"""Panel refresh contracts, independent of retry deadlines."""

import math

from .config import (
    COMPETITION_SECONDS,
    HISTORY_PAGES,
    PAGE_SIZE,
    POLL_SECONDS,
    RECONCILE_SECONDS,
    SEAT_BATCH,
    SLOW_SECONDS,
)


def age_label(seconds):
    if seconds is None:
        return "not collected"
    return f"{seconds / 60:.0f} min old" if seconds > 120 else f"{seconds} s old"


def annotate(panel, dependencies, now, cadence=COMPETITION_SECONDS):
    def fetched(source):
        value = source.get("fetched_at")
        data = source.get("data") or {}
        checks = [] if source.get("name") == "overrides" else data.get("checked_at", {}).values()
        candidates = [value, data.get("recent_through"), *checks]
        return min((v for v in candidates if v is not None), default=None)

    ages = [max(0, int(now - fetched(d))) for d in dependencies if fetched(d) is not None]
    panel["age"] = max(ages) if ages else None
    panel["newest"] = min(ages) if ages else None
    panel["missing"] = sum(d.get("data") is None for d in dependencies)
    panel["stale"] = False
    panel["sources"] = []
    for source in dependencies:
        name = source.get("name", "uncollected source")
        interval = {
            "versions": RECONCILE_SECONDS,
            "costs": SLOW_SECONDS,
            "daily_spend": SLOW_SECONDS,
            "seat_models": SLOW_SECONDS,
            "attempts": SLOW_SECONDS,
            "models": SLOW_SECONDS,
            "seats": SLOW_SECONDS,
            "overrides": SLOW_SECONDS,
            "detail": SLOW_SECONDS,
            "rounds": POLL_SECONDS,
        }.get(name, COMPETITION_SECONDS)
        if name in ("episodes", "request_detail", "detail") and source.get("fetched_at") is not None:
            interval = max(interval, source["next_due"] - source["fetched_at"])
        if name == "detail" and (source.get("data") or {}).get("completed_at") is not None:
            interval = RECONCILE_SECONDS  # A finished game's cost is only re-read daily for late usage.
        if name == "seats":
            # Seats rotate through eligible games one batch per pass; the oldest check is a full rotation old.
            batches = math.ceil((source.get("data") or {}).get("eligible", 0) / SEAT_BATCH)
            interval = SLOW_SECONDS * max(1, batches)
        age = max(0, int(now - fetched(source))) if fetched(source) is not None else None
        threshold = 2 * max(cadence, interval)
        if name == "requests":
            # A walk reads HISTORY_PAGES pages per visit and only advances recent_through when it finishes.
            listed = len((source.get("data") or {}).get("rows", []))
            visits = max(1, math.ceil(listed / (HISTORY_PAGES * PAGE_SIZE)))
            threshold = 2 * visits * source.get("revisit_seconds", COMPETITION_SECONDS)
        expired = age is not None and age > threshold
        panel["stale"] |= bool(source.get("error")) or expired
        data = source.get("data") or {}
        rows = data.get("rows", data.get("leagues", []))
        panel["sources"].append({"name": name, "age": age, "rows": len(rows),
                                 "stale": bool(source.get("error")) or expired, "error": source.get("error"),
                                 "threshold": threshold})
    panel.setdefault("coverage", "")


def grouped(sources):
    """One display row per source name; the member closest to its stale threshold speaks for the group.

    Panels can depend on thousands of per-game sources. The page re-ages every row each second, so
    rendering them individually made a 2 MB fragment and a slow tab.
    """
    groups = {}
    for source in sources:
        group = groups.setdefault(source["name"], {**source, "count": 0, "rows": 0, "error": None})
        group["count"] += 1
        group["rows"] += source["rows"]
        group["error"] = group["error"] or source["error"]
        group["stale"] = group["stale"] or source["stale"]
        # Immutable artifacts carry the string "Infinity" for the browser; float() reads it.
        if source["age"] is not None and (group["age"] is None or float(source["threshold"]) - source["age"]
                                          < float(group["threshold"]) - group["age"]):
            group["age"], group["threshold"] = source["age"], source["threshold"]
    return list(groups.values())
