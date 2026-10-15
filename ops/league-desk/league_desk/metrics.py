"""Current health strip from a single cache snapshot; no API calls."""
from .alerts import alert
from .config import COMPETITION_SECONDS, CREDITS_PER_USD, ROUND_STALL_SECONDS, STALE_SECONDS
from .dates import when

# The platform's round admission gates (metta RoundRefusalCause).
REFUSAL_CAUSES = {"coworld_envelope": "the daily budget is spent", "league_pool": "the league credit pool is too low"}


def money(value):
    return f"${value:,.2f}" if value is not None else "unknown"


def credits_label(value):
    return f"{value:,.0f} credits" if value is not None else "unknown"


def duration(seconds):
    hours, minutes = divmod(int(seconds) // 60, 60)
    return f"{hours} h {minutes} min" if hours else f"{minutes} min"


def round_alerts(latest, interval_minutes, health, scope, now):
    """Rounds stopped starting, and the platform's own reason when its admission check refused one."""
    result = []
    check = (health or {}).get("budget_check")
    if check and check["refusal_cause"]:
        reason = REFUSAL_CAUSES.get(check["refusal_cause"], check["refusal_cause"])
        result.append(alert(f"Round scheduling is blocked: {reason} (platform check at {when(check['checked_at'])}).",
                            scope, "round-refused", [check["refusal_cause"], latest and latest["number"]]))
    if latest and latest["created_at"] is not None:
        threshold = max(ROUND_STALL_SECONDS, 2 * 60 * interval_minutes if interval_minutes else 0)
        gap = now - latest["created_at"]
        if gap > threshold:
            result.append(alert(f"No new round for {duration(gap)}: round {latest['number']} "
                                f"({latest['status']}) started {when(latest['created_at'])}.",
                                scope, "round-stall", [latest["number"]]))
    return result


def desk(snapshot, league_key, now):
    def source(name, scope="all"):
        return snapshot.get((name, scope), {})

    discovery = source("discovery").get("data") or {}
    league = next((r for r in discovery.get("leagues", []) if r["key"] == league_key), None)
    scope = league["id"] if league else ""
    settings = source("settings", scope).get("data") or {}
    round_data = source("round", scope).get("data") or {}
    canonical = source("canonical").get("data") or {}
    budget_data = source("budgets").get("data") or {}
    health = source("health", scope).get("data")
    budget = next((r for r in budget_data.get("leagues", []) if r["league_id"] == scope), {})
    credit = source("credits", scope).get("data") or {}
    pool = credit.get("pool_credits")
    members = (source("memberships", scope).get("data") or {}).get("rows", [])
    submissions = (source("submissions", scope).get("data") or {}).get("rows", [])
    active = sum(m["status"] == "competing" and m["substatus"] == "active" for m in members)
    day_submissions = sum(s["created_at"] is not None and now - 86400 <= s["created_at"] <= now for s in submissions)
    rounds = round_data.get("rounds", [])
    latest = rounds[0] if rounds else None
    interval = settings.get("round_interval_minutes")
    now_rows = [
        {"title": "Latest listed round", "source": "round", "scope": scope,
         "text": f"Round {latest['number']}: {latest['status']}. Created {when(latest['created_at'])}."
         if latest else "No round collected.", "note": "Due time and game counts are not yet available."},
        {"title": "Next round", "source": "settings", "scope": scope,
         "text": "Next scheduled slot is not exposed by the collected sources.",
         "note": f"Current interval: {interval:g} minutes." if interval is not None else "Interval not collected."},
        {"title": "Budget today", "source": "budgets", "scope": "all",
         "text": f"{money(budget.get('spent_today_usd'))} of {money(budget.get('daily_budget_usd'))}"
         if budget else "Budget has not been collected.",
         "note": f"Projected {money(budget.get('projected_today_usd'))}; reset {when(budget_data.get('resets_at'))}."
         if budget else "Tournament spending only."},
        {"title": "Credit pool", "source": "credits", "scope": scope, "threshold": 2 * COMPETITION_SECONDS,
         "text": f"{credits_label(pool)} ({money(pool / CREDITS_PER_USD)})" if pool is not None
         else "Credit pool has not been collected.",
         "note": (f"Today: +{credits_label(credit.get('granted_today_credits'))} granted, "
                  f"−{credits_label(credit.get('play_charged_today_credits'))} play, "
                  f"−{credits_label(credit.get('paid_today_credits'))} rewards. "
                  "Rounds stop when the pool cannot cover the next one.") if credit
         else "The league's own funding; refilled once per Pacific day."},
        {"title": "Coworld", "source": "canonical", "scope": "all",
         "text": canonical.get("version", "Canonical version not confirmed."),
         "note": "Canonical first observed in this cache at " + when(source("canonical").get("observed_at"))
         + "; not a release timestamp."},
        {"title": "Policies", "source": "memberships", "scope": scope, "threshold": 2 * COMPETITION_SECONDS,
         "text": f"{active} active · {day_submissions} submitted in 24 h"
         if source("memberships", scope).get("data") is not None else "Memberships not collected.",
         "note": "Active competing memberships; submissions are every listed upload, all versions."},
        {"title": "Last 24 h", "source": "health", "scope": scope,
         "text": "Game, retry and failure counts are not yet collected.",
         "note": (f"Health summary covers {len(health['rounds'])} recently listed rounds; not 24-hour game totals."
                  if health is not None else "Health summary not collected.")},
    ]
    relevant = [source("discovery"), source("canonical"), source("budgets")]
    relevant += [source(name, scope) for name in ("settings", "health", "round", "credits")]
    ages = []
    for row in now_rows:
        state = source(row["source"], row["scope"])
        fetched = state.get("fetched_at")
        if row["source"] == "budgets" and budget_data.get("as_of") is not None and fetched is not None:
            fetched = min(fetched, budget_data["as_of"])
        row["age"] = max(0, int(now - fetched)) if fetched is not None else None
        row["error"] = state.get("error")
        row["stale"] = bool(row["error"]) or row["age"] is not None and row["age"] > row.get("threshold", STALE_SECONDS)
        if row["age"] is not None:
            ages.append(row["age"])
    discovery_time = source("discovery").get("fetched_at")
    if discovery_time is not None:
        ages.append(max(0, int(now - discovery_time)))
    alerts = []
    if source("discovery").get("error"):
        alerts.append(source("discovery")["error"])
    if any(row["stale"] for row in now_rows):
        alerts.append("Some sources failed or are stale; their last good data is retained.")
    spent, limit = budget.get("spent_today_usd"), budget.get("daily_budget_usd")
    projection = budget.get("projected_today_usd")
    if spent is not None and limit is not None and spent > limit:
        alerts.append(f"Budget exceeded: {money(spent)} of {money(limit)}.")
    elif projection is not None and limit is not None and projection > limit:
        alerts.append(f"Projected spend {money(projection)} exceeds the {money(limit)} budget.")
    if pool is not None and pool <= 0:
        alerts.append(f"Credit pool is empty: {credits_label(pool)}. No round can start until it is refilled.")
    alerts += round_alerts(latest, interval, health, scope, now)
    return {"league": league, "now_rows": now_rows, "alerts": alerts,
            "age": max(ages) if ages else None, "missing": sum(r.get("data") is None for r in relevant),
            "time": when(now), "budget_available": bool(budget),
            "meter": ({"value": spent, "limit": limit,
                       "alert": spent > limit or projection is not None and projection > limit}
                      if spent is not None and limit is not None and limit > 0 else None)}
