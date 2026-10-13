"""Selected API fields and bounded, resumable competition/history scans."""
import math

from .api import ApiError
from .config import HISTORY_PAGES, PAGE_SIZE
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


def identity(row):
    return text(row["id"])


def membership(row):
    policy, player = row["policy_version"], row["player"]
    return {"id": identity(row), "player_id": identity(player), "player": player["name"],
            "policy_id": identity(policy), "policy": policy["policy"]["name"], "version": policy["version"],
            "division_id": identity(row["division"]), "status": row["status"], "substatus": row["substatus"],
            "champion": row["is_champion"], "created_at": timestamp(row["created_at"])}


def submission(row):
    return {"id": identity(row), "player_id": identity(row["player"]), "player": row["player"]["name"],
            "policy_id": identity(row["policy_version"]), "status": row["status"],
            "created_at": timestamp(row["created_at"])}


def round_row(row):
    config = row.get("round_config") or {}
    entrants = config.get("entrant_attributions")
    return {"id": identity(row), "number": number(row["round_number"]), "status": row["status"],
            "created_at": timestamp(row["created_at"]), "completed_at": timestamp(row["completed_at"]),
            "skip_kind": row.get("skip_kind"), "division_id": (row.get("division") or {}).get("id"),
            "entrants": sorted({r["subject_id"] for r in entrants if r["subject_type"] == "player"})
            if isinstance(entrants, list) else None}


def episode(row):
    scores = {}
    for score in row["participant_scores"]:
        position = score["position"]
        if position in scores:
            raise ValueError("duplicate score position")
        scores[position] = number(score["score"])
    seats = []
    for seat in row["participants"]:
        if not isinstance(seat["is_filler"], bool):
            raise ValueError("missing filler attribution")
        seats.append({"slot": seat["position"], "player_id": seat.get("player_id"),
                      "player": seat.get("player_name"), "policy_id": seat.get("policy_version_id"),
                      "policy_label": (f"{seat['policy_name']} v{seat['version']}"
                                       if seat.get("policy_name") and seat.get("version") is not None else None),
                      "filler": seat["is_filler"], "seed": seat["is_seed"], "score": scores.get(seat["position"])})
    if len({s["slot"] for s in seats}) != len(seats):
        raise ValueError("duplicate seat")
    return {"id": identity(row), "episode_id": row["episode_id"], "coworld_id": row["coworld_id"],
            "version": row["coworld_version"], "variant": row["variant_name"], "status": row["status"],
            "error_type": row["error_type"], "seats": seats,
            **{key: timestamp(row[key]) for key in ("created_at", "dispatched_at", "running_at", "completed_at")}}


def scan(api, path, params, parse, previous, now):
    """Walk complete listings without assuming ordering; preserve older rows with visibility provenance.

    Two pages per poll bound work. Cursors/seen IDs survive restarts. A bad walk
    restarts at the head next time, retaining the last committed partial history.
    """
    old = (previous or {}).get("data") or {}
    restarting = bool((previous or {}).get("error"))
    cursor = None if restarting else old.get("cursor")
    seen = set(old.get("seen", [])) if cursor else set()
    cursors = set(old.get("cursors", [])) if cursor else set()
    rows = {r["id"]: dict(r) for r in old.get("rows", [])}
    complete = False
    for _ in range(HISTORY_PAGES):
        page = api.page(path, {**params, "limit": PAGE_SIZE, **({"cursor": cursor} if cursor else {})})
        for raw in page.entries:
            row = parse(raw)
            if row["id"] in seen:
                raise ApiError("Repeated row in history scan; restarting next poll")
            seen.add(row["id"])
            rows[row["id"]] = {**row, "listed": True}
        if page.complete:
            complete = True
            cursor = None
            for row in rows.values():
                row["listed"] = row["id"] in seen
            break
        cursor = page.next_cursor
        if not cursor or cursor in cursors:
            raise ApiError("Incomplete history cursor; restarting next poll")
        cursors.add(cursor)
    return {"rows": sorted(rows.values(), key=lambda r: r["id"]), "cursor": cursor,
            "seen": sorted(seen) if cursor else [], "cursors": sorted(cursors) if cursor else [],
            "complete": complete, "completed_at": now if complete else old.get("completed_at"),
            "scan_started": old.get("scan_started", now) if old.get("cursor") and not restarting else now}


def memberships(api, league_id):
    return {"rows": [membership(r) for r in api.pages("/v2/league-policy-memberships", {"league_id": league_id})]}


def ratings(api, league_id, divisions, rounds, canonical_id):
    """Bracket every view with its generation and the commissioner state; never invent historical points."""
    state_path = f"/v2/leagues/{league_id}/commissioner-state"
    for _ in range(2):
        state = api.json(state_path)
        rankings = {(r["division_id"], r["standing"]["subject_id"]): r["standing"]["ranking"]
                    for r in state["state"]["standings"] if r["standing"]["subject_type"] == "player"}
        rows, generations, raced = [], {}, False
        for division in divisions:
            path = f"/v2/divisions/{division['id']}"
            before = api.json(path + "/leaderboard/summary")["snapshot_version"]
            payload = api.json(path + "/leaderboards")
            view, = [v for v in payload["views"] if v["key"] == payload["default_view_key"]]
            after = api.json(path + "/leaderboard/summary")["snapshot_version"]
            if before != after:
                raced = True
                break
            generations[division["id"]] = after
            for row in view["rows"]:
                if row["subject_type"] != "player":
                    continue
                values = row["values"]
                rank = rankings.get((division["id"], row["subject_id"]), {})
                selected = {key: number(values.get(key)) for key in ("mu", "sigma", "rating", "rounds_played")}
                if selected["sigma"] is not None and selected["sigma"] < 0:
                    raise ValueError("invalid rating interval")
                rows.append({"player_id": row["subject_id"], "player": row["subject_name"],
                             "division_id": division["id"], "policies": row["policy_version_ids"], **selected,
                             "last_round_id": rank.get("last_round_id"),
                             "failures": number(rank.get("consecutive_failures")),
                             "current_policy_id": rank.get("current_policy_version_id"),
                             "failure_limit": division["failure_limit"]})
        if not raced and api.json(state_path)["version"] == state["version"]:
            return {"rows": sorted(rows, key=lambda r: (r["division_id"], r["player_id"])),
                    "generations": generations, "canonical_id": canonical_id,
                    "completed_rounds": sorted(r["id"] for r in rounds if r["status"] == "completed"),
                    "visible_rounds": sorted(r["id"] for r in rounds if r.get("listed"))}
    raise ApiError("Ratings changed during collection; last consistent observation retained")
