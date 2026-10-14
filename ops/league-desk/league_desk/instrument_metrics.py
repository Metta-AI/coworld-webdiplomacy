"""Game-clustered policy readings from selected, terminal public instrumentation."""
from collections import defaultdict

from .config import MIN_SHARED_GAMES
from .game_metrics import fmt, panel, quantile
from .instrumentation import supported


def median(values):
    return quantile(values, .5) if values else None


def percent(value):
    return f"{value:.1%}" if value is not None else "unknown"


def coverage(n, total):
    return f"From Coworld 0.7.12; {n} of {total} games covered. Older games and missing facts are unknown. "


def complete_activity(facts, log):
    phases = {(p["turn"], p["phase"]): p for p in facts.get("phases", []) if p["natural_end"]}
    return [(phases[p["turn"], p["phase"]], p["seats"]) for p in log.get("activity") or []
            if (p["turn"], p["phase"]) in phases]


def ready_panel(games, results, logs, labels, current, total):
    groups, covered = defaultdict(list), set()
    for game_id, game in games.items():
        facts = results.get(game_id, {}).get("instrumentation", {})
        for phase, seats in complete_activity(facts, logs.get(game_id, {})):
            covered.add(game_id)
            for seat in game["seats"]:
                activity = seats[seat["slot"]]
                if activity is not None and seat["policy_id"] in current:
                    group = "Movement" if phase["phase"] == "Diplomacy" else "Retreat/build"
                    groups[seat["policy_id"], group].append((game_id, phase["length"], activity))
    rows, points = [], []
    for (policy, phase), observations in sorted(groups.items()):
        # One median per game before the across-game median: long games do not dominate timing.
        per_game = defaultdict(list)
        for game_id, length, activity in observations:
            value = activity["first_ready_seconds"]
            if length is not None and value is not None:
                per_game[game_id].append(value/length)
        n = len({g for g, _, _ in observations})
        values = [median(v) for v in per_game.values() if v]
        never = sum(a["first_ready_seconds"] is None for _, _, a in observations)
        rows.append([labels.get(policy, "Unlisted policy"), phase, n, len(observations),
                     percent(median(values)), len(values),
                     f"{never}/{len(observations)} ({percent(never/len(observations))})"])
        if len(values) >= MIN_SHARED_GAMES:
            points.append({"label": labels.get(policy, "Unlisted policy"), "series": phase, "n": len(values),
                           "value": median(values)*100, "value_label": percent(median(values))})
    sentence = (f"{len(groups)} policy/phase groups; {len(points)} Ready estimates meet the five-game floor."
                if groups else "No complete phases with order activity are covered yet for the competing policies.")
    return panel(sentence, ["Policy version", "Phase type", "Games", "Seat phases with orders due",
                 "Median first Ready / phase length", "Ready games", "Never Ready"], rows,
                 "Currently competing policies only. " + coverage(len(covered), total) +
                 "Phase length is observed deadline minus first phase timestamp; absent deadlines stay unknown. "
                 "Timing is the median of each game's median share; never-Ready is a seat-phase share. "
                 "First Saved is still recorded in the game log but not shown here. "
                 "Null seats have no orders due and are excluded. Final Finished-bound/incomplete phases are censored, "
                 "including adapter-cut-short endings. Sampling is about 0.25 s and can miss brief Ready states. "
                 "Charts require five measured games per timing estimate; smaller samples remain in the table.",
                 {"kind": "paired-dots", "label": "Median first Ready, % of phase length", "data": points})


def health_panel(games, results, logs, labels, current, total):
    groups, covered = defaultdict(list), set()
    for game_id, game in games.items():
        facts = results.get(game_id, {}).get("instrumentation", {})
        if facts.get("health") is None:
            continue
        covered.add(game_id)
        activity = complete_activity(facts, logs.get(game_id, {}))
        for seat in game["seats"]:
            if seat["policy_id"] not in current:
                continue
            health = facts["health"][seat["slot"]]
            connections = health["connections"]
            first = next((e["elapsed_seconds"] for e in connections if e["event"] in ("connect", "reconnect")), None)
            start = facts.get("first_phase_seconds")
            due = [seats[seat["slot"]] for _, seats in activity if seats[seat["slot"]] is not None]
            groups[seat["policy_id"]].append({"game": game_id,
                "disconnects": sum(e["event"] == "disconnect" for e in connections),
                "reconnects": sum(e["event"] == "reconnect" for e in connections),
                "late": first > start if first is not None and start is not None else None,
                "no_connect": first is None, "api": health["api_requests"],
                "no_saved": any(s["first_saved_seconds"] is None for s in due) if due else None})
    rows, points = [], []
    for policy, seats in sorted(groups.items()):
        by_game = defaultdict(list)
        for seat in seats:
            by_game[seat["game"]].append(seat)
        api = [sum(s["api"] for s in group) for group in by_game.values() if all(s["api"] is not None for s in group)]
        due = [group for group in by_game.values() if any(s["no_saved"] is not None for s in group)]
        no_saved = sum(any(s["no_saved"] is True for s in group) for group in due)
        late = [s["late"] for s in seats if s["late"] is not None]
        rows.append([labels.get(policy, "Unlisted policy"), len(by_game), sum(s["disconnects"] for s in seats),
                     sum(s["reconnects"] for s in seats), f"{sum(late)}/{len(late)}",
                     sum(s["no_connect"] for s in seats), f"{no_saved}/{len(due)}", fmt(median(api))])
        if len(due) >= MIN_SHARED_GAMES:
            points.append({"label": labels.get(policy, "Unlisted policy"), "value": no_saved/len(due)*100,
                           "value_label": percent(no_saved/len(due))})
    worst = max(points, key=lambda p: p["value"], default=None)
    return panel((f"{len(groups)} current policies observed; {worst['label']} left a due phase unsaved in "
                  f"{worst['value_label']} of games." if worst and worst["value"] else
                  f"{len(groups)} current policies observed; none left a due phase unsaved.") if groups else
                 "No instrumented seat health is covered yet for the competing policies.",
                 ["Policy version", "Games", "Disconnects", "Reconnects", "Late first connect (timed seats)",
                  "Never connected seats", "Unsaved due phase (games with orders due)", "Median API requests/game"],
                 rows, "Currently competing policies only. " +
                 coverage(len(covered), total) + "Late means first connection after the first observed order phase; "
                 "never connected is separate. Reconnect includes takeover without prior disconnect. "
                 "No-Saved counts games with at least one uncensored due seat-phase never Saved; absent log coverage "
                 "is unknown. API counts sum owned seats within each game and include the bot, browser tunnel and "
                 "archive worker; cancelled counts stay unknown. They are context, not an alert. Pod loss is not "
                 "observable here; verified platform failure-streak alerts are unchanged. Charts require five covered "
                 "games.", {"kind": "amounts", "label": "% of games with an unsaved due phase",
                            "order": [p["label"] for p in sorted(points, key=lambda p: -p["value"])], "data": points})


def instrumentation_panels(games, results, logs, labels, current):
    selected = {k: g for k, g in games.items() if supported(g.get("version"))}
    total = len(games)
    return {"Time to Ready": ready_panel(selected, results, logs, labels, current, total),
            "Seat health": health_panel(selected, results, logs, labels, current, total)}
