"""Public artifact facts already parsed by the collector; no artifact I/O here."""
from collections import Counter, defaultdict

from .config import MIN_SHARED_GAMES
from .dates import when
from .game_metrics import PAR, day, fmt, panel, quantile
from .optimizer_tools import POWERS, stat


def score_facts(game, facts):
    """Quarantine conflicts with known API scores; missing API scores are not zeros."""
    if facts.get("score_issue") or facts.get("taints") or game["status"] != "completed":
        return []
    api = {s["slot"]: s for s in game["seats"]}
    if any(s["slot"] not in api or api[s["slot"]]["score"] is not None and
           abs(api[s["slot"]]["score"] - s["score"]) > 1e-6 for s in facts["seats"]):
        return []
    return [{**s, "game": game["id"], "policy_id": api[s["slot"]]["policy_id"]} for s in facts["seats"]]


def powers_panel(seats):
    points = []
    for power in POWERS.values():
        rows = [s for s in seats if s["power"] == power]
        value = stat([(s["game"], s["score"]) for s in rows])
        points.append({"power": power, **value, "low": value["ci"][0] if value["ci"] else None,
                       "high": value["ci"][1] if value["ci"] else None})
    eligible = [r for r in points if r["games"] >= MIN_SHARED_GAMES]
    sentence = (f"{len(eligible)} powers have at least five distinct scored games." if seats else
                "No complete, untainted scored results are available.")
    above = [r for r in eligible if r["low"] is not None and r["low"] > PAR]
    below = [r for r in eligible if r["high"] is not None and r["high"] < PAR]
    if above:
        sentence = f"{max(above, key=lambda r: r['mean'])['power']}'s observed interval is above equal-share par."
    elif below:
        sentence = f"{min(below, key=lambda r: r['mean'])['power']}'s observed interval is below equal-share par."
    return panel(sentence, ["Power", "Games", "Mean score", "95% interval", "Survival", "Solos"],
                 [[r["power"], r["games"], fmt(r["mean"]),
                   f"{fmt(r['low'])} – {fmt(r['high'])}" if r["ci"] else "unavailable",
                   f"{sum(s['survived'] is True for s in seats if s['power'] == r['power'])}/"
                   f"{sum(s['survived'] is not None for s in seats if s['power'] == r['power'])} known",
                   sum(s["solo"] for s in seats if s["power"] == r["power"])] for r in points],
                 "All seats, including fillers. Game-clustered 95% intervals; par is 1/7. "
                 "Fewer than five games have no colored mark; zero-variance intervals stay unavailable. "
                 "Survival uses results member centers, never the stale final replay board.",
                 {"kind": "power-scores", "data": points, "reference": PAR, "minimum": MIN_SHARED_GAMES})


def policy_panel(seats, labels):
    groups = defaultdict(list)
    for seat in seats:
        if seat["policy_id"]:
            groups[seat["policy_id"], seat["power"]].append(seat)
    points = []
    for policy_id in sorted({key[0] for key in groups}):
        for power in POWERS.values():
            rows = groups[policy_id, power]
            value = stat([(s["game"], s["score"] - PAR) for s in rows])
            points.append({"policy_id": policy_id, "policy": labels.get(policy_id, "Unlisted policy"),
                           "power": power, **value})
    count = sum(r["games"] >= MIN_SHARED_GAMES for r in points)
    return panel(f"{count} policy/power cells have at least five distinct games.",
                 ["Policy version", "Power", "Games", "Mean score − par", "95% interval"],
                 [[r["policy"], r["power"], r["games"], fmt(r["mean"]),
                   " – ".join(fmt(v) for v in r["ci"]) if r["ci"] else "unavailable"] for r in points],
                 "Stable policy-version IDs join API seats; labels come from memberships or recorded API participants. "
                 "Mean deviation from 1/7; includes filler seats with policy identity. "
                 "Dashed cells have fewer than five games. Intervals account for game clustering.",
                 {"kind": "policy-power", "data": points, "minimum": MIN_SHARED_GAMES})


def contests_panel(replays):
    usable = [r for r in replays if r["board_comparisons"] > 0]
    totals = defaultdict(Counter)
    for facts in usable:
        for name, counts in facts["provinces"].items():
            totals[name].update(counts)
    points = [{"label": name, "value": (counts["failed_moves"] + counts["owner_changes"]) / len(usable),
               **counts} for name, counts in totals.items()]
    points.sort(key=lambda r: (-r["value"], r["label"]))
    sentence = (f"{points[0]['label']}: {fmt(points[0]['value'])} observed contests/game; "
                f"{points[-1]['label']}: {fmt(points[-1]['value'])}." if points else "No comparable replay boards.")
    shown = points[:6] + [r for r in points[-3:] if r not in points[:6]]
    return panel(sentence, ["Province", "Failed incoming moves", "Known owner changes", "Games", "Contests/game"],
                 [[r["label"], r["failed_moves"], r["owner_changes"], len(usable), fmt(r["value"])] for r in points],
                 "Failed Move orders plus known owner changes; coast children folded into provinces. "
                 "First boards are baselines; missing ownership and the stale Finished board add no changes. "
                 "Final-autumn ownership may be unavailable. "
                 "Chart shows six highest and three lowest; table includes zeros.",
                 {"kind": "amounts", "label": "Observed contests / usable game", "data": shown,
                  "order": [r["label"] for r in shown]})


def timing_panel(results, replays):
    groups = defaultdict(list)
    for game_id, facts in results.items():
        limits = replays.get(game_id, {}).get("limits", {})
        for phase in facts["phases"]:
            limit = limits.get(f"{phase['turn']}:{phase['phase']}")
            groups[phase["phase"], limit].append((game_id, phase["seconds"]))
    rows, points = [], []
    for (phase, limit), values in sorted(groups.items(), key=lambda pair: (pair[0][0], pair[0][1] or -1)):
        label = "Movement" if phase == "Diplomacy" else phase
        median = quantile([v for _, v in values], .5)
        above = sum(v > limit for _, v in values) if limit is not None else None
        rows.append([label, fmt(limit), len(values), len({g for g, _ in values}), fmt(median),
                     above if above is not None else "unknown", "not recorded"])
        reference = f"{fmt(limit)} s limit" if limit is not None else "limit unknown"
        points.append({"label": f"{label} · {reference}", "value": median})
    sentence = (f"{sum(len(v) for v in groups.values())} complete observed phases in "
                f"{len({g for v in groups.values() for g, _ in v})} games." if groups else
                "No complete timestamped phase transitions.")
    exceeded = sum(r[5] for r in rows if isinstance(r[5], int))
    if exceeded:
        sentence = f"{exceeded} complete observed phases exceeded their observed config reference."
    elif points:
        longest = max(points, key=lambda p: p["value"])
        sentence += f" Largest median: {longest['label']}, {fmt(longest['value'])} seconds."
    return panel(sentence, ["Phase", "Observed config seconds", "Phases", "Games", "Median seconds",
                            "Above config", "Deadline-based early rate"], rows,
                 "Results transition clocks, grouped by turn/phase; processing-state duplicates collapse. "
                 "Final incomplete phases excluded. Pauses remain in elapsed duration. Replay config is an observed "
                 "reference; duration below config does not prove early finish. Deadlines and per-phase adjudication "
                 "durations are not established by these public snapshots.",
                 {"kind": "amounts", "label": "Median observed seconds", "data": points})


def board_panels(snapshot, league, competition, now, start, version):
    games = {g["id"]: g for s in competition["episode_sources"].values() for g in s["data"]["rows"]
             if g["completed_at"] is not None and start <= g["completed_at"] <= now
             and (version == "all" or g["coworld_id"] == version)
             and g["status"] in ("completed", "failed", "cancelled", "error", "canceled", "timed_out")}
    results, replays, dependencies = {}, {}, []
    for kind, target in (("results", results), ("replay", replays)):
        for game_id in games:
            source = snapshot.get(("artifact_" + kind, game_id), {})
            dependencies.append({**source, "name": kind})
            if source.get("data"):
                target[game_id] = source["data"]["facts"]
    seats, excluded = [], 0
    for game_id, facts in results.items():
        accepted = score_facts(games[game_id], facts)
        seats.extend(accepted)
        excluded += not bool(accepted)
    scope = league["id"] if league else ""
    members = (snapshot.get(("memberships", scope), {}).get("data") or {}).get("rows", [])
    labels = {s["policy_id"]: s["policy_label"] for g in games.values() for s in g["seats"]
              if s.get("policy_label")}
    labels.update({m["policy_id"]: f"{m['player']} · {m['policy']} v{m['version']}" for m in members})
    comparable = [replays[key] for key in replays if key in results and score_facts(games[key], results[key])]
    panels = {"Score by power, all players": powers_panel(seats),
              "Score by policy and power": policy_panel(seats, labels),
              "Contested provinces": contests_panel(comparable), "Phase timing": timing_panel(results, replays)}
    coverage = (f"Results {len(results)}/{len(games)}; replay {len(replays)}/{len(games)} "
                "finished selected league games.")
    newest = max((d.get("fetched_at") or 0 for d in dependencies), default=0)
    for title, value in panels.items():
        required = dependencies if title in ("Contested provinces", "Phase timing") else [
            d for d in dependencies if d["name"] == "results"]
        value.update(immutable=True, age=None, missing=sum(not d.get("data") for d in required),
                     stale=any(bool(d.get("error")) for d in required),
                     artifact_status=coverage + (f" Last ingest {when(newest)}." if newest else " Awaiting ingest."),
                     coverage=coverage + f" {excluded} results excluded from competitive summaries "
                     "(taint or score conflict). "
                     + competition["game_coverage"], sources=[{
                         "name": d["name"], "age": int(now - d["fetched_at"]) if d.get("fetched_at") else None,
                         "rows": int(bool(d.get("data"))), "error": d.get("error"), "stale": bool(d.get("error")),
                         "threshold": "Infinity"} for d in required])
    # Keep operational failures/cancellations in throughput, even when excluded from competitive scores.
    throughput = competition["panel_data"]["Games per day and how they ended"]
    counts = Counter((day(game["completed_at"]), results[key]["reason"] if key in results else
                      "End reason unavailable", game["status"], results.get(key, {}).get("outcome", "unknown"),
                      results.get(key, {}).get("draw_survivors")) for key, game in games.items())
    ordered = sorted(counts.items(), key=lambda r: str(r[0]))
    throughput["chart"]["data"] = [{"day": date, "series": f"{status} · {reason}", "value": n}
                                    for (date, reason, status, outcome, survivors), n in ordered]
    throughput["columns"] = ["Pacific completion day", "Status", "Outcome", "End reason", "Draw survivors", "Games"]
    throughput["rows"] = [[date, status, outcome, reason, survivors if survivors is not None else "—", n]
                          for (date, reason, status, outcome, survivors), n in ordered]
    throughput["sentence"] = f"{len(games)} terminal games; {len(results)} have public end reasons."
    throughput["note"] = "Terminal events, including failed/cancelled games. " + coverage
    throughput["coverage"] += " " + coverage
    throughput["sources"] += panels["Score by power, all players"]["sources"]
    throughput["stale"] |= panels["Score by power, all players"]["stale"]
    timing = competition["panel_data"].get("Where an episode's time goes")
    calls = [r["gamemaster"] for r in results.values() if r.get("gamemaster", {}).get("max_seconds") is not None]
    if timing and calls:
        timing["note"] += (f" Game-level gamemaster context: {len(calls)} results with timings; "
                           f"largest recorded call {fmt(max(r['max_seconds'] for r in calls))} seconds. "
                           "This overlaps play time; it is not a per-phase adjudication measurement.")
    return panels
