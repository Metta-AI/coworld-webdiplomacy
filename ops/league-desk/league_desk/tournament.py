"""Inputs for the tournament planner: scored league games with powers, players, cost and duration.

The statistics run in the browser (static/tournament-worker.js); this module only selects and
joins cached data. It never reads the platform.
"""
from collections import defaultdict
from statistics import mean
from urllib.parse import urlencode

from .board_metrics import score_facts
from .dates import when
from .game_metrics import minutes, quantile
from .optimizer_tools import POWERS

# Results facts name powers; the planner works with power indices 0..6 in this fixed order.
POWER_INDEX = {name: index for index, name in enumerate(POWERS.values())}
DEFAULT_PLAYERS = 7
IN_FLIGHT = 8


def league_games(snapshot, league_id, version):
    games = {}
    for (name, _), state in snapshot.items():
        data = state.get("data") or {}
        if name == "episodes" and data.get("league_id") == league_id:
            for game in data["rows"]:
                if version == "all" or game["coworld_id"] == version:
                    games[game["id"]] = game
    return games


def scored_games(snapshot, games):
    """Completed games with every seat scored, powers joined by slot from accepted results facts.

    Games whose results are tainted or conflict with API scores are excluded. Games without
    results facts keep their API scores with unknown powers (null).
    """
    rows, excluded, without_powers = [], 0, 0
    for game in sorted(games.values(), key=lambda g: (g["completed_at"] or 0, g["id"])):
        if game["status"] != "completed" or any(s["score"] is None for s in game["seats"]):
            continue
        facts = (snapshot.get(("artifact_results", game["id"]), {}).get("data") or {}).get("facts")
        powers = {}
        if facts:
            accepted = score_facts(game, facts)
            if not accepted:
                excluded += 1
                continue
            powers = {s["slot"]: POWER_INDEX.get(s["power"]) for s in accepted}
        else:
            without_powers += 1
        seats = sorted(game["seats"], key=lambda s: s["slot"])
        rows.append({"id": game["id"], "completed_at": game["completed_at"], "seats": [
            {"player_id": s["player_id"], "policy_id": s["policy_id"], "filler": s["filler"],
             "power": powers.get(s["slot"]), "score": s["score"]} for s in seats]})
    return rows, excluded, without_powers


def candidates(members, ratings, games):
    """Competing players with a champion policy, highest MMR first; the top seven start selected."""
    rated = defaultdict(list)
    for row in ratings:
        if row["rating"] is not None:
            rated[row["player_id"]].append(row["rating"])
    players = {}
    for row in members:
        entry = players.setdefault(row["player_id"], {"player_id": row["player_id"], "player": row["player"],
                                                      "champions": [], "policy_ids": []})
        entry["policy_ids"].append(row["policy_id"])
        if row["status"] == "competing" and row.get("champion"):
            entry["champions"].append({"policy_id": row["policy_id"], "label": f"{row['policy']} v{row['version']}"})
    # Seats also reveal older versions that no longer have a membership row.
    for game in games:
        for seat in game["seats"]:
            if seat["player_id"] in players and not seat["filler"]:
                if seat["policy_id"] not in players[seat["player_id"]]["policy_ids"]:
                    players[seat["player_id"]]["policy_ids"].append(seat["policy_id"])
    result = []
    for entry in players.values():
        if not entry["champions"]:
            continue
        champion_ids = {c["policy_id"] for c in entry["champions"]}
        mmr = max(rated[entry["player_id"]], default=None)
        result.append({**entry, "mmr": mmr, "champion_ids": sorted(champion_ids),
                       "label": ", ".join(c["label"] for c in entry["champions"]),
                       "games": sum(any(s["policy_id"] in champion_ids and not s["filler"] for s in g["seats"])
                                    for g in games),
                       "games_any_version": sum(any(s["player_id"] == entry["player_id"] and not s["filler"]
                                                    for s in g["seats"]) for g in games)})
        del result[-1]["champions"]
    result.sort(key=lambda p: (p["mmr"] is None, -(p["mmr"] or 0), p["player"]))
    for index, player in enumerate(result):
        player["default"] = index < DEFAULT_PLAYERS
    return result


def seat_costs(snapshot, league_id):
    """Mean provider-billed LLM USD per seat-game for each policy version, from cached seat_models rows."""
    seats = defaultdict(float)
    policy_of = {}
    for row in (snapshot.get(("seat_models", league_id), {}).get("data") or {}).get("rows", []):
        key = (row["episode"], row["slot"])
        seats[key] += row["usd"]
        policy_of[key] = row["policy_version_id"]
    per_policy = defaultdict(list)
    for key, usd in seats.items():
        per_policy[policy_of[key]].append(usd)
    return {policy: {"usd": mean(values), "seats": len(values)} for policy, values in per_policy.items()}


def run_inputs(snapshot, games):
    durations = [minutes(g["running_at"], g["completed_at"]) for g in games.values() if g["status"] == "completed"]
    durations = [d for d in durations if d is not None]
    compute = [state["data"]["compute"] for key, state in ((g, snapshot.get(("detail", g), {})) for g in games)
               if state.get("data") and state["data"].get("compute") is not None
               and games[key]["status"] == "completed"]
    return {"median_minutes": quantile(durations, 0.5), "duration_games": len(durations),
            "compute_usd": mean(compute) if compute else None, "compute_games": len(compute),
            "in_flight": IN_FLIGHT}


def planner_data(snapshot, league, version):
    league_id = league["id"] if league else ""
    games = league_games(snapshot, league_id, version)
    rows, excluded, without_powers = scored_games(snapshot, games)
    members = (snapshot.get(("memberships", league_id), {}).get("data") or {}).get("rows", [])
    ratings = (snapshot.get(("ratings", league_id), {}).get("data") or {}).get("rows", [])
    sums = [sum(s["score"] for s in g["seats"]) for g in rows]
    times = [g["completed_at"] for g in rows]
    return {
        "league_id": league_id, "version": version, "powers": list(POWER_INDEX),
        "players": candidates(members, ratings, rows),
        "games": [{"seats": g["seats"]} for g in rows],
        "costs": {"seat_usd": seat_costs(snapshot, league_id), **run_inputs(snapshot, games)},
        "fit": {"games": len(rows), "excluded": excluded, "without_powers": without_powers,
                "first": when(min(times)) if times else None, "last": when(max(times)) if times else None,
                "score_sum_error": max((abs(total - 1) for total in sums), default=None),
                "history": "All cached history" + ("" if version == "all" else " for the selected version")},
    }


def tournament_panel(snapshot, league, competition, now, version):
    """Panel shell; the interactive planner fetches /tournament-data itself."""
    from .freshness import annotate

    league_id = league["id"] if league else ""
    games = league_games(snapshot, league_id, version)
    rows, excluded, without_powers = scored_games(snapshot, games)
    dependencies = ([snapshot.get(("memberships", league_id), {}), snapshot.get(("ratings", league_id), {})]
                    + [state for state in competition["episode_sources"].values()])
    dependencies = [{**d, "name": d.get("name", "uncollected source")} for d in dependencies]
    result = {
        "sentence": (f"Plan the week's seven-player final from {len(rows)} scored league games "
                     "(all cached history), with two models side by side." if rows else
                     "No scored league games are cached for this selection yet."),
        "columns": [], "rows": [], "chart": None,
        "note": ("Statistics run in your browser from cached games only. League games are mixed fields, "
                 "not the final seven; strategies may adapt. See the README's Tournament planner section."),
    }
    annotate(result, dependencies, now)
    result["coverage"] = (f"{len(rows)} scored games; {excluded} excluded (tainted results or score conflict); "
                          f"{without_powers} without results facts use unknown powers. " + competition["game_coverage"])
    # `games` changes the URL only when more scored games arrive, so the kept widget refetches then.
    query = urlencode({"league": (league or {}).get("key", "press"), "version": version, "games": len(rows)})
    result["widget"] = {"name": "tournament", "src": f"/tournament-data?{query}"}
    return result
