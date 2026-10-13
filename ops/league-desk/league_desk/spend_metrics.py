"""Cost/experience readings from the cache; every denominator keeps its native scope."""

from collections import Counter, defaultdict
from statistics import mean

from .config import MODEL_ERROR_RATE, MODEL_MIN_CALLS, SEAT_NEAR_CAP, SLOW_SECONDS
from .freshness import annotate
from .game_metrics import day, fmt, minutes, panel, quantile
from .metrics import money


def source_label(source):
    return {"tournament": "League rounds", "xp__request": "Experience requests",
            "xp_request": "Experience requests"}.get(source, source)


def source_spend(data):
    rows = data.get("rows", [])
    if not rows:
        return panel(
            "Comparable source costs unavailable.", note="No attributed rows; this is not proof of zero spend."
        )
    total = sum(r["combined_estimated_cost_usd"] for r in rows)
    return panel(
        f"{money(total)} attributed to this league across the listed sources.",
        ["Source", "Compute", "Estimated LLM", "Combined estimate"],
        [
            [
                source_label(r["source"]),
                money(r["compute_cost_usd"]),
                money(r["llm_estimated_cost_usd"]),
                money(r["combined_estimated_cost_usd"]),
            ]
            for r in rows
        ],
        "Native API week, all versions; only requests attributed to this league. "
        "Unattributed experience requests are not included. Compute and estimated LLM are distinct measures.",
        {
            "kind": "bars",
            "data": [
                {"day": source_label(r["source"]), "series": "Combined estimate",
                 "value": r["combined_estimated_cost_usd"]}
                for r in rows
            ],
            "label": "USD", "x_label": "Attributed source",
        },
    )


def model_usage(data):
    groups = defaultdict(lambda: {"calls": 0, "errors": 0, "spend": 0, "policies": set(), "players": set()})
    for row in data.get("rows", []):
        group = groups[row["model"], row["role"], row["source"]]
        group["calls"] += row["invocations"]
        group["errors"] += row["error_count"]
        group["spend"] += row["estimated_cost_usd"]
        if row["policy"]:
            group["policies"].add(row["policy"])
        if row["player"]:
            group["players"].add(row["player"])
    alerts, rows = [], []
    for (model, role, source), group in sorted(groups.items(), key=lambda item: -item[1]["spend"]):
        n, errors = group["calls"], group["errors"]
        if n >= MODEL_MIN_CALLS and errors / n > MODEL_ERROR_RATE:
            alerts.append(f"Family-wide {model}: {errors}/{n} calls failed ({role}, {source_label(source)}).")
        rows.append(
            [model, role, source_label(source), n, errors, f"{errors / n:.1%}" if n else "unknown",
             money(group["spend"]), len(group["policies"]), len(group["players"])]
        )
    result = panel(
        alerts[0]
        if alerts
        else f"{sum(g['calls'] for g in groups.values())} observed calls across "
        f"{len({key[0] for key in groups})} model labels."
        if groups
        else "No model usage observed.",
        ["Model", "Role", "Source", "Calls", "Errors", "Failure rate", "Estimated USD",
         "Policy labels", "Player labels"],
        rows,
        "Entire webDiplomacy family, both leagues and experience requests, all versions; native API week. "
        "Display labels are not stable policy identities. No configured-model or model-free-policy inference.",
    )
    model_sources = defaultdict(float)
    for (model, role, source), group in groups.items():
        model_sources[model, source_label(source)] += group["spend"]
    totals = Counter()
    for (model, source), amount in model_sources.items():
        totals[model] += amount
    result["chart"] = {"kind": "models", "label": "Estimated USD", "order": list(dict(totals.most_common())),
                       "data": [{"model": model, "source": source, "value": value}
                                for (model, source), value in model_sources.items()]}
    return result, alerts


def seat_spend(data, games, cap):
    by_id = {g["id"]: g for g in games}
    rows, amounts, rejections, near, keyed = [], [], 0, 0, {}
    points = []
    for row in data.get("rows", []):
        game = by_id.get(row["episode"])
        seat = next((s for s in game["seats"] if s["slot"] == row["slot"]), None) if game else None
        if seat is None:
            continue
        keyed[row["episode"], row["slot"]] = row["estimated"]
        amounts.append(row["estimated"])
        points.append({"key": seat["player_id"] or f"unattributed:{row['episode']}:{row['slot']}",
                       "player": seat["player"] or "Unattributed seat", "slot": row["slot"],
                       "value": row["estimated"]})
        rejections += row["rejections"]
        near += cap is not None and row["estimated"] >= cap * SEAT_NEAR_CAP
        rows.append(
            [
                seat["player"] or "Unattributed seat",
                row["slot"],
                row["calls"],
                money(row["estimated"]),
                row["rejections"],
                money(cap),
            ]
        )
    sentence = (
        f"{rejections:g} recorded spend-limit rejections across {len(rows)} seats with usage."
        if rejections
        else f"{near} seats are near or above the current cap reference."
        if near
        else f"{len(rows)} seats with usage, median estimate {money(quantile(amounts, 0.5))}."
        if rows
        else "No attributed per-seat usage; missing rows do not establish zero spend."
    )
    result = panel(
        sentence,
        ["Player", "Slot", "Calls", "Estimated USD", "Rejections", "Current cap reference"],
        rows,
        f"SQL player-role sums across provider/hour facts. {len(data.get('ids', []))}/"
        f"{data.get('eligible', 0)} eligible games queried; no-row seats remain unknown. "
        "Cap is today's reference, not the historical game cap. Estimates at a cap do not prove rejection.",
    )
    grouped = defaultdict(list)
    for point in points:
        grouped[point["key"]].append(point["value"])
    order = sorted(grouped, key=lambda key: (-quantile(grouped[key], .5), key))
    result["chart"] = {"kind": "seat-dots", "label": "Estimated USD / seat-game", "reference": cap,
                       "order": order, "data": points}
    return result, keyed, [sentence] if rejections else []


def unit_costs(games, details, rounds, episode_sources):
    eligible = {g["id"] for g in games if g["status"] == "completed" and g["completed_at"] is not None}
    covered = {
        key: source["data"]["compute"]
        for key, source in details.items()
        if key in eligible and source.get("data") and source["data"]["compute"] is not None
    }
    round_costs = []
    for rd in rounds:
        source = episode_sources.get(rd["id"])
        ids = {g["id"] for g in source["data"]["rows"]} if source and source.get("data") else set()
        if rd["status"] == "completed" and ids and ids <= covered.keys():
            round_costs.append(sum(covered[key] for key in ids))
    result = panel(
        f"Compute {money(mean(round_costs) if round_costs else None)}/round and "
        f"{money(mean(covered.values()) if covered else None)}/game over covered completed games.",
        ["Measure", "Value"],
        [
            ["Covered / eligible completed games", f"{len(covered)}/{len(eligible)}"],
            ["Fully covered rounds", len(round_costs)],
            ["Covered compute", money(sum(covered.values()))],
        ]
        if covered
        else [],
        "Detail API compute only; game denominator includes cost-covered completions in the selected window. "
        "Round means require every listed game covered and completed in that window. "
        "Per-round LLM is not reconciled and stays unknown.",
    )

    result["chart"] = {"kind": "amounts", "label": "Mean compute USD", "data": [
        {"label": label, "value": mean(values)} for label, values in
        (("Covered round", round_costs), ("Covered game", list(covered.values()))) if values]}
    return result


def request_series(requests, complete):
    groups = Counter((day(r["created_at"]), r["requester_id"]) for r in requests)
    labels = {r["requester_id"]: r["requester"] for r in requests}
    rows = [[date, labels[requester], count] for (date, requester), count in sorted(groups.items())]
    return panel(
        f"{len(requests)} observed requests from {len(labels)} requesters."
        + (" Version/window coverage incomplete." if not complete else ""),
        ["Pacific creation day", "Requester (local only)", "Requests"],
        rows,
        "Selected variant, versions and creation window. Today is partial. "
        "Private requesters stay in this localhost cache; request counts are not episode counts.",
        {
            "kind": "bars",
            "data": [{"day": d, "series": labels[p], "key": p, "value": n} for (d, p), n in sorted(groups.items())],
            "label": "Requests",
        },
    )


def request_durations(requests, games):
    groups = defaultdict(lambda: {"requests": [], "play": [], "queue": [], "failed": 0})
    ids = {r["id"]: r["variant"] for r in requests}
    for row in requests:
        group = groups[row["variant"] or "Unknown variant"]
        duration = minutes(row["created_at"], row["completed_at"])
        if row["status"] == "completed" and duration is not None:
            group["requests"].append(duration)
        group["failed"] += row["status"] == "failed"
    for game in games:
        if game["request_id"] not in ids or game["status"] != "completed":
            continue
        group = groups[ids[game["request_id"]] or "Unknown variant"]
        for key, start, end in (("play", "running_at", "completed_at"), ("queue", "created_at", "dispatched_at")):
            value = minutes(game[start], game[end])
            if value is not None:
                group[key].append(value)
    rows = [
        [
            variant,
            fmt(quantile(g["play"], 0.5)),
            len(g["play"]),
            fmt(quantile(g["queue"], 0.5)),
            fmt(quantile(g["requests"], 0.9)),
            len(g["requests"]),
            g["failed"],
        ]
        for variant, g in sorted(groups.items())
    ]
    result = panel(
        "Request completion and episode play use separate clocks and covered samples."
        if rows
        else "No completed request or episode timing collected.",
        [
            "Variant",
            "Median play min",
            "Timed games",
            "Median queue min",
            "Request p90 min",
            "Timed requests",
            "Failed requests",
        ],
        rows,
        "Request completion = completed − created; play = completed − running; queue = dispatched − created. "
        "Only fetched game details contribute. Overrides are shown separately, with no inferred shortening.",
    )

    result["chart"] = {"kind": "amounts", "label": "Minutes (separate samples)", "data": [
        {"label": f"{variant} · {label}", "value": quantile(group[key], fraction)}
        for variant, group in sorted(groups.items())
        for key, label, fraction in (("play", "play median", .5), ("queue", "queue median", .5),
                                    ("requests", "request p90", .9)) if group[key]]}
    return result


def override_frequency(requests, data):
    ids = {r["id"] for r in requests}
    rows = [r for r in data.get("rows", []) if r["id"] in ids]
    counts = Counter((key, str(value)) for row in rows for key, value in row["values"].items())
    ordered = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    result = panel(
        f"{ordered[0][0][0]} is set to {ordered[0][0][1]} in {ordered[0][1]}/{len(rows)} inspected requests."
        if ordered
        else "No allowlisted overrides found in inspected requests."
        if rows
        else "Stored request overrides not yet collected.",
        ["Config key", "Value", "Requests", "Inspected"],
        [[key, value, n, len(rows)] for (key, value), n in ordered],
        f"{len(rows)}/{len(ids)} selected requests inspected. Only allowlisted scalar keys are read; "
        "notes, rosters and arbitrary values never enter the cache. No version-default comparison is available.",
    )

    result["chart"] = {"kind": "amounts", "label": "Inspected requests", "data": [
        {"label": f"{key} = {value}", "value": n} for (key, value), n in ordered]}
    return result


def spending_panels(snapshot, league, now, competition, start=None, version="all"):
    start = now - 7 * 86400 if start is None else start
    scope = league["id"] if league else ""

    def source(name, key="all"):
        return snapshot.get((name, key), {})

    def data(name, key="all"):
        return source(name, key).get("data") or {}

    variant = "classic-" + (league["key"] if league else "press")
    scans = [s for (name, _), s in snapshot.items() if name == "requests"]
    requests = {r["id"]: r for state in scans if state.get("data") for r in state["data"]["rows"]}
    request_details = [s for (name, _), s in snapshot.items() if name == "request_detail" and s.get("data")]
    for state in request_details:
        row = state["data"]
        if state["fetched_at"] >= requests.get(row["id"], {}).get("seen_at", 0):
            requests[row["id"]] = row
    selected = [
        r
        for r in requests.values()
        if r["variant"] == variant and r["created_at"] is not None and start <= r["created_at"] <= now
        and (version == "all" or r["coworld_id"] == version)
    ]
    versions = [v for v in data("versions").get("rows", []) if version == "all" or v["id"] == version]
    complete = bool(versions) and all(
        all((source("requests", v["id"]).get("data") or {}).get(key) for key in ("backfilled", "complete"))
        for v in versions
    )
    details = {key: s for (name, key), s in snapshot.items() if name == "detail"}
    games = [
        g
        for state in competition["episode_sources"].values()
        for g in state["data"]["rows"]
        if (version == "all" or g["coworld_id"] == version)
        and (g["completed_at"] if g["completed_at"] is not None else g["created_at"]) is not None
        and start <= (g["completed_at"] if g["completed_at"] is not None else g["created_at"]) <= now
    ]
    models, model_alerts = model_usage(data("models"))
    seat_panel, amounts, seat_alerts = seat_spend(
        data("seats", scope), games, data("settings", scope).get("seat_cap_usd")
    )
    panels = {
        "Daily spend against budget": panel(
            "Tournament daily cost breakdown is unavailable from these sources.",
            note="The available family-wide daily costs include experience requests and cannot be compared to this "
            "league's tournament budget. The Now strip retains actual spend, projection and reset time.",
        ),
        "League against experience requests": source_spend(data("costs", scope)),
        "Models in use": models,
        "LLM spend per seat per game": seat_panel,
        "Cost per round and per game": unit_costs(
            games, details, data("rounds", scope).get("rows", []), competition["episode_sources"]
        ),
        "Requests per day": request_series(selected, complete),
        "How long they take": request_durations(selected, [s["data"] for s in details.values() if s.get("data")]),
        "Common config overrides": override_frequency(selected, data("overrides")),
    }
    panels["Requests per day"]["chart"]["markers"] = competition.get("version_markers", [])
    for name in ("League against experience requests", "Models in use"):
        panels[name]["note"] += " Range/version controls do not apply: native API week, all versions."
    panels["LLM spend per seat per game"]["note"] += (
        " Selection uses cached coverage; the SQL collector only scans unfinished or last-seven-day games.")
    request_deps = [source("versions")] + [source("requests", v["id"]) for v in versions]
    selected_details = {s["data"]["id"]: s for s in request_details if s["data"]["id"] in {r["id"] for r in selected}}
    expected_games = {key for s in selected_details.values() for key in s["data"]["episode_ids"]}
    timing_deps = [selected_details.get(r["id"], {}) for r in selected] + [
        details.get(key, {}) for key in expected_games
    ]
    panels["How long they take"]["note"] += (
        f" {len(selected_details)}/{len(selected)} selected request details collected; "
        f"{sum(bool(details.get(key, {}).get('data')) for key in expected_games)}/{len(expected_games)} "
        "listed game details; "
        f"{sum(len(s['data']['episode_ids']) != s['data']['episode_count'] for s in selected_details.values())} "
        "request episode listings differ from their declared count."
    )
    deps = {
        "Daily spend against budget": [source("budgets")],
        "League against experience requests": [source("costs", scope)],
        "Models in use": [source("models")],
        "LLM spend per seat per game": [source("seats", scope)],
        "Cost per round and per game": [details.get(g["id"], {}) for g in games] or [{}],
        "Requests per day": request_deps,
        "How long they take": request_deps + timing_deps,
        "Common config overrides": request_deps + [source("overrides")],
    }
    for name, result in panels.items():
        annotate(result, deps[name], now, cadence=SLOW_SECONDS if name not in ("Requests per day",) else 300)
        result["coverage"] = result["note"]
    # Only stable seat/player joins can enrich standings; model labels lack stable IDs.
    player_costs = defaultdict(list)
    for game in games:
        if game["status"] != "completed" or game["completed_at"] is None:
            continue
        own = defaultdict(list)
        for seat in game["seats"]:
            if seat["player_id"] and not seat["filler"]:
                own[seat["player_id"]].append((game["id"], seat["slot"]))
        for player, keys in own.items():
            if all(key in amounts for key in keys):
                player_costs[player].append(sum(amounts[key] for key in keys))
    return {
        "spend_panels": panels,
        "spend_alerts": model_alerts + seat_alerts,
        "player_costs": player_costs,
        "slow_next_due": max(
            (
                s.get("next_due", 0)
                for (name, _), s in snapshot.items()
                if name in ("costs", "models", "seats", "overrides")
            ),
            default=0,
        ),
    }
