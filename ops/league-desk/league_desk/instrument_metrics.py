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


def ready_panel(games, results, logs, labels, total):
    groups, covered = defaultdict(list), set()
    for game_id, game in games.items():
        facts = results.get(game_id, {}).get("instrumentation", {})
        for phase, seats in complete_activity(facts, logs.get(game_id, {})):
            covered.add(game_id)
            for seat in game["seats"]:
                activity = seats[seat["slot"]]
                if activity is not None and seat["policy_id"]:
                    group = "Movement" if phase["phase"] == "Diplomacy" else "Retreat/build"
                    groups[seat["policy_id"], group].append((game_id, phase["length"], activity))
    rows, points = [], []
    for (policy, phase), observations in sorted(groups.items()):
        # One median per game before the across-game median: long games do not dominate timing.
        per_game = defaultdict(lambda: {"saved": [], "ready": []})
        for game_id, length, activity in observations:
            for name in ("saved", "ready"):
                value = activity[f"first_{name}_seconds"]
                if length is not None and value is not None:
                    per_game[game_id][name].append(value/length)
        n = len({g for g, _, _ in observations})
        values = {name: [median(v[name]) for v in per_game.values() if v[name]] for name in ("saved", "ready")}
        never = sum(a["first_ready_seconds"] is None for _, _, a in observations)
        rows.append([labels.get(policy, "Unlisted policy"), phase, n, len(observations),
                     percent(median(values["saved"])), len(values["saved"]), percent(median(values["ready"])),
                     len(values["ready"]), f"{never}/{len(observations)} ({percent(never/len(observations))})"])
        for name in ("saved", "ready"):
            if len(values[name]) >= MIN_SHARED_GAMES:
                points.append({"label": f"{labels.get(policy, 'Unlisted policy')} · {phase} · {name.title()}",
                               "value": median(values[name])*100, "value_label": percent(median(values[name]))})
    sentence = (f"{len(groups)} policy/phase groups; {len(points)} timing estimates meet the five-game floor."
                if groups else "No complete phases with order activity are covered yet.")
    return panel(sentence, ["Policy version", "Phase type", "Games", "Seat phases with orders due",
                 "Median first Saved / phase length", "Saved games", "Median first Ready / phase length", "Ready games",
                 "Never Ready"], rows, coverage(len(covered), total) +
                 "Phase length is observed deadline minus first phase timestamp; absent deadlines stay unknown. "
                 "Timing is the median of each game's median share; never-Ready is a seat-phase share. "
                 "Null seats have no orders due and are excluded. Final Finished-bound/incomplete phases are censored, "
                 "including adapter-cut-short endings. Sampling is about 0.25 s and can miss brief Ready states. "
                 "Charts require five measured games per timing estimate; smaller samples remain in the table.",
                 {"kind": "instrument-rows", "label": "% of phase length", "data": points})


def health_panel(games, results, logs, labels, total):
    groups, covered = defaultdict(list), set()
    for game_id, game in games.items():
        facts = results.get(game_id, {}).get("instrumentation", {})
        if facts.get("health") is None:
            continue
        covered.add(game_id)
        activity = complete_activity(facts, logs.get(game_id, {}))
        for seat in game["seats"]:
            if not seat["policy_id"]:
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
                     sum(s["reconnects"] for s in seats), f"{sum(late)}/{len(late)} timed seats",
                     sum(s["no_connect"] for s in seats), f"{no_saved}/{len(due)} covered games with orders due",
                     fmt(median(api)), len(api), "unknown"])
        if len(due) >= MIN_SHARED_GAMES:
            points.append({"label": labels.get(policy, "Unlisted policy"), "value": no_saved/len(due)*100,
                           "value_label": percent(no_saved/len(due))})
    return panel(f"{len(groups)} policy versions have connection observations." if groups else
                 "No instrumented seat health is covered yet.",
                 ["Policy version", "Games", "Disconnects", "Reconnects", "Late first connect", "Never connected seats",
                  "Games with an unsaved due phase", "Median API requests/game", "API-covered games", "Pod loss"], rows,
                 coverage(len(covered), total) + "Late means first connection after the first observed order phase; "
                 "never connected is separate. Reconnect includes takeover without prior disconnect. "
                 "No-Saved counts games with at least one uncensored due seat-phase never Saved; absent log coverage "
                 "is unknown. API counts sum owned seats within each game and include the bot, browser tunnel and "
                 "archive worker; cancelled counts stay unknown. They are context, not an alert. Pod loss remains "
                 "unknown; verified platform failure-streak alerts are unchanged. Charts require five covered games.",
                 {"kind": "instrument-rows", "label": "% of games with unsaved due phases", "data": points})


def stages_panel(games, results, logs, total):
    stages = [("Queue", None), ("Pod start", None), ("Storage", "storage"), ("Game creation", "game_creation"),
              ("Services", "services"), ("Connect wait", "player_connect_wait"), ("Play", "play"),
              ("Replay write", "replay_write"), ("Results write", "results_write"),
              ("Acknowledgement wait", "acknowledgement_wait"), ("Shutdown", "shutdown")]
    covered = []
    for game_id, game in games.items():
        spans = []
        for a, b in (("created_at", "dispatched_at"), ("dispatched_at", "running_at")):
            lo, hi = game.get(a), game.get(b)
            spans.append(hi-lo if lo is not None and hi is not None and hi >= lo else None)
        timing = logs.get(game_id, {}).get("timing") or {}
        values = spans + [timing.get(key+"_seconds") for _, key in stages[2:]]
        if all(v is not None for v in values) and "interrupted_seconds" not in timing:
            covered.append(values)
    points = [{"label": name, "value": median([r[i] for r in covered]),
               "value_label": f"{fmt(median([r[i] for r in covered]))} s"}
              for i, (name, _) in enumerate(stages)] if covered else []
    largest = max(points, key=lambda p: p["value"]) if points else None
    return panel(f"{largest['label']} has the largest stage median: {fmt(largest['value'])} seconds." if largest else
                 "No complete instrumented lifecycle profiles are covered yet.",
                 ["Stage", "Median seconds", "Games"], [[p["label"], fmt(p["value"]), len(covered)] for p in points],
                 coverage(len(covered), total) + "Common complete-game cohort; "
                 "interrupted/incomplete profiles excluded. "
                 "Queue and pod start use API timestamps; other stages use the final game-log profile. "
                 "Separate medians are not additive and are not a representative game's timeline. "
                 "API and container boundaries differ; pod start may overlap early container initialization.",
                 {"kind": "amounts", "label": "Median seconds", "data": points, "order": [p["label"] for p in points]})


def phases_panel(games, results, total):
    groups, covered = defaultdict(list), set()
    for game_id in games:
        for phase in results.get(game_id, {}).get("instrumentation", {}).get("phases", []):
            if phase["seconds"] is not None:
                groups[phase["phase"]].append(phase)
                covered.add(game_id)
    rows, points = [], []
    for name, phases in sorted(groups.items()):
        label = "Movement" if name == "Diplomacy" else name
        early = [p["early"] for p in phases if p["early"] is not None]
        calls = [p["adjudication"] for p in phases if p["adjudication"] is not None]
        observed = median([p["seconds"] for p in phases])
        adjudication = median(calls)
        rows.append([label, len(phases), fmt(observed), fmt(adjudication), len(calls),
                     f"{sum(early)}/{len(early)} ({percent(sum(early)/len(early))})" if early else "unknown"])
        for metric, value in (("Observed", observed), ("Adjudication", adjudication)):
            if value is not None:
                points.append({"label": f"{label} · {metric}", "value": value, "value_label": f"{fmt(value)} s"})
    return panel(f"{sum(len(v) for v in groups.values())} complete observed phases with instrumentation." if groups else
                 "No instrumented phase timings are covered yet.",
                 ["Phase", "Phases", "Median observed seconds", "Median adjudication seconds", "Adjudication phases",
                  "Early finish / known deadlines"], rows, coverage(len(covered), total) +
                 "First phase observations collapse processing-state duplicates; latest observed deadlines include "
                 "extensions. Early means the next order phase began before that deadline. Final Finished-bound and "
                 "incomplete phases are excluded from early rates. Adjudication is the longest gamemaster request "
                 "started in that phase, overlapping observed duration; absent calls remain unknown.",
                 {"kind": "amounts", "label": "Median seconds", "data": points})


def instrumentation_panels(games, results, logs, labels):
    selected = {k: g for k, g in games.items() if supported(g.get("version"))}
    total = len(games)
    return {"Time to Ready": ready_panel(selected, results, logs, labels, total),
            "Seat health": health_panel(selected, results, logs, labels, total),
            "Where an episode's time goes": stages_panel(selected, results, logs, total),
            "Phase timing": phases_panel(selected, results, total)}
