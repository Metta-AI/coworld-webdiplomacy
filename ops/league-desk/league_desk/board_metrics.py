"""Public artifact facts already parsed by the collector; no artifact I/O here."""
from collections import Counter, defaultdict

from .board_map import board_map_panel, map_entries, map_report
from .config import MIN_SHARED_GAMES
from .dates import when
from .game_metrics import PAR, day, fmt, panel
from .instrument_metrics import instrumentation_panels
from .instrumentation import supported
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


def policy_panel(seats, labels, current):
    groups = defaultdict(list)
    for seat in seats:
        if seat["policy_id"] in current:
            groups[seat["policy_id"], seat["power"]].append(seat)
    points = []
    for policy_id in sorted({key[0] for key in groups}):
        for power in POWERS.values():
            rows = groups[policy_id, power]
            value = stat([(s["game"], s["score"] - PAR) for s in rows])
            points.append({"policy_id": policy_id, "policy": labels.get(policy_id, "Unlisted policy"),
                           "power": power, **value})
    count = sum(r["games"] >= MIN_SHARED_GAMES for r in points)
    return panel(f"{count} policy/power cells have at least five distinct games." if points else
                 "No scored games for the currently competing policies in this selection.",
                 ["Policy version", "Power", "Games", "Mean score − par", "95% interval"],
                 [[r["policy"], r["power"], r["games"], fmt(r["mean"]),
                   " – ".join(fmt(v) for v in r["ci"]) if r["ci"] else "unavailable"] for r in points],
                 "One row per player: the policy version currently competing for them. "
                 "Stable policy-version IDs join API seats; seats they filled in other players' games count too. "
                 "Mean deviation from 1/7. "
                 "Dashed cells have fewer than five games. Intervals account for game clustering.",
                 {"kind": "policy-power", "data": points, "minimum": MIN_SHARED_GAMES})


def terminal_games(episode_sources, now, start, version):
    """Selected league games that ended in the range, by completion time and Coworld version."""
    return {g["id"]: g for s in episode_sources.values() for g in s["data"]["rows"]
            if g["completed_at"] is not None and start <= g["completed_at"] <= now
            and (version == "all" or g["coworld_id"] == version)
            and g["status"] in ("completed", "failed", "cancelled", "error", "canceled", "timed_out")}


def board_panels(snapshot, league, competition, now, start, version):
    games = terminal_games(competition["episode_sources"], now, start, version)
    results, replays, logs, dependencies, absent = {}, {}, {}, [], set()
    for kind, target in (("results", results), ("replay", replays), ("logs", logs)):
        for game_id in games:
            if kind == "logs" and not supported(games[game_id].get("version")):
                continue
            source = snapshot.get(("artifact_" + kind, game_id), {})
            if (source.get("data") or {}).get("state") == "absent":
                # A game that ended without completing and never uploaded this artifact.
                absent.add(game_id)
                continue
            dependencies.append({**source, "name": kind, "scope": game_id})
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
    # The champion is each player's one current entry; benched older versions also read "competing".
    current = {m["policy_id"] for m in members if m["status"] == "competing" and m.get("champion")}
    entries, pending = map_entries(snapshot, games)
    panels = {"The board": board_map_panel(map_report(entries), pending),
              "Score by policy and power": policy_panel(seats, labels, current)}
    panels.update(instrumentation_panels(games, results, logs, labels, current))
    eligible = sum(supported(g.get("version")) for g in games.values())
    coverage = (f"Results {len(results)}/{len(games)}; replay {len(replays)}/{len(games)}; "
                f"game log {len(logs)}/{eligible} eligible 0.7.12+ games. "
                + (f"{len(absent)} games that did not complete have no artifacts to fetch. " if absent else "")
                + "Terminal selected league games.")
    for title, value in panels.items():
        kinds = ("results", "replay") if title == "The board" else ("results",)
        required = [d for d in dependencies if d["name"] in kinds]
        if title in ("Time to Ready", "Seat health"):
            kinds = ("results", "logs")
            required = [d for d in dependencies if d["name"] in kinds and
                        supported(games[d["scope"]].get("version"))]
        newest = max((d.get("fetched_at") or 0 for d in required), default=0)
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
    throughput["sources"] += panels["Score by policy and power"]["sources"]
    throughput["stale"] |= panels["Score by policy and power"]["stale"]
    return panels
