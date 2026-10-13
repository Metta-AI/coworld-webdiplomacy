"""Current membership and cumulative rating observations, with explicit history gaps."""
from collections import Counter, defaultdict
from statistics import mean

from .config import FILLER_SHARE_ALERT, RATING_BASELINE_TOLERANCE
from .dates import when
from .game_metrics import PAR, day, fmt, minutes, panel, player_scores, quantile


def rating_history(history):
    points, previous, segments = [], {}, defaultdict(int)
    for observation in history:
        for row in observation["data"]["rows"]:
            key = (row["division_id"], row["player_id"])
            old = previous.get(key)
            reset = old and row["rounds_played"] is not None and old["rounds"] is not None and (
                row["rounds_played"] < old["rounds"])
            gap = old and (observation["data"].get("poll_gap", False) or
                           row["rounds_played"] is not None and old["rounds"] is not None and
                           row["rounds_played"] - old["rounds"] > 1)
            # Polling gaps and observed rank resets break lines. No interpolated rounds.
            if reset or gap:
                segments[key] += 1
            mu, sigma = row["mu"], row["sigma"]
            point = {"player_id": row["player_id"], "division_id": row["division_id"], "player": row["player"],
                     "time": observation["observed_at"], "value": row["rating"], "mu": mu,
                     "low": mu - 3 * sigma if mu is not None and sigma is not None else None,
                     "high": mu + 3 * sigma if mu is not None and sigma is not None else None,
                     "rounds": row["rounds_played"], "segment": segments[key],
                     "series": f"{row['division_id']}:{row['player_id']}:{segments[key]}",
                     "reset": bool(reset), "gap": bool(gap), "last_round_id": row["last_round_id"]}
            points.append(point)
            previous[key] = point
    return points


def rating_delta(points, division, player, now):
    own = [r for r in points if r["player_id"] == player and r["division_id"] == division]
    if not own:
        return None, None
    current = own[-1]
    candidates = [r for r in own if r["segment"] == current["segment"] and r["value"] is not None and
                  abs(r["time"] - (now - 86400)) <= RATING_BASELINE_TOLERANCE]
    if not candidates or current["value"] is None:
        return None, None
    baseline = min(candidates, key=lambda r: abs(r["time"] - (now - 86400)))
    return current["value"] - baseline["value"], baseline["time"]


def standings(members, ratings, points, submissions, games, now, submission_complete):
    competing = defaultdict(list)
    for row in members:
        if row["status"] == "competing":
            competing[row["division_id"], row["player_id"]].append(row)
    rated = {(r["division_id"], r["player_id"]): r for r in ratings}
    scores = defaultdict(list)
    for row in player_scores(games):
        scores[row["player_id"]].append(row["score"])
    rows, intervals, sparks, changes, player_ids = [], [], [], [], []
    for key, policies in sorted(competing.items(), key=lambda item: (
            -(rated.get(item[0], {}).get("rating") if rated.get(item[0], {}).get("rating") is not None
              else float('-inf')), item[0])):
        division, player_id = key
        player_ids.append(player_id)
        rating = rated.get(key, {})
        name = policies[0]["player"]
        mu, sigma = rating.get("mu"), rating.get("sigma")
        low, high = (mu - 3 * sigma, mu + 3 * sigma) if mu is not None and sigma is not None else (None, None)
        delta, baseline = rating_delta(points, division, player_id, now)
        values = scores[player_id]
        submissions_24h, submissions_7d = [sum(s["player_id"] == player_id and s["created_at"] is not None and
                                             now - age <= s["created_at"] <= now for s in submissions)
                                           for age in (86400, 7 * 86400)]
        rows.append([name, "; ".join(f"{m['policy']} v{m['version']} ({m['substatus']})" for m in policies),
                     fmt(rating.get("rating")), f"{fmt(mu)} ± {fmt(3 * sigma if sigma is not None else None)}",
                     f"{delta:+.2f} since {when(baseline)}" if delta is not None else "baseline unavailable",
                     len(values), fmt(mean(values)) if values else "unknown",
                     f"{submissions_24h} / {submissions_7d}" + (" observed" if not submission_complete else " listed"),
                     "not observed", "unknown"])
        if low is not None:
            intervals.append({"player": name, "low": low, "high": high, "mu": mu, "value": rating.get("rating")})
        sparks.extend([r for r in points if (r["division_id"], r["player_id"]) == key][-20:])
        if delta is not None:
            changes.append((abs(delta), name, delta, baseline))
    sentence = (f"{len(competing)} player/division entries have competing policies; "
                f"{len(competing.keys() & rated.keys())} rated.")
    if changes:
        _, name, delta, baseline = max(changes)
        sentence = f"{name} has the largest observed 24-hour rating change: {delta:+.2f}, from {when(baseline)}."
    result = panel(sentence, ["Player", "Competing policies", "MMR", "μ ± 3σ", "24 h change", "Scored games (7d)",
                             f"Mean score (par {PAR:.3f})", "Submissions 24h / 7d", "Model", "LLM/game"], rows,
                   "Current memberships; all versions. Scores average owned non-filler seats once per game. "
                   "MMR is cumulative across versions. Model labels lack a verified player identity join.",
                   {"kind": "intervals", "data": intervals})
    result["sparks"] = sparks
    result["player_ids"] = player_ids
    return result


def histories(points):
    times = sorted({r["time"] for r in points})
    sentence = f"{len(times)} observed updates since {when(times[0])}." if times else (
        "Rating history starts with the first successful poll.")
    gaps, resets = sum(r["gap"] for r in points), sum(r["reset"] for r in points)
    note = (f"{gaps} player-series gaps; {resets} observed resets. Lines stop across gaps/resets. "
            "Cumulative mixed-input ratings, never version-isolated MMR; canonical observations are not release times.")
    rows = [[r["player"], when(r["time"]), fmt(r["value"]), fmt(r["mu"]), fmt(r["low"]), fmt(r["high"]),
             "reset" if r["reset"] else "gap" if r["gap"] else "observed"] for r in points]
    columns = ["Player", "Observed (Pacific)", "MMR", "μ", "μ − 3σ", "μ + 3σ", "Continuity"]
    by_player = defaultdict(list)
    for row in points:
        by_player[row["division_id"], row["player_id"]].append(row)
    changes = []
    for group in by_player.values():
        if len(group) >= 2 and group[-1]["segment"] == group[-2]["segment"] and all(
                r["low"] is not None for r in group[-2:]):
            a, b = group[-2:]
            changes.append((b["high"] - b["low"] - (a["high"] - a["low"]), b["player"]))
    widening = [c for c in changes if c[0] > 0]
    narrowing = [c for c in changes if c[0] < 0]
    interval_sentence = (f"{max(widening)[1]}'s observed rating interval widened." if widening else
                         f"{min(narrowing)[1]}'s observed rating interval narrowed most." if narrowing else
                         "Not enough changed intervals to describe a trend.")
    return {"MMR over time": panel(sentence, columns, rows, note, {"kind": "ratings", "data": points}),
            "Rating interval over time": panel(interval_sentence, columns, rows, note,
                                               {"kind": "bands", "data": points})}


def submission_series(rows, now, complete):
    current = [r for r in rows if r["created_at"] is not None and now - 7 * 86400 <= r["created_at"] <= now]
    prior = [r for r in rows if r["created_at"] is not None and now - 14 * 86400 <= r["created_at"] < now - 7 * 86400]
    counts = Counter((day(r["created_at"]), r["player"]) for r in current)
    points = [{"day": d, "series": player, "value": n} for (d, player), n in sorted(counts.items())]
    sentence = (f"{len(current)} listed submissions in seven days; {len(prior)} in the prior seven days."
                if complete else
                f"Submission history incomplete: {len(current)} observed in seven days.")
    return panel(sentence, ["Pacific creation day", "Player", "Submissions"],
                 [[r["day"], r["series"], r["value"]] for r in points],
                 "All versions. Complete means the current API listing was exhausted; "
                 "older deleted history is unknown. "
                 "Today and the first day are partial rolling-window buckets.",
                 {"kind": "bars", "data": points, "label": "Submissions"})


def exposure(members, games, rounds, episode_sources, submissions, now, target):
    active = sum(m["status"] == "competing" and m["substatus"] == "active" for m in members)
    benched = sum(m["status"] == "competing" and m["substatus"] == "benched" for m in members)
    disqualified = sum(m["status"] == "disqualified" for m in members)
    seats = [s for g in games for s in g["seats"]]
    fillers = sum(s["filler"] for s in seats)
    sentence = (f"{fillers} of {len(seats)} observed seats are fillers." if seats and
                fillers / len(seats) > FILLER_SHARE_ALERT else
                f"{active} active, {benched} benched, {disqualified} disqualified policies.")
    rows = [["Active competing policies", active], ["Benched competing policies", benched],
            ["Disqualified policies", disqualified], ["Filler seats / all observed seats", f"{fillers} / {len(seats)}"],
            ["Current games-per-entrant target", target if target is not None else "unknown"]]
    waits, waiting = [], 0
    for sub in submissions:
        starts = [g["created_at"] for g in games if g["created_at"] is not None and sub["created_at"] is not None and
                  g["created_at"] >= sub["created_at"] and any(s["policy_id"] == sub["policy_id"] and
                  not s["filler"] for s in g["seats"])]
        if starts:
            waits.append(minutes(sub["created_at"], min(starts)))
        else:
            waiting += 1
    rows += [["Median wait to first observed game, min", fmt(quantile(waits, .5))],
             ["Seven-day submissions without an observed game", waiting]]
    exposures = []
    for rd in rounds:
        source = episode_sources.get(rd["id"])
        if rd["status"] != "completed" or rd["entrants"] is None or not source or source.get("data") is None:
            continue
        for player in rd["entrants"]:
            count = sum(any(s["player_id"] == player and not s["filler"] for s in game["seats"])
                        for game in source["data"]["rows"])
            exposures.append({"round": rd["number"], "player_id": player, "games": count})
    names = {s["player_id"]: s["player"] for g in games for s in g["seats"] if s["player_id"]}
    names.update({m["player_id"]: m["player"] for m in members})
    rows += [[f"Round {r['round']} · {names.get(r['player_id'], 'Unnamed entrant')} games", r["games"]]
             for r in exposures]
    rows += [["Eligible player/round rows with complete episode listing", len(exposures)],
             ["Eligible player/round rows with zero games", sum(r["games"] == 0 for r in exposures)]]
    result = panel(sentence, ["Measure", "Observed value"], rows,
                   "Current memberships, all versions; seats and submitted policies in seven days. "
                   "First observed game is not "
                   "necessarily the historical first game. No-game submissions may be waiting or outside retained "
                   "history. Eligibility uses the round's entrant roster; current target is not a historical limit.")
    result["exposures"] = exposures
    return result
