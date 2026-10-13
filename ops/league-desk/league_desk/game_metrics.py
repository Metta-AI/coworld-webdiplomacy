"""Game-grain metrics. Missing timestamps/scores never become zero."""
from collections import Counter, defaultdict
from datetime import datetime
from itertools import combinations
from statistics import mean
from zoneinfo import ZoneInfo

from .config import MIN_SHARED_GAMES, QUEUE_MINUTES_ALERT
from .dates import when

PAR = 1 / 7


def day(value):
    return datetime.fromtimestamp(value, ZoneInfo("America/Los_Angeles")).date().isoformat()


def quantile(values, fraction):
    """Linear interpolation on sorted observations, including singleton samples."""
    if not values:
        return None
    values = sorted(values)
    index = (len(values) - 1) * fraction
    lo = int(index)
    return values[lo] + (values[min(lo + 1, len(values) - 1)] - values[lo]) * (index - lo)


def minutes(start, end):
    return (end - start) / 60 if start is not None and end is not None and end >= start else None


def fmt(value):
    return f"{value:.2f}" if value is not None else "unknown"


def panel(sentence, columns=(), rows=(), note="", chart=None):
    return {"sentence": sentence, "columns": columns, "rows": rows, "note": note, "chart": chart}


def player_scores(games):
    """One player score per completed game; every owned non-filler seat must have a score."""
    result = []
    for game in games:
        if game["status"] != "completed":
            continue
        players = defaultdict(list)
        for seat in game["seats"]:
            if seat["player_id"] and not seat["filler"]:
                players[seat["player_id"]].append(seat)
        for player_id, seats in players.items():
            if all(s["score"] is not None for s in seats):
                result.append({"game_id": game["id"], "player_id": player_id,
                               "player": seats[0]["player"] or "Unnamed player",
                               "score": mean(s["score"] for s in seats)})
    return result


def head_to_head(games):
    by_game, names, counts = defaultdict(dict), {}, defaultdict(lambda: [0, 0, 0])
    for row in player_scores(games):
        by_game[row["game_id"]][row["player_id"]] = row["score"]
        names[row["player_id"]] = row["player"]
    for scores in by_game.values():
        for a, b in combinations(sorted(scores), 2):
            count = counts[a, b]
            count[0] += 1
            count[1] += scores[a] > scores[b]
            count[2] += scores[a] == scores[b]
    cells = []
    for a in sorted(names):
        for b in sorted(names):
            n, wins, ties = counts.get(tuple(sorted((a, b))), (0, 0, 0))
            if a > b:
                wins = n - wins - ties
            cells.append({"a": a, "b": b, "player": names[a], "opponent": names[b], "n": n, "ties": ties,
                          "share": wins / n if a != b and n >= MIN_SHARED_GAMES else None})
    supported = sum(n >= MIN_SHARED_GAMES for n, _, _ in counts.values())
    sentence = f"{supported} pairs have at least {MIN_SHARED_GAMES} shared games." if supported else (
        "No sufficiently sampled pairs.")
    comparisons = [(wins / n, a, b, n, wins, ties) for (a, b), (n, wins, ties) in counts.items()
                   if n >= MIN_SHARED_GAMES]
    comparisons += [(1 - share - ties / n, b, a, n, n - wins - ties, ties)
                    for share, a, b, n, wins, ties in list(comparisons)]
    if comparisons:
        _, a, b, n, wins, ties = max(comparisons)
        sentence = f"{names[a]} finished ahead of {names[b]} in {wins}/{n} shared games ({ties} ties)."
    rows = [[names[a], names[b], n, ties, fmt(wins / n) if n >= MIN_SHARED_GAMES else "fewer than five"]
            for (a, b), (n, wins, ties) in sorted(counts.items())]
    result = panel(sentence, ["Player", "Opponent", "Shared games", "Ties", "Ahead / shared"], rows,
                   "Completed, scored, non-filler seats; multiple seats averaged per player/game. "
                   "Ties stay in the denominator. Dashed cells have fewer than five distinct games.",
                   {"kind": "matrix", "data": cells})
    result["cells"] = cells
    return result


def round_durations(rounds, settings_history, now):
    rows, points, durations = [], [], []
    running = skipped = exceeded = 0
    for row in sorted(rounds, key=lambda r: r["created_at"] or 0):
        created, end = row["created_at"], row["completed_at"]
        settings = [s for s in settings_history if created is not None and s["observed_at"] <= created]
        interval = settings[-1]["data"]["round_interval_minutes"] if settings else None
        duration = minutes(created, end)
        if row["skip_kind"] or row["status"] == "skipped":
            skipped += 1
        elif row["status"] == "completed" and duration is not None:
            durations.append(duration)
            exceeded += interval is not None and duration > interval
            points.append({"time": end, "value": duration, "series": "Completed", "reference": interval})
        elif end is None:
            running += 1
        rows.append([row["number"], row["status"], fmt(duration) if end is not None else
                     f"≥ {fmt(minutes(created, now))} (unfinished)", fmt(interval)])
    sentence = (f"{exceeded} completed rounds exceeded their observed interval." if exceeded else
                f"Median {fmt(quantile(durations, .5))} minutes over {len(durations)} completed rounds."
                if durations else "No completed rounds with valid timestamps.")
    return panel(sentence, ["Round", "Status", "Created → completed, min", "Observed interval, min"], rows,
                 f"{running} unfinished, {skipped} skipped; skips excluded. "
                 "Intervals before first observation unknown.",
                 {"kind": "dots", "data": points, "label": "Minutes"})


def game_durations(games):
    groups, all_values = defaultdict(list), []
    for game in games:
        value = minutes(game["running_at"], game["completed_at"])
        if game["status"] == "completed" and value is not None:
            groups[day(game["completed_at"]), game["version"]].append(value)
            all_values.append(value)
    points = [{"day": d, "series": version, "n": len(values), "value": quantile(values, .5),
               "p90": quantile(values, .9)} for (d, version), values in sorted(groups.items())]
    return panel(f"Median {fmt(quantile(all_values, .5))}, p90 {fmt(quantile(all_values, .9))} minutes "
                 f"across {len(all_values)} games." if all_values else "No completed games with play timestamps.",
                 ["Completion day (Pacific)", "Version", "Games", "Median min", "p90 min"],
                 [[r["day"], r["series"], r["n"], fmt(r["value"]), fmt(r["p90"])] for r in points],
                 "Running → completed. Percentiles use linear interpolation; versions show association, not causation.",
                 {"kind": "daily-dots", "data": points, "label": "Minutes"})


def throughput(games):
    counts = Counter((day(g["completed_at"]), g["status"]) for g in games if g["completed_at"] is not None)
    points = [{"day": d, "series": status, "value": n} for (d, status), n in sorted(counts.items())]
    completed = sum(n for (_, status), n in counts.items() if status == "completed")
    failed = sum(n for (_, status), n in counts.items() if status == "failed")
    return panel(f"{failed} failed games; {completed} completed." if failed else
                 f"{completed} games completed; end reasons await results ingest.",
                 ["Completion day (Pacific)", "Status", "Games"],
                 [[r["day"], r["series"], r["value"]] for r in points],
                 "Observed terminal events only. Missing days are gaps; today's bucket is partial.",
                 {"kind": "bars", "data": points, "label": "Games"})


def episode_timing(games):
    rows = []
    for game in games:
        spans = [minutes(game[a], game[b]) for a, b in (("created_at", "dispatched_at"),
                 ("dispatched_at", "running_at"), ("running_at", "completed_at"))]
        if game["status"] == "completed" and all(v is not None for v in spans):
            rows.append((game["id"], game["completed_at"], spans))
    if not rows:
        return panel("No completed games have all four lifecycle timestamps.",
                     note="Detailed boot/connect/adjudication/upload timing needs instrumentation.")
    median = quantile([sum(r[2]) for r in rows], .5)
    representative = min(rows, key=lambda r: (abs(sum(r[2]) - median), r[0]))
    parts = [{"part": name, "value": value} for name, value in zip(
        ("Queue", "Startup", "Play and finish"), representative[2], strict=True)]
    largest = max(parts, key=lambda r: r["value"])
    queue = quantile([r[2][0] for r in rows], .5)
    sentence = (f"Median queue time is {fmt(queue)} minutes across {len(rows)} fully timed games."
                if queue > QUEUE_MINUTES_ALERT else
                f"{largest['part']} took {fmt(largest['value'])} of this representative game's "
                f"{fmt(sum(representative[2]))} minutes.")
    return panel(sentence, ["Span", "Minutes"], [[r["part"], fmt(r["value"])] for r in parts],
                 f"One game nearest median total ({fmt(median)} min), completed {when(representative[1])}; "
                 f"{len(rows)} games eligible. Queue median {fmt(queue)} min. Spans do not overlap; "
                 "fine-grained game timing remains unavailable.", {"kind": "timing", "data": parts})
