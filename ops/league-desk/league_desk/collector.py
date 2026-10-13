"""One synchronous collector; each source keeps its last complete successful result."""
import fcntl
import math
import random
import time
from contextlib import contextmanager

from .api import ApiError, logged_in_api
from .config import LEAGUES, POLL_SECONDS
from .dates import timestamp


def number(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("invalid number")
    return value


def text(value):
    if not isinstance(value, str) or not value:
        raise ValueError("missing string")
    return value


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
            "seat_cap_usd": number(row["episode_player_pod_llm_spend_limit_usd"])}


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

    def poll(self, name, scope, fetch, observed=False):
        now = self.clock()
        previous = self.store.source(name, scope)
        if now < self.store.retry_not_before() or previous and now < previous["next_due"]:
            return
        try:
            data = fetch()
        except (ApiError, ValueError, KeyError, TypeError, IndexError, AttributeError) as error:
            message = str(error) if isinstance(error, ApiError) else "Unexpected response shape; last data retained"
            failures = previous["failures"] if previous else 0
            delay = min(900, POLL_SECONDS * 2 ** min(failures, 4)) + random.uniform(0, 1)
            if isinstance(error, ApiError) and error.retry_after:
                delay = max(delay, error.retry_after)
                self.store.defer(self.clock() + error.retry_after)
            self.store.failure(name, scope, message, self.clock(), delay)
        else:
            self.store.success(name, scope, data, self.clock(), observed)

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
        while True:
            if time.time() >= store.retry_not_before():
                try:
                    with logged_in_api() as api:
                        Collector(store, api).once()
                except ApiError as error:
                    store.failure("discovery", "all", str(error), time.time(), POLL_SECONDS)
                    store.defer(time.time() + POLL_SECONDS)
            if once:
                return
            time.sleep(POLL_SECONDS)
