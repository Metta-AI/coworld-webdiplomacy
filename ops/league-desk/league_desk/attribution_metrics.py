"""Readings from bounded league accounting snapshots; labels never join identities."""
from collections import defaultdict

from .alerts import model_alerts
from .game_metrics import day, panel
from .metrics import money


def reconciliation(daily, costs):
    if not daily or not costs:
        return "Rolling seven-day reconciliation pending: both SQL and API snapshots are required."
    totals = defaultdict(lambda: [0, 0])
    for row in daily["rows"]:
        for i, key in enumerate(("week_compute", "week_llm")):
            totals[row["source"]][i] += row[key]
    api = {r["source"].replace("xp__request", "xp_request"):
           [r["compute_cost_usd"], r["llm_estimated_cost_usd"]] for r in costs["rows"]}
    differences = [abs(totals[source][i] - api.get(source, [0, 0])[i])
                   for source in set(totals) | set(api) for i in range(2)]
    largest = max(differences, default=0)
    return (f"Reconciliation mismatch: largest source/component difference {money(largest)}. "
            "SQL and API fetch times or corrections may differ." if largest > .0100001 else
            "Rolling seven-day compute and LLM totals reconcile to the API within $0.01 per source/component.")


def daily_panels(data, costs, budget, start, now):
    rows = [r for r in data.get("rows", []) if day(start) <= r["day"] <= day(now)]
    budgets = {r["data"]["day"]: r["data"]["limit"] for r in budget.get("history", [])}
    if budget.get("data"):
        budgets[budget["data"]["day"]] = budget["data"]["limit"]
    note = ("Pacific dates touched by the range, not exact clock hours; first/last days may be partial. "
            "All Coworld versions; the version control does not "
            "apply. The latest 30 days are replaced each poll, including the mutable last 48 hours. "
            "Today and the previous two days are provisional. Lobby spend is excluded to match the API. "
            + reconciliation(data, costs))
    tournament = [r for r in rows if r["source"] == "tournament"]
    total = sum(r["compute"] + r["llm"] for r in tournament)
    daily = panel(f"{money(total)} league-round spend in the displayed Pacific days." if data else
                  "League daily accounting has not been collected.",
                  ["Pacific day", "Compute USD", "Estimated LLM USD", "Total USD", "Observed budget reference"],
                  [[r["day"], money(r["compute"]), money(r["llm"]), money(r["compute"] + r["llm"]),
                    money(budgets.get(r["day"]))] for r in tournament],
                  note + " Budget references begin when observed; the latest observation on each day is shown. "
                  "Unobserved days have no budget line; this is not reconstructed budget history.",
                  {"kind": "daily-spend", "label": "USD", "data": [
                      {"day": r["day"], "series": label, "value": r[key]}
                      for r in tournament for key, label in (("compute", "Compute"), ("llm", "Estimated LLM"))],
                   "budgets": [{"day": d, "value": value} for d, value in sorted(budgets.items())
                               if value is not None and d in {r["day"] for r in tournament}]})
    comparable = [r for r in rows if r["source"] in ("tournament", "xp_request")]
    source_names = {"tournament": "League rounds", "xp_request": "Experience requests"}
    comparison = panel("Daily league-round and attributed experience-request costs are shown separately." if data else
                       "Daily source accounting has not been collected.",
                       ["Pacific day", "Source", "Compute USD", "Estimated LLM USD", "Total USD"],
                       [[r["day"], source_names[r["source"]], money(r["compute"]), money(r["llm"]),
                         money(r["compute"] + r["llm"])] for r in comparable],
                       note + " Only experience requests attributed to this league are included.",
                       {"kind": "source-days", "label": "USD", "data": [
                           {"day": r["day"], "series": source_names[r["source"]], "value": r["compute"] + r["llm"]}
                           for r in comparable]})
    return daily, comparison


def attributed_models(data, attempt_data, games, start, now, version, scope=""):
    # The raw event cohort is game creation, deliberately distinct from accounting bucket time.
    selected = [r for r in data.get("rows", []) if start <= r["created_at"] <= now and
                (version == "all" or r["coworld_id"] == version)]
    selected_keys = {(r["episode"], r["slot"], r["model"]) for r in selected}
    groups = {}
    seat_amounts = {}
    for row in data.get("rows", []):
        key = (row["player_id"], row["policy_version_id"])
        group = groups.setdefault(key, {"label": f"{row['player'] or 'Unowned'} · {row['policy']} v{row['version']}",
            "calls": 0, "failed": 0, "usd": 0, "attempts": 0, "not_ok": 0, "refused": 0,
            "models": defaultdict(float), "requested": set(), "seats": set()})
        group["seats"].add((row["episode"], row["slot"]))
        for key in ("calls", "failed", "usd"):
            group[key] += row[key]
        if row["calls"]:
            group["models"][row["model"] or "Unknown resolved model"] += row["usd"]
        if (row["episode"], row["slot"], row["model"]) not in selected_keys:
            continue
        seat = seat_amounts.setdefault((row["episode"], row["slot"]),
                                      {"episode": row["episode"], "slot": row["slot"], "estimated": 0,
                                       "calls": 0, "rejections": None, "models": set()})
        seat["estimated"] += row["usd"]
        seat["calls"] += row["calls"]
        if row["calls"]:
            seat["models"].add(row["model"] or "Unknown resolved model")
    by_policy = {policy: group for (_, policy), group in groups.items()}
    unmatched = 0
    for row in attempt_data.get("rows", []):
        group = by_policy.get(row["policy_version_id"])
        if group is None:
            unmatched += 1
            continue
        for key in ("attempts", "not_ok", "refused"):
            group[key] += row[key]
        group["requested"].add(row["model"] or "Unknown requested model")
    rows, chart, policy_models = [], defaultdict(float), defaultdict(set)
    for (player, policy), group in sorted(groups.items(), key=lambda pair: (-pair[1]["usd"], pair[0][1])):
        label = group["label"]
        observed = ", ".join(sorted(group["models"])) or "No provider calls observed"
        rows.append([label, observed, ", ".join(sorted(group["requested"])) if attempt_data else "not collected",
                     len(group["seats"]), group["calls"], group["failed"],
                     f"{group['failed']/group['calls']:.1%}" if group["calls"] else "no provider calls",
                     group["attempts"] if attempt_data else "unknown", group["not_ok"] if attempt_data else "unknown",
                     f"{group['not_ok']/group['attempts']:.1%}" if group["attempts"] else
                     "no attempts observed" if attempt_data else "unknown",
                     group["refused"] if attempt_data else "unknown", money(group["usd"])])
        for model, usd in group["models"].items():
            chart[model] += usd
    alerts = model_alerts(data.get("rows", []), attempt_data.get("rows", []), scope)
    result = panel(alerts[0]["message"] if alerts else
                   f"No provider calls observed across {len(groups)} player/policy versions with covered league seats."
                   if data and not any(g["calls"] for g in groups.values()) else
                   f"{len(groups)} player/policy versions with covered league seats." if data else
                   "League model attribution has not been collected.",
                   ["Player · policy version", "Resolved models", "Requested models (attempts)", "Seats",
                    "Provider calls", "Provider failures", "Provider failure rate", "Attempts", "Not OK",
                    "Attempt failure rate", "Refused", "Provider billed USD"], rows,
                   "League tournament seats, games created in the last seven days; "
                   "range/version controls do not apply here. "
                   "Stable episode/slot, policy-version and player joins; labels are display only. "
                   "Attempt failures include pre-provider failures and refusals; "
                   "they are not added to provider failures. "
                   "Requested models describe observed attempts, not an inspected policy configuration. "
                   "No provider calls observed does not prove a model-free policy; "
                   "raw events can arrive late or expire. "
                   f"{unmatched} attempt model rows lack a provider-seat policy match and are omitted.",
                   {"kind": "pie", "label": "Provider billed USD",
                    "data": [{"label": model, "value": usd}
                             for model, usd in sorted(chart.items(), key=lambda item: -item[1])]})
    for row in selected:
        models = policy_models[row["policy_version_id"]]
        if row["calls"]:
            models.add(row["model"] or "Unknown resolved model")
    seats = {"rows": [{**r, "models": sorted(r["models"])} for r in seat_amounts.values()],
             "ids": sorted({key[0] for key in seat_amounts}), "eligible": len({g["id"] for g in games})}
    return result, alerts, seats, {p: ", ".join(sorted(models)) or "No provider calls observed"
                                   for p, models in policy_models.items()}
