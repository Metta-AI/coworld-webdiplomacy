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

Every episode has exactly seven seats. Use `slot: -1` everywhere; powers are
shuffled per episode anyway.

| Question | Roster |
|---|---|
| **A/B (default: paired)** | Candidate + baseline + **five** field seats, all in the same request. Analyze with `paired.py` |
| A/B (separate arms) | Per arm: one candidate seat + **six** field seats, identical field in both arms, both arms in the same window. Analyze with `compare.py` |
| Field eval | One candidate seat + six field seats |
| Health check | One `classic-press-short` episode with the candidate (and any new model or prompt). Then confirm every `llm_call` in our seat logs succeeded and `rejected` is 0 |
| Crash test | One short episode, any field. Look only at connect, play every phase, exit |

**Variant:** judge on the league's full variant: `classic-press` for the press
league, `classic-gunboat` for the gunboat league. `classic-press-short` ends in
1904, which changes the endgame; use it only for health and crash checks.

**LLM policies:** model × soul (prompt) is the unit under test. The model is
fixed per uploaded version, so each model is its own version and its own arm.

### Example request (paired A/B)

From the prior lab's request builder, adapted for paired seating. Replace each
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

Dry-run it first: `eval_request.py create body.json --dry-run`. Set
`episode_player_llm_spend_limit_usd` to 0 when no seat uses an LLM.

## Episode-count floors

From 2026-10 measurements; recompute from your first batch:

- Per-seat score SD is about 0.12 to 0.18.
- **Smoke / health: 1 episode.** Answers "does it run".
- **Directional: about 16 per arm.** SE about 0.02 to 0.03; only effects of
  about 0.08 or more show up. Most of the prior lab's results stopped here and
  none reached a verdict.
- **Verdict: about 150 per arm** to resolve a 0.04 difference with separate
  arms. Paired seating needs 2 to 3 times fewer games.
- **|z| < 2 is no result**, whatever the episode count.

The calculation: the SE of a two-arm difference is about SD × √(2/n). The prior
lab pre-registered 150 per arm assuming SD 0.19. With the SD it then measured
(0.12 to 0.18), 150 per arm gives a difference SE of 0.014 to 0.021, so a 0.04
effect lands at z ≈ 1.9 to 2.9. At 16 per arm the difference SE is 0.04 to
0.06.

## Role/seat pinning

- **Default: powers are shuffled** by the episode seed. Decompose by power in
  analysis (the ab binding); that needs no pinning.
- **Pin powers with `countries`** (coworld 0.7.9 and later): `countries[slot]`
  is that slot's upstream country ID (a permutation of 1 to 7). Set it through
  `game_config_overrides.countries` with **fixed integer slots** in the roster.
  Seeds still vary, so episodes still differ. The setting is not yet tried in a
  hosted eval; confirm it in the hosted `config_schema`
  (`coworld show <coworld-id> --json`) and check `results.countries` in the
  first episode. One request holds one assignment, so a full rotation of powers
  takes **one request per permutation**.
- Alternative (not tried): `game_config_overrides.seed` fixes
  every episode in a request to that seed, and therefore to that seed's power
  assignment. Every episode then repeats the same seed, so deterministic bots
  replay identical games.
- Pin powers only when the question is about a specific power. Pinning changes
  which powers the field plays too.

## Pacing

- A full hosted `classic-press` game takes **60 to 100 minutes** (re-measure).
  Sixteen episodes in one request ran in parallel, about an hour of wall clock.
  Gunboat games are much shorter.
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
