"""Panel catalogue and competition/game dependency joins."""
SECTIONS = [
    ("Standings and rating", [
        ("Competing players", "Softmax API", 12, "Competing memberships and ratings have not been collected."),
        ("MMR over time", "Local rating snapshots", 4, "Rating history begins when snapshot collection is enabled."),
        ("Policy submissions", "Softmax API", 4, "Submission history has not been collected."),
        ("Membership and exposure", "Softmax API", 4, "Membership and seat exposure have not been collected."),
        ("Rating interval over time", "Local rating snapshots", 12, "No rating snapshots yet."),
    ]),
    ("Rounds, games and time", [
        ("Round duration", "Softmax API", 4, "Completed round history has not been collected."),
        ("Game duration", "Softmax API", 4, "Game timestamps have not been collected."),
        ("Games per day and how they ended", "Softmax API · Replays and results", 4,
         "Game history and end reasons have not been collected."),
        ("Where an episode's time goes", "Softmax API", 12,
         "Detailed boot, connect, adjudication and upload timing is unavailable."),
    ]),
    ("Money and model use", [
        ("Daily spend against budget", "Softmax API", 4, "Daily cost breakdown has not been collected."),
        ("League against experience requests", "Softmax API", 4, "Comparable source costs have not been collected."),
        ("LLM spend per seat per game", "Read-only SQL", 4, "Per-seat usage has not been collected."),
        ("Models in use", "Softmax API", 8, "No model usage collected; this does not mean policies use no model."),
        ("Cost per round and per game", "Softmax API", 4, "Cost attribution has not been collected."),
    ]),
    ("Experience requests", [
        ("Requests per day", "Softmax API", 4, "Request history has not been collected."),
        ("How long they take", "Softmax API", 4, "Request and game timings have not been collected."),
        ("Common config overrides", "Read-only SQL", 4, "Stored request overrides have not been collected."),
    ]),
    ("Matchups and the board", [
        ("Head to head", "Softmax API", 8, "No scored shared games collected."),
        ("Score by power, all players", "Replays and results", 4, "Results have not been ingested."),
        ("Contested provinces", "Replays and results", 4, "No replay histories ingested."),
        ("Score by policy and power", "Replays and results", 8, "Results have not been ingested."),
        ("Phase timing", "Replays and results", 4, "No complete phase transitions ingested."),
        ("Time to Ready", "Needs instrumentation", 4, "Ready timing needs an end-of-game log record."),
        ("Seat health", "Needs instrumentation", 4,
         "Seat-level health is unavailable from the public artifacts collected here."),
    ]),
]


def competition_panels(snapshot, league, now):
    from .competition_metrics import exposure, histories, rating_history, standings, submission_series
    from .config import FAILURE_MARGIN
    from .game_metrics import episode_timing, game_durations, head_to_head, round_durations, throughput

    scope = league["id"] if league else ""

    def source(name):
        return snapshot.get((name, scope), {})

    def data(name):
        return source(name).get("data") or {}

    rounds = data("rounds").get("rows", [])
    episode_sources = {key[1]: value for key, value in snapshot.items() if key[0] == "episodes" and
                       (value.get("data") or {}).get("league_id") == scope}
    all_games = {g["id"]: g for s in episode_sources.values() for g in s["data"]["rows"]}
    games = [g for g in all_games.values() if any(t is not None and now - 7 * 86400 <= t <= now
             for t in (g["created_at"], g["completed_at"]))]
    finished = [g for g in games if g["completed_at"] is not None and now - 7 * 86400 <= g["completed_at"] <= now]
    recent_rounds = [r for r in rounds if r["completed_at"] is None or now - 7 * 86400 <= r["completed_at"] <= now]
    members, ratings = data("memberships").get("rows", []), data("ratings").get("rows", [])
    submissions = data("submissions").get("rows", [])
    points = rating_history(source("ratings").get("history", []))
    complete = data("submissions").get("complete", False)
    recent_submissions = [s for s in submissions if s["created_at"] is not None
                          and now - 7 * 86400 <= s["created_at"] <= now]
    panels = {
        "Competing players": standings(members, ratings, points, submissions, finished, now, complete),
        **histories(points), "Policy submissions": submission_series(submissions, now, complete),
        "Membership and exposure": exposure(members, games, recent_rounds, episode_sources, recent_submissions, now,
                                             data("settings").get("game_target")),
        "Round duration": round_durations(recent_rounds, source("settings").get("history", []), now),
        "Game duration": game_durations(finished), "Games per day and how they ended": throughput(finished),
        "Where an episode's time goes": episode_timing(finished), "Head to head": head_to_head(finished),
    }
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
        ages = [max(0, int(now - d["fetched_at"])) for d in deps if d.get("fetched_at") is not None]
        panel["age"] = max(ages) if ages else None
        panel["missing"] = sum(d.get("data") is None for d in deps)
        panel["stale"] = any(d.get("error") or d.get("fetched_at") is not None and
                             now > d["next_due"] + (d["next_due"] - d["fetched_at"])
                             for d in deps)
        panel["coverage"] = coverage if name not in ("Policy submissions", "MMR over time",
                                                    "Rating interval over time") else ""
        if panel["missing"]:
            panel["sentence"] = "Collection incomplete. " + panel["sentence"]
    if source("memberships").get("data") is None:
        panels["Competing players"]["sentence"] = "No competing memberships collected."
        panels["Membership and exposure"]["sentence"] = "No complete membership scan."
    if not episode_sources:
        for title in ("Head to head", "Games per day and how they ended"):
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
    return {"panel_data": panels, "competition_alerts": alerts,
            "day_games": {status: sum(g["status"] == status for g in last_day) for status in ("completed", "failed")},
            "game_coverage": coverage, "episode_sources": episode_sources,
            "competition_age": max((p["age"] for p in panels.values() if p["age"] is not None), default=None),
            "missing_panels": sum(bool(p["missing"]) for p in panels.values()),
            "stale_panels": sum(bool(p["stale"]) for p in panels.values())}
