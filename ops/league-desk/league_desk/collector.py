"""One synchronous collector; sources retain successful data and explicit scan progress."""
import fcntl
import random
import time
from contextlib import contextmanager

from .api import ApiError, logged_in_api
from .competition import episode, memberships, number, ratings, round_row, scan, submission, text
from .config import COMPETITION_SECONDS, EPISODE_ROUNDS_PER_POLL, LEAGUES, POLL_SECONDS, RECONCILE_SECONDS
from .dates import timestamp


def discovery(api):
    games = [r for r in api.pages("/v2/games") if r.get("coworld_name") == "webdiplomacy"]
    if len(games) != 1:
        raise ValueError("ambiguous game")
    game = games[0]
    leagues = []
    for row in api.pages("/v2/leagues", {"game_id": text(game["id"])}):
        if row.get("hidden") or row.get("disabled_at"):
            continue
        variant = (row.get("commissioner_config") or {}).get("default_variant_id")
        if variant in LEAGUES:
            leagues.append({"id": text(row["id"]), "key": LEAGUES[variant], "name": text(row["name"])})
    if len({r["key"] for r in leagues}) != len(leagues):
        raise ValueError("ambiguous active league")
    return {"coworld_id": text(game["canonical_coworld_id"]), "leagues": leagues}


def canonical(api, coworld_id):
    row = api.json(f"/v2/coworlds/{coworld_id}")
    if row["id"] != coworld_id or row["name"] != "webdiplomacy" or row["canonical"] is not True:
        raise ValueError("canonical changed during collection")
    return {"id": coworld_id, "version": text(row["version"])}


def budgets(api, leagues):
    payload = api.json("/v2/budgets")
    ids = {row["id"] for row in leagues}
    rows = []
    for row in payload["leagues"]:
        if row["league_id"] in ids:
            rows.append({"league_id": row["league_id"], **{
                key: number(row[key]) for key in (
                    "daily_budget_usd", "spent_today_usd", "projected_today_usd", "remaining_today_usd",
                )}, "status": text(row["status"])})
    if len({r["league_id"] for r in rows}) != len(rows):
        raise ValueError("duplicate budget")
    return {"as_of": timestamp(payload["as_of"]), "resets_at": timestamp(payload["resets_at"]), "leagues": rows}


def settings(api, league_id):
    row = api.json(f"/v2/leagues/{league_id}/settings")["settings"]
    return {"round_interval_minutes": number(row["round_interval_minutes"]),
            "seat_cap_usd": number(row["episode_player_pod_llm_spend_limit_usd"]),
            "game_target": number((row.get("ladder") or {}).get("scheduler", {}).get("min_episodes_per_entrant")),
            "divisions": [{"id": text(d["division_id"]),
                           "failure_limit": number(d.get("disqualify_after_consecutive_failures"))}
                          for d in (row.get("ladder") or {}).get("divisions", [])]}


def health(api, league_id):
    rows = api.json("/v2/leagues/health", {"league_id": league_id})
    row, = [r for r in rows if r["league_id"] == league_id]
    # These are compact recent summaries, not a full history or a 24-hour game count.
    return {"rounds": [{"status": text(r["status"]), "created_at": timestamp(r["created_at"]),
                        "completed_at": timestamp(r["completed_at"])} for r in row["rounds"]]}


def latest_round(api, league_id):
    page = api.page("/v2/rounds", {"league_id": league_id, "limit": 1})
    return {"rounds": [{"number": number(r["round_number"]), "status": text(r["status"]),
                        "created_at": timestamp(r["created_at"]), "completed_at": timestamp(r["completed_at"])}
                       for r in page.entries], "coverage": "Latest listed round only"}


class Collector:
    def __init__(self, store, api, clock=time.time):
        self.store, self.api, self.clock = store, api, clock
        self.manual = False

    def poll(self, name, scope, fetch, observed=False, cadence=POLL_SECONDS, force=False, floor=0):
        now = self.clock()
        previous = self.store.source(name, scope)
        force |= self.manual and name in {"discovery", "canonical", "budgets", "settings", "health",
                                          "round", "rounds", "memberships", "submissions", "ratings"}
        if previous and previous["error"]:
            force = False
        if now < self.store.retry_not_before() or previous and now < previous["next_due"] and not force:
            return
        if previous and floor and now < (previous["attempted_at"] or 0) + floor:
            return
        if floor:
            self.store.reserve(name, scope, now, floor)
        try:
            data = fetch()
        except (ApiError, ValueError, KeyError, TypeError, IndexError, AttributeError) as error:
            message = str(error) if isinstance(error, ApiError) else "Unexpected response shape; last data retained"
            failures = previous["failures"] if previous else 0
            delay = max(floor, min(900, POLL_SECONDS * 2 ** min(failures, 4)) + random.uniform(0, 1))
            if isinstance(error, ApiError) and error.retry_after:
                delay = max(delay, error.retry_after)
                self.store.defer(self.clock() + error.retry_after)
            self.store.failure(name, scope, message, self.clock(), delay)
        else:
            # A callable cadence picks the next refresh from what was just fetched (e.g. a finished game).
            cadence = cadence(data) if callable(cadence) else cadence
            self.store.success(name, scope, data, self.clock(), observed, cadence)

    def once(self):
        self.poll("discovery", "all", lambda: discovery(self.api))
        source = self.store.source("discovery", "all")
        if not source or source["data"] is None:
            return
        data = source["data"]
        self.poll("canonical", "all", lambda: canonical(self.api, data["coworld_id"]), observed=True)
        self.poll("budgets", "all", lambda: budgets(self.api, data["leagues"]))
        for league in data["leagues"]:
            for name, fetch in (("settings", settings), ("health", health), ("round", latest_round)):
                self.poll(name, league["id"], lambda: fetch(self.api, league["id"]), observed=name == "settings")
            self.competition(league["id"], data["coworld_id"])
        from .spending import collect_spending
        collect_spending(self, data)
        from .artifacts import collect_artifacts
        collect_artifacts(self)

    def competition(self, league_id, canonical_id):
        def cached(name):
            return (self.store.source(name, league_id) or {}).get("data") or {}

        self.poll("rounds", league_id, lambda: scan(
            self.api, "/v2/rounds", {"league_id": league_id}, round_row,
            self.store.source("rounds", league_id), self.clock()))
        rounds = cached("rounds").get("rows", [])
        # Old unfinished/hidden rounds still need reconciliation; never drop them on a reset.
        candidates = []
        for row in rounds:
            source = self.store.source("episodes", row["id"])
            cadence = POLL_SECONDS if row["completed_at"] is None else (
                COMPETITION_SECONDS if self.clock() - row["completed_at"] < RECONCILE_SECONDS else RECONCILE_SECONDS)
            needs_labels = bool(source and source.get("data") and any(
                "policy_label" not in seat for game in source["data"]["rows"] for seat in game["seats"]))
            if not source or self.clock() >= source["next_due"] or needs_labels:
                candidates.append((source["fetched_at"] or 0 if source else 0, row, cadence, needs_labels))
        for _, row, cadence, needs_labels in sorted(
                candidates, key=lambda item: (item[0], item[1]["id"]))[:EPISODE_ROUNDS_PER_POLL]:
            def fetch_episodes(row=row):
                return {"league_id": league_id, "round_id": row["id"], "rows": [episode(r) for r in
                        self.api.pages(f"/v2/rounds/{row['id']}/episodes")]}
            self.poll("episodes", row["id"], fetch_episodes, cadence=cadence, force=needs_labels)
        self.poll("memberships", league_id, lambda: memberships(self.api, league_id),
                  cadence=COMPETITION_SECONDS)
        self.poll("submissions", league_id, lambda: scan(
            self.api, "/v2/league-submissions", {"league_id": league_id}, submission,
            self.store.source("submissions", league_id), self.clock()), cadence=COMPETITION_SECONDS)
        divisions = cached("settings").get("divisions", [])
        if divisions:
            completed = sorted(r["id"] for r in rounds if r["status"] == "completed")
            previous = self.store.source("ratings", league_id)
            force = bool(previous and not previous["error"] and
                         (previous["data"] or {}).get("completed_rounds") != completed)

            def fetch_ratings():
                result = ratings(self.api, league_id, divisions, rounds, canonical_id)
                result["poll_gap"] = bool(previous and previous["fetched_at"] is not None and
                                          self.clock() - previous["fetched_at"] > COMPETITION_SECONDS * 2)
                return result
            self.poll("ratings", league_id, fetch_ratings, observed=True, cadence=COMPETITION_SECONDS, force=force)


@contextmanager
def collector_lock(directory):
    with (directory / "collector.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ApiError("A collector already owns this cache") from None
        yield


def collect(store, once=False):
    store.initialize()
    with collector_lock(store.directory):
        next_poll = 0
        while True:
            manual = store.take_refresh()
            if (manual or time.time() >= next_poll) and time.time() >= store.retry_not_before():
                try:
                    with logged_in_api() as api:
                        collector = Collector(store, api)
                        collector.manual = manual
                        collector.once()
                except ApiError as error:
                    store.failure("discovery", "all", str(error), time.time(), POLL_SECONDS)
                    store.defer(time.time() + POLL_SECONDS)
                next_poll = time.time() + POLL_SECONDS
            if once:
                return
            time.sleep(1)
