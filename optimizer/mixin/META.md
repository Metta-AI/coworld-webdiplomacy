# META — webDiplomacy field picture

The current picture of this game's competitive field, maintained by
`meta-recon`. Dated because it rots: when a session touches this lab and the
"As of" date below is older than the freshness window, suggest a refresh
before strategy work.

**As of:** *(date of last recon)*
**Freshness window:** 7 days *(tune per game volatility)*

## Who is in the field

*(every policy in the league's filler roster, from `coworld leagues <league_id>
--json` (`filler_policy_version_ids`), and every policy seated in its recent
rounds, from `python3 games/webdiplomacy/tools/field.py press|gunboat`: league
entrants and the fillers that take the empty seats. One row each. Version ids go
into `field_sets.json` as the opponent sets for evals. Say which league a row is
for: the same bot name can sit in both.)*

| Policy version | Entrant or filler | How it plays (and how we know) | Seen in rounds |
|---|---|---|---|

## Standings snapshot

*(top of the relevant division: who, with what policy, at what rating (MMR) and mean score; who's
rising/falling since last recon)*

## Decoded strategies

*(what the top policies are actually doing — mechanism-level where known, with
the evidence: replays watched, telemetry, behavior patterns. Tag transplant
candidates: copyable / prerequisite-first / not-copyable)*

## Meta shifts

*(what changed since the last recon: new entrants, version bumps, strategies
that decayed or got countered)*

## Where the field looks weak

*(exploitable gaps, with the evidence — these feed `diagnose` and the human's
strategy conversations)*

## Curated replays

*(episodes worth a human's attention, each with one line on why)*
