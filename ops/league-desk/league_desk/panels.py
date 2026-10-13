"""The accepted page's panel list. Later gates replace these empty states with metrics."""
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
        ("Where an episode's time goes", "Needs instrumentation", 12,
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
