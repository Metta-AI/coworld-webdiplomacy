"""Slow spend/SQL snapshots and bounded experience-request history; no remote writes."""

from datetime import datetime, timezone
from math import ceil

from .competition import episode, identity, number, scan, text
from .config import (
    COMPETITION_SECONDS,
    DETAILS_PER_POLL,
    POLL_SECONDS,
    RECONCILE_SECONDS,
    REQUEST_DETAILS_PER_POLL,
    SEAT_BATCH,
    SLOW_SECONDS,
    XP_VERSIONS_PER_POLL,
)
from .dates import timestamp
from .sql import OVERRIDES, select_rows


def iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def versions(api):
    return {
        "rows": [
            {"id": identity(r), "version": text(r["version"]), "created_at": timestamp(r["created_at"])}
            for r in api.pages("/v2/coworlds/summaries", {"limit": 500})
            if r["name"] == "webdiplomacy"
        ]
    }


def request_row(row):
    return {
        "id": identity(row),
        "coworld_id": row["coworld_id"],
        "version": row["coworld_version"],
        "variant": row["variant_id"],
        "requester_id": row["requester_user_id"],
        "requester": row["requester"],
        "status": row["status"],
        "episode_count": number(row["episode_count"]),
        **{key: timestamp(row[key]) for key in ("created_at", "started_at", "completed_at")},
    }


def request_history(api, version, previous, now):
    old = (previous or {}).get("data") or {}
    earliest = version["created_at"]
    if earliest is None:
        raise ValueError("Missing version creation time")
    if old.get("cursor"):
        start, end = old["window_start"], old["window_end"]
    elif old.get("complete") and not old.get("backfilled"):
        end = old["window_start"]
        start = max(earliest, end - 30 * 86400)
    else:
        end, start = now, max(earliest, now - (7 if old.get("backfilled") else 30) * 86400)
    result = scan(
        api,
        "/v2/experience-requests",
        {"coworld_id": version["id"], "event": "created", "start": iso(start), "end": iso(end)},
        lambda row: {**request_row(row), "seen_at": now},
        previous,
        now,
    )
    if any(r["coworld_id"] != version["id"] for r in result["rows"]):
        raise ValueError("Unscoped request")
    result.update(
        recent_through=max(old.get("recent_through", 0), end),
        window_start=start,
        window_end=end,
        backfilled=old.get("backfilled", False) or result["complete"] and start == earliest,
    )
    return result


def details(api, game_id):
    raw = api.json(f"/v2/episode-requests/{game_id}")
    if raw["id"] != game_id:
        raise ValueError("Unscoped game")
    return {**episode(raw), "compute": number(raw["cost_usd"]), "request_id": raw["experience_request_id"]}


def costs(api, league_id):
    payload = api.json("/admin/costs/leagues", {"period": "week", "league_id": league_id})
    if payload["period"] != "week":
        raise ValueError("Wrong cost period")
    rows = [
        {
            "source": r["source"],
            **{k: number(r[k]) for k in ("compute_cost_usd", "llm_estimated_cost_usd", "combined_estimated_cost_usd")},
        }
        for r in payload["leagues"]
        if r["league_id"] == league_id
    ]
    if any(
        r[k] is None
        for r in rows
        for k in ("compute_cost_usd", "llm_estimated_cost_usd", "combined_estimated_cost_usd")
    ):
        raise ValueError("Incomplete cost amounts")
    if any(
        abs(r["compute_cost_usd"] + r["llm_estimated_cost_usd"] - r["combined_estimated_cost_usd"]) > 1e-6 for r in rows
    ):
        raise ValueError("Cost components do not reconcile")
    if len({r["source"] for r in rows}) != len(rows):
        raise ValueError("Duplicate source cost")
    return {"period": "week", "rows": rows}


def models(api):
    payload = api.json("/admin/llm-coworld-usage", {"period": "week"})
    if payload["period"] != "week":
        raise ValueError("Wrong model period")
    result = {
        "period": "week",
        "rows": [
            {
                "coworld_id": r["coworld_id"],
                "model": r["model_id"],
                "role": r["role"],
                "source": r["source"],
                "policy": r["policy_name"],
                "player": r["player_name"],
                **{k: number(r[k]) for k in ("invocations", "error_count", "estimated_cost_usd")},
            }
            for r in payload["rows"]
            if r["coworld"] == "webdiplomacy"
        ],
    }

    if any(r[k] is None for r in result["rows"] for k in ("invocations", "error_count", "estimated_cost_usd")):
        raise ValueError("Incomplete model amounts")
    return result


def seats(api, ids):
    rows = []
    for r in select_rows(api, "seats", ids):
        if not str(r["slot"]).isdecimal():
            raise ValueError("Unknown player slot")
        rows.append(
            {
                "episode": "ereq_" + r["episode"],
                "slot": int(r["slot"]),
                **{k: number(r[k]) for k in ("calls", "estimated", "rejections")},
            }
        )
    if any(r[k] is None for r in rows for k in ("calls", "estimated", "rejections")):
        raise ValueError("Incomplete seat amounts")
    return {"ids": sorted(ids), "rows": rows}


def overrides(api, ids):
    rows = []
    for r in select_rows(api, "overrides", ids):
        selected = {}
        for key in OVERRIDES:
            value = r[key]
            if value is None:
                continue
            if key == "press":
                if value not in ("none", "full"):
                    continue
            elif key == "render_maps":
                if not isinstance(value, bool):
                    continue
            elif isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            else:
                value = number(value)
            selected[key] = value
        rows.append({"id": r["request"], "values": selected})
    return {"ids": sorted(ids), "rows": rows}


def request_interval(version_id, canonical_id, version_count):
    """Reserve one poll slot for canonical; bound the remaining version rotation."""
    if version_id == canonical_id:
        return COMPETITION_SECONDS
    return max(COMPETITION_SECONDS, ceil(max(0, version_count - 1) / (XP_VERSIONS_PER_POLL - 1)) * POLL_SECONDS)


def collect_spending(collector, discovery):
    store, api, now = collector.store, collector.api, collector.clock()
    poll = collector.poll
    canonical_id = discovery["coworld_id"]
    catalog = (store.source("versions", "all") or {}).get("data") or {}
    # A new canonical release must not wait out the daily catalog refresh: its requests are listed per version.
    known = any(r["id"] == canonical_id for r in catalog.get("rows", []))
    missing = bool(catalog) and not known
    # The floor bounds retries to one per five minutes if the catalog still lacks it.
    poll("versions", "all", lambda: versions(api), cadence=RECONCILE_SECONDS, force=missing,
         floor=COMPETITION_SECONDS if missing else 0)
    catalog = (store.source("versions", "all") or {}).get("data") or {}
    pending = []
    for version in catalog.get("rows", []):
        old = store.source("requests", version["id"])
        if not old or now >= old["next_due"]:
            pending.append((old["fetched_at"] or 0 if old else 0, version, old))
    pending.sort(key=lambda r: (r[1]["id"] != canonical_id, r[0], -(r[1]["created_at"] or 0)))
    for _, version, old in pending[:XP_VERSIONS_PER_POLL]:
        poll(
            "requests",
            version["id"],
            lambda: request_history(api, version, old, collector.clock()),
            cadence=request_interval(version["id"], canonical_id, len(catalog.get("rows", []))),
        )
    snapshot = store.snapshot()
    requests = {
        r["id"]: r
        for (name, _), state in snapshot.items()
        if name == "requests" and state["data"]
        for r in state["data"]["rows"]
    }
    due = []
    for row in requests.values():
        state = snapshot.get(("request_detail", row["id"]))
        if not state or now >= state["next_due"]:
            due.append((state["fetched_at"] or 0 if state else 0, row))
    due.sort(key=lambda r: (r[0], -r[1]["created_at"]))
    active = None
    for item in due:
        state = snapshot.get(("request_detail", item[1]["id"]), {}).get("data") or item[1]
        if item[0] and state["completed_at"] is None:
            active = item
            break
    rest = REQUEST_DETAILS_PER_POLL - bool(active)
    chosen = ([active] if active else []) + [item for item in due if item != active][:rest]
    for _, row in chosen:

        def fetch_request(row=row):
            raw = api.json(f"/v2/experience-requests/{row['id']}")
            # The detail embeds episodes but does not promise continuation; use the paginated ID listing.
            games = api.pages("/v2/episode-requests", {"ids": row["id"], "view": "results"})
            if raw["id"] != row["id"] or any(g["experience_request_id"] != row["id"] for g in games):
                raise ValueError("Unscoped request episodes")
            return {
                **request_row(raw),
                "seen_at": collector.clock(),
                "episode_ids": [identity(g) for g in games],
            }

        poll(
            "request_detail",
            row["id"],
            fetch_request,
            cadence=COMPETITION_SECONDS if row["completed_at"] is None else RECONCILE_SECONDS,
        )
    snapshot = store.snapshot()
    games = {
        g["id"]: g
        for (name, _), state in snapshot.items()
        if name == "episodes" and state["data"]
        for g in state["data"]["rows"]
    }
    ids = set(games)
    for (name, _), state in snapshot.items():
        if name == "request_detail" and state["data"]:
            ids.update(state["data"]["episode_ids"])

    def detail_cadence(data):
        return RECONCILE_SECONDS if data["completed_at"] is not None else SLOW_SECONDS

    def priority(key):
        # League games first, so a flood of newly listed experience-request games cannot starve them;
        # then unfetched and unfinished games, so daily re-reads of finished games do not starve those.
        state = snapshot.get(("detail", key), {})
        finished = (state.get("data") or {}).get("completed_at") is not None
        return key not in games, finished, state.get("fetched_at") or 0, key

    due = [key for key in ids if now >= snapshot.get(("detail", key), {}).get("next_due", 0)]
    for key in sorted(due, key=priority)[:DETAILS_PER_POLL]:
        poll("detail", key, lambda: details(api, key), cadence=detail_cadence)
    from .attribution import collect_attribution

    collect_attribution(collector, discovery["leagues"])
    for league in discovery["leagues"]:
        poll("costs", league["id"], lambda: costs(api, league["id"]), cadence=SLOW_SECONDS, floor=SLOW_SECONDS)
        eligible = sorted(
            g["id"]
            for (name, _), state in snapshot.items()
            if name == "episodes" and state["data"] and state["data"]["league_id"] == league["id"]
            for g in state["data"]["rows"]
            if g["completed_at"] is None or g["completed_at"] >= now - 7 * 86400
        )
        old = (store.source("seats", league["id"]) or {}).get("data") or {}
        # Rotate bounded chunks; each chunk replaces its prior rows to pick up delayed usage.
        batch = eligible[old.get("offset", 0) : old.get("offset", 0) + SEAT_BATCH] or eligible[:SEAT_BATCH]
        if batch:

            def fetch_seats():
                result = seats(api, batch)
                retained = [r for r in old.get("rows", []) if r["episode"] not in batch and r["episode"] in eligible]
                return {
                    "rows": retained + result["rows"],
                    "ids": sorted(set(old.get("ids", [])) & set(eligible) | set(batch)),
                    "offset": (eligible.index(batch[-1]) + 1) % len(eligible),
                    "eligible": len(eligible),
                    "checked_at": {
                        **{key: value for key, value in old.get("checked_at", {}).items() if key in eligible},
                        **{key: collector.clock() for key in batch},
                    },
                }

            poll("seats", league["id"], fetch_seats, cadence=SLOW_SECONDS, floor=SLOW_SECONDS)
    old = (store.source("overrides", "all") or {}).get("data") or {}
    request_ids = sorted(requests)
    batch = request_ids[old.get("offset", 0) : old.get("offset", 0) + 50] or request_ids[:50]
    if batch:

        def fetch_overrides():
            result = overrides(api, batch)
            return {
                "rows": [r for r in old.get("rows", []) if r["id"] not in batch] + result["rows"],
                "offset": (request_ids.index(batch[-1]) + 1) % len(request_ids),
                "checked_at": {**old.get("checked_at", {}), **{key: collector.clock() for key in batch}},
            }

        poll("overrides", "all", fetch_overrides, cadence=SLOW_SECONDS, floor=SLOW_SECONDS)
