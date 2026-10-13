"""League-only accounting and stable seat/model attribution, collected on the slow floor."""
from datetime import date

from .competition import number, text
from .config import SLOW_SECONDS
from .game_metrics import day
from .sql import attribution_rows, identifier


def amount(value):
    # PostgreSQL numeric aggregates are JSON decimal strings; reject non-finite values below.
    value = number(float(value) if isinstance(value, str) else value)
    if value is None or value < 0:
        raise ValueError("Missing or negative attribution amount")
    return value


def count(value):
    value = amount(value)
    if int(value) != value:
        raise ValueError("Fractional attribution count")
    return int(value)


def daily_spend(api, league, now):
    end = int(now)
    start = end - 30 * 86400
    rows = attribution_rows(api, "daily_spend", league, start, end)
    for row in rows:
        date.fromisoformat(row["day"])
        if not day(start) <= row["day"] <= day(end) or row["source"] not in (
                "tournament", "xp_request", "coworld_persistent"):
            raise ValueError("Unscoped daily spend")
        for key in ("compute", "llm", "week_compute", "week_llm"):
            row[key] = amount(row[key])
    # Replacing the entire bounded window also replaces every corrected hour in the last 48 hours.
    return {"rows": rows, "start": start, "end": end, "week_start": end - 7 * 86400}


def seat_models(api, league, now):
    end = int(now)
    start = end - 7 * 86400
    rows = attribution_rows(api, "seat_models", league, start, end)
    for row in rows:
        row["episode"] = "ereq_" + identifier("ereq_" + row["episode"], "ereq_")
        row["slot"] = count(row["slot"])
        if row["slot"] > 6:
            raise ValueError("Invalid attribution slot")
        if row["failure_day"] is not None:
            date.fromisoformat(row["failure_day"])
        row["policy_version_id"] = identifier("pv_" + row["policy_version_id"], "pv_")
        row["policy_id"] = identifier("pol_" + row["policy_id"], "pol_")
        row["coworld_id"] = "cow_" + identifier(row["coworld_id"], "cow_")
        row["policy"] = text(row["policy"])
        if not isinstance(row["model"], str):
            raise ValueError("Invalid model label")
        if row["player_id"] is not None:
            row["player_id"] = text(row["player_id"])
        if row["player"] is not None:
            row["player"] = text(row["player"])
        for key in ("calls", "failed", "version"):
            row[key] = count(row[key])
        row["usd"] = amount(row["usd"])
        row["created_at"] = amount(row["created_at"])
        if not start <= row["created_at"] < end or row["failed"] > row["calls"]:
            raise ValueError("Invalid provider attribution facts")
    return {"rows": rows, "start": start, "end": end}


def attempts(api, league, now):
    end = int(now)
    rows = attribution_rows(api, "attempts", league, end - 7 * 86400, end)
    for row in rows:
        if row["failure_day"] is not None:
            date.fromisoformat(row["failure_day"])
        row["policy_version_id"] = identifier("pv_" + row["policy_version_id"], "pv_")
        if not isinstance(row["model"], str):
            raise ValueError("Invalid model label")
        for key in ("attempts", "not_ok", "refused"):
            row[key] = count(row[key])
        if max(row["not_ok"], row["refused"]) > row["attempts"]:
            raise ValueError("Invalid attempt attribution facts")
    return {"rows": rows, "start": end - 7 * 86400, "end": end}


def collect_attribution(collector, leagues):
    for league in leagues:
        scope = league["id"]
        for name, fetch in (("daily_spend", daily_spend), ("seat_models", seat_models), ("attempts", attempts)):
            collector.poll(name, scope, lambda: fetch(collector.api, scope, collector.clock()),
                           cadence=SLOW_SECONDS, floor=SLOW_SECONDS)
        budget = collector.store.source("budgets", "all")
        if budget and budget["data"] and not budget["error"]:
            for row in budget["data"]["leagues"]:
                if row["league_id"] == scope:
                    collector.store.success("budget_limits", scope,
                        {"day": day(budget["fetched_at"]), "limit": row["daily_budget_usd"]},
                        budget["fetched_at"], observed=True, cadence=SLOW_SECONDS)
