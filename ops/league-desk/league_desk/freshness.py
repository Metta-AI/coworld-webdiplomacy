"""Panel refresh contracts, independent of retry deadlines."""

from .config import COMPETITION_SECONDS, POLL_SECONDS, RECONCILE_SECONDS, SLOW_SECONDS


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
        age = max(0, int(now - fetched(source))) if fetched(source) is not None else None
        threshold = 2 * max(cadence, interval)
        if name == "requests":
            threshold = 2 * source.get("revisit_seconds", COMPETITION_SECONDS)
        expired = age is not None and age > threshold
        panel["stale"] |= bool(source.get("error")) or expired
        data = source.get("data") or {}
        rows = data.get("rows", data.get("leagues", []))
        panel["sources"].append({"name": name, "age": age, "rows": len(rows),
                                 "stale": bool(source.get("error")) or expired, "error": source.get("error"),
                                 "threshold": threshold})
    panel.setdefault("coverage", "")
