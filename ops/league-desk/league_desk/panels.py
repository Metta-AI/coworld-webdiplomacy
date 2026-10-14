"""Panel catalogue and competition/game dependency joins."""
SECTIONS = [
    ("Standings and rating", [
        ("Competing players", "Softmax API · Read-only SQL", 12,
         "Competing memberships and ratings have not been collected."),
        ("MMR over time", "Local rating snapshots", 4, "Rating history begins when snapshot collection is enabled."),
        ("Policy submissions", "Softmax API", 4, "Submission history has not been collected."),
        ("Membership and exposure", "Softmax API", 4, "Membership and seat exposure have not been collected."),
        ("Rating interval over time", "Local rating snapshots", 12, "No rating snapshots yet."),
    ]),
    ("Tournament planning", [
        ("Tournament planner", "Results and Softmax API", 12, "No scored league games collected yet."),
    ]),
    ("Matchups", [
        ("Head to head", "Softmax API", 6, "No scored shared games collected."),
        ("Games together", "Softmax API", 6, "No shared games collected."),
    ]),
    ("The board", [
        ("The board", "Replays and results", 12, "No replay boards ingested."),
        ("Score by policy and power", "Replays and results", 12, "Results have not been ingested."),
    ]),
    ("Rounds and games", [
        ("Round duration", "Softmax API", 4, "Completed round history has not been collected."),
        ("Game duration", "Softmax API", 4, "Game timestamps have not been collected."),
        ("Games per day and how they ended", "Softmax API · Replays and results", 4,
         "Game history and end reasons have not been collected."),
    ]),
    ("Money and model use", [
        ("Daily spend against budget", "Read-only SQL", 4, "Daily cost breakdown has not been collected."),
        ("League against experience requests", "Read-only SQL", 4, "Comparable source costs have not been collected."),
        ("LLM spend per seat per game", "Read-only SQL", 4, "Per-seat usage has not been collected."),
        ("Models in use", "Read-only SQL", 8, "No model usage collected; this does not mean policies use no model."),
        ("Cost per round and per game", "Softmax API", 4, "Cost attribution has not been collected."),
    ]),
    ("Experience requests", [
        ("Requests per day", "Softmax API", 4, "Request history has not been collected."),
        ("How long games take", "Softmax API", 4, "Request and game timings have not been collected."),
        ("Common config overrides", "Read-only SQL", 4, "Stored request overrides have not been collected."),
    ]),
    ("Timing and seat health", [
        ("Time to Ready", "Results and game log", 6, "No public order activity collected."),
        ("Seat health", "Results and game log", 6, "No instrumented seat health collected."),
    ]),
]


def competition_panels(snapshot, league, now, start=None, version="all"):
    start = now - 7 * 86400 if start is None else start
    from .competition_metrics import exposure, histories, rating_history, standings, submission_series
    from .config import COMPETITION_SECONDS, FAILURE_MARGIN, POLL_SECONDS
    from .game_metrics import game_durations, games_together, head_to_head, round_durations, throughput

    scope = league["id"] if league else ""

    def source(name):
        return snapshot.get((name, scope), {})

    def data(name):
        return source(name).get("data") or {}

    rounds = data("rounds").get("rows", [])
    episode_sources = {key[1]: value for key, value in snapshot.items() if key[0] == "episodes" and
                       (value.get("data") or {}).get("league_id") == scope}
    all_games = {g["id"]: g for s in episode_sources.values() for g in s["data"]["rows"]}
    selected_games = [g for g in all_games.values() if version == "all" or g["coworld_id"] == version]
    matched_rounds = {key for key, state in episode_sources.items()
                      if any(g["coworld_id"] == version for g in state["data"]["rows"])}
    games = [g for g in selected_games if any(t is not None and start <= t <= now
             for t in (g["created_at"], g["completed_at"]))]
    finished = [g for g in games if g["completed_at"] is not None and start <= g["completed_at"] <= now]
    recent_rounds = [r for r in rounds if (version == "all" or r["id"] in matched_rounds)
                     and (r["completed_at"] is None or start <= r["completed_at"] <= now)]
    members, ratings = data("memberships").get("rows", []), data("ratings").get("rows", [])
    submissions = data("submissions").get("rows", [])
    points = rating_history(source("ratings").get("history", []))
    history_points = [p for p in points if start <= p["time"] <= now and
                      (version == "all" or p["canonical_id"] == version or p["last_round_id"] in matched_rounds)]
    complete = data("submissions").get("complete", False)
    recent_submissions = [s for s in submissions if s["created_at"] is not None
                          and start <= s["created_at"] <= now]
    panels = {
        "Competing players": standings(members, ratings, points, submissions, finished, now, complete),
        **histories(history_points), "Policy submissions": submission_series(submissions, now, complete, start),
        "Membership and exposure": exposure(members, games, recent_rounds, episode_sources, recent_submissions, now,
                                             data("settings").get("game_target")),
        "Round duration": round_durations(recent_rounds, source("settings").get("history", []), now),
        "Game duration": game_durations(finished), "Games per day and how they ended": throughput(finished),
        "Head to head": head_to_head(finished), "Games together": games_together(finished),
    }
    panels["Competing players"]["columns"][5] = "Scored games (selection)"
    panels["Competing players"]["note"] += " Score and cost cells use the selection; submissions stay 24h/7d."
    panels["Membership and exposure"]["note"] += " Round exposure uses whole matching rounds, possibly mixed versions."
    panels["Round duration"]["note"] += (
        " Version selection matches observed games; round duration is not version-isolated.")
    markers = [{"time": o["observed_at"], "label": "Canonical observed: " + o["data"]["version"]}
               for o in snapshot.get(("canonical", "all"), {}).get("history", [])
               if start <= o["observed_at"] <= now]
    for result in panels.values():
        if result.get("chart"):
            result["chart"]["markers"] = markers
    game_dependencies = [source("rounds")] + [episode_sources.get(r["id"], {}) for r in recent_rounds]
    dependencies = {
        "Competing players": [source(n) for n in ("memberships", "ratings", "submissions")] + game_dependencies,
        "MMR over time": [source("ratings")], "Rating interval over time": [source("ratings")],
        "Policy submissions": [source("submissions")],
        "Membership and exposure": [source(n) for n in ("memberships", "submissions", "settings")] + game_dependencies,
        "Round duration": [source("rounds"), source("settings")],
    }
    coverage = (f"{len(episode_sources)}/{len(rounds)} cached rounds have episode listings; "
                + ("round listing exhausted" if data("rounds").get("complete") else "round scan incomplete")
                + ". API retention before earliest listed round is unknown; "
                "retained hidden rounds stay in local history.")
    for name, panel in panels.items():
        deps = dependencies.get(name, game_dependencies)
        from .freshness import annotate
        annotate(panel, deps, now, cadence=POLL_SECONDS if name == "Round duration" else COMPETITION_SECONDS)
        panel["coverage"] = coverage if name not in ("Policy submissions", "MMR over time",
                                                    "Rating interval over time") else ""
        if panel["missing"]:
            panel["sentence"] = "Collection incomplete. " + panel["sentence"]
    if source("memberships").get("data") is None:
        panels["Competing players"]["sentence"] = "No competing memberships collected."
        panels["Membership and exposure"]["sentence"] = "No complete membership scan."
    if not episode_sources:
        for title in ("Head to head", "Games together", "Games per day and how they ended"):
            panels[title]["sentence"] = "No episodes collected; game coverage is unavailable."
    alerts = []
    for rating in ratings:
        streak, limit = rating["failures"], rating["failure_limit"]
        current = any(m["status"] == "competing" and m["substatus"] == "active" and
                      m["policy_id"] == rating["current_policy_id"] for m in members)
        if (current and streak is not None and limit is not None and limit > 0
                and streak >= max(1, limit - FAILURE_MARGIN)):
            alerts.append(f"{rating['player']}: {streak:g}/{limit:g} consecutive platform failures.")
    versions = {g["coworld_id"] for g in all_games.values()}
    if len(versions) > 1:
        alerts.append("Multiple game versions observed; cumulative ratings may contain mixed-version inputs.")
    if any(p["stale"] or p["missing"] for p in panels.values()):
        alerts.append("Competition or game sources are stale or incomplete; inspect panel coverage.")
    last_day = [g for g in all_games.values() if g["completed_at"] is not None
                and now - 86400 <= g["completed_at"] <= now]
    return {"version_markers": markers, "panel_data": panels, "competition_alerts": alerts,
            "day_games": {status: sum(g["status"] == status for g in last_day) for status in ("completed", "failed")},
            "game_coverage": coverage, "episode_sources": episode_sources,
            "competition_age": max((p["age"] for p in panels.values() if p["age"] is not None), default=None),
            "missing_panels": sum(bool(p["missing"]) for p in panels.values()),
            "stale_panels": sum(bool(p["stale"]) for p in panels.values())}
