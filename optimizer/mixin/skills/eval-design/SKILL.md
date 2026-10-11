---
name: webdiplomacy-eval-design
binding: eval-design
description: >
  webDiplomacy binding for the core run-eval skill: rosters, episode-count
  floors, role pinning, and pacing for this game.
---

# Eval-design binding — webDiplomacy

The core `run-eval` skill carries the question-to-shape table and the eval
ladder. This binding sizes the rungs and names webDiplomacy's knobs. Request
body details, costs and the LLM sidecar are in
[docs/platform.md](../../docs/platform.md).

## Opponents: the field you will meet

- **Opponents come from the current field**: the league's current entrants and
  filler roster for the league you are targeting. A policy that wins against one
  field can lose against another (see [strategy.md](../../docs/strategy.md)).
- **Within one campaign, keep the same opponent set**, so every comparison in
  the campaign is against the same field. Record the set (the exact
  `policy_ref`s) in the experiment record.
- **When the field changes, refresh the set and start a new campaign.** Never
  pool results across opponent sets.
- **Explicit `policy_ref`s, never `random`.** `random` samples the league's
  champion pool. When we are most of that pool, it seats us against ourselves.
- **No self-play verdicts.** All-our-policy games never decide "better", and
  hosted XP is not spent on self-play. Self-play is for local debugging only.

## Sensible rosters

Every episode has exactly seven seats. For an A/B, pin and rotate the powers
(`tools/make_request.py --balanced`, fixed integer slots). `slot: -1` with
shuffled powers is for a quick field look, a health check or a crash test.

| Question | Roster |
|---|---|
| **A/B (default: paired)** | Candidate + baseline + **five** field seats in the same games, **each version in each of the two seat positions for half the games** (`tools/make_request.py paired --balanced` writes the 14 bodies). Analyze with `paired.py`. A paired **win** is a screen result only: confirm it with separate arms before promotion (measured 2026-10-10: a z = 3.1 paired win vanished alone) |
| A/B (separate arms) | Per arm: one candidate seat + **six** field seats, identical field in both arms, both arms in the same window. Analyze with `compare.py` |
| Field eval | One candidate seat + six field seats |
| Health check | One `classic-press-short` episode with the candidate (and any new model or prompt). Build it with `tools/make_request.py field … -n 1 --variant classic-press-short`. Then confirm every `llm_call` in our seat logs succeeded and `rejected` is 0 |
| Crash test | One short episode, any field. Look only at connect, play every phase, exit |

**Variant:** judge on the league's full variant: `classic-press` for the press
league, `classic-gunboat` for the gunboat league. `classic-press-short` ends in
1904, which changes the endgame; use it only for health and crash checks.

**LLM policies:** model × soul (prompt) is the unit under test. The model is
fixed per uploaded version, so each model is its own version and its own arm.

### Example request

The shape of one request body, with free slots and shuffled powers. A real
paired A/B is fourteen of these with pinned powers and both seat orders, which
`tools/make_request.py --balanced` writes for you (below). Replace each
placeholder with an explicit version reference:

```json
{
  "private": true,
  "target": {"league_id": "league_1bccc63d-cd0a-47d7-92d7-e762797b5f1c", "variant_id": "classic-press"},
  "num_episodes": 16,
  "episode_player_llm_spend_limit_usd": 14,
  "roster": [
    {"player": {"policy_ref": "mybot:v4"}, "slot": -1},
    {"player": {"policy_ref": "mybot:v3"}, "slot": -1},
    {"player": {"policy_ref": "<field policy-version 1>"}, "slot": -1},
    {"player": {"policy_ref": "<field policy-version 2>"}, "slot": -1},
    {"player": {"policy_ref": "<field policy-version 3>"}, "slot": -1},
    {"player": {"policy_ref": "<field policy-version 4>"}, "slot": -1},
    {"player": {"policy_ref": "<field policy-version 5>"}, "slot": -1}
  ],
  "notes": "paired A/B mybot v4 vs v3, campaign <name>, field set <name>"
}
```

You rarely write this by hand. `tools/make_request.py` builds bodies from a
named opponent set in `field_sets.json`, and `tools/run_ab.py` runs the whole
A/B from an experiment record:

```sh
# 14 bodies: every power and both seat orders for each version, 2 games each = 28 games.
# A press set gets an LLM budget by default; a zero budget silences every LLM seat.
python3 games/webdiplomacy/tools/make_request.py paired --a mybot:v4 --b mybot:v3 \
    --field-set <paired set> -n 2 --balanced --no-maps --out games/webdiplomacy/.runtime/requests/v4.json
# the candidate-alone check for a paired win: 7 bodies per arm against a six-seat set
python3 games/webdiplomacy/tools/make_request.py field --a mybot:v4 \
    --field-set <field set> -n 4 --balanced --no-maps --out games/webdiplomacy/.runtime/requests/v4-alone.json
```

Dry-run it first: `skills/run-eval/scripts/eval_request.py create body.json --dry-run`
(it checks the body's shape, not that each version exists; a stale id fails at
create time). Set
`episode_player_llm_spend_limit_usd` to 0 when no seat uses an LLM.

## Episode-count floors

From 2026-10 measurements; recompute from your first batch:

- **Press:** per-seat score SD is about 0.12 to 0.18 (prior lab). The SD of a
  paired difference has **not been measured in press**; `tools/sizing.py`
  uses an estimate of 0.23 until you measure it in your first paired batch.
- **Gunboat** (hosted, 2026-10-10, one opponent set; re-measure): 0.22 per
  seat for the search, and 0.30 to 0.36 for a paired difference. Use
  `tools/sizing.py --league gunboat`.
- **Smoke / health: 1 episode.** Answers "does it run".
- **Directional: about 16 per arm.** The standard error of the difference
  between two arms is 0.04 to 0.06, so only effects of about 0.08 or more
  show up. Most of the prior lab's results stopped here and
  none reached a verdict.
- **Verdict: size it with `tools/sizing.py`** (press by default). For a 0.04
  difference in press it gives about 135 paired games, or about 115 per arm
  with separate arms, for an even chance of reaching z = 2 (about double for an
  80% chance). In gunboat the same difference needs about 290 paired games.
- **|z| < 2 is no result**, whatever the episode count.

The calculation: the SE of a two-arm difference is about SD × √(2/n). The prior
lab pre-registered 150 per arm assuming SD 0.19. With the SD it then measured
(0.12 to 0.18), 150 per arm gives a difference SE of 0.014 to 0.021, so a 0.04
effect lands at z ≈ 1.9 to 2.9. At 16 per arm the difference SE is 0.04 to
0.06.

## Role/seat pinning

- **A/B default: balanced pinning.** `tools/make_request.py --balanced` pins
  powers and rotates them, so each version plays every power equally and, in a
  paired A/B, holds each seat position equally. Without pinning, powers are
  shuffled by the episode seed and an 80-game batch can give one policy a
  strong power many more times than another.
- **How pinning works: `countries`** (webDiplomacy Coworld 0.7.9 and later): `countries[slot]`
  is that slot's upstream country ID (a permutation of 1 to 7). Set it through
  `game_config_overrides.countries` with **fixed integer slots** in the roster.
  Seeds still vary, so episodes still differ. Verified in hosted evals on
  2026-10-10 (`results.countries` matched in every game checked). Pinning makes
  raw means honest but did not reduce the standard error. One request holds one assignment, so a full rotation of powers
  takes **one request per permutation**.
- Alternative (not tried): `game_config_overrides.seed` fixes
  every episode in a request to that seed, and therefore to that seed's power
  assignment. Every episode then repeats the same seed, so deterministic bots
  replay identical games.
- To ask about one power, use `--pin-a POWER`: our seat keeps that power and
  the field seats rotate through the others.

## Pacing

- A full hosted `classic-press` game takes **60 to 100 minutes** (re-measure).
  Sixteen episodes in one request ran in parallel, about an hour of wall clock.
  Gunboat games take a few minutes, but they test only the search core.
- Cost: about **15 XP credits per full press game** with five LLM seats; our
  own LLM seat cost about $0.10 per game on glm-5.3-flash.
- **Stream artifacts while games run** (`fetch_artifacts.py XREQ --watch`).
  Never block a session on a whole request.
- A parent request shows `failed` as soon as one child fails; wait for all
  children before reading it.
- Fire both arms of a separate-arms A/B back to back, in the same window.

## Local runs

Local runs debug; they never judge. A local win once turned into a below-par
hosted result. Local tools need Docker and the `coworld` CLI.

- `python3 games/webdiplomacy/tools/wd.py local ...`: all seven seats run one
  image (self-play). For crash and activation checks.
- `python3 games/webdiplomacy/tools/wd.py arena ...`: one candidate against a
  local field. For quick screening only.
- `python3 games/webdiplomacy/tools/llm_sidecar_local.py ...`: a local stand-in
  for the hosted LLM sidecar, so an LLM policy runs its hosted code path
  locally. Needs `OPENROUTER_API_KEY`. In a sandboxed agent session, run it
  outside the sandbox or inbound connections from Docker never arrive.
- Use a distinct image tag per experiment. Killing a local run can leave game
  and player containers running; remove them by name.

**Exact flags live in each tool's docstring**; they may shift slightly.

## eval_defaults.yaml

This mixin ships no `eval_defaults.yaml`. The values above are the defaults.
