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
  field can lose against another.
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
| **A/B (default: paired)** | Candidate + baseline + **five** field seats in the same games, **each version in each of the two seat positions for half the games** (`tools/make_request.py paired --balanced` writes the 14 bodies). Analyze with `paired.py`. A paired **win** is a screen result only: confirm it with separate arms before promotion (the [ab binding](../ab/SKILL.md) says why) |
| A/B (separate arms) | Per arm: one candidate seat + **six** field seats, identical field in both arms, both arms in the same window. Analyze with `compare.py` |
| Field eval | One candidate seat + six field seats |
| Health check | One `classic-press-short` episode with the candidate (and any new model or prompt). Build it with `tools/make_request.py field … -n 1 --variant classic-press-short`. Then confirm every `llm_call` in our seat logs succeeded and `rejected` is 0: the `telemetry` line of `wd.py metrics DIR --policy NAME:vN` (`llm calls N (0 failed…)`, `rejected 0`, `exceptions 0`) and `press_sent` in the trace. Logs are readable only after the game ends. `run_ab.py --health <six-seat field set>` launches it with the batch and notes its id in the record; it does not fetch or read it. **One game can fail for a reason that is not your build:** the platform can delete our pod mid-game (`wd.py metrics` then says "without our log 1"). When the clock matters, launch two or three health games, not one (`run_ab.py --health SET --health-games 2`). A pass shows the build runs; it does not show that a new guard or rule ever fires: read the mechanism from the full batch |
| Crash test | One short episode, any field. Look only at connect, play every phase, exit |

**Variant:** judge on the league's full variant: `classic-press` for the press
league, `classic-gunboat` for the gunboat league. `classic-press-short` ends in
1904, which changes the endgame; use it only for health and crash checks. The
same holds for any game shortened with `game_config_overrides`
([Faster first reads](#faster-first-reads-screens-never-verdicts)).

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
    {"player": {"policy_ref": "<policy>:vNEW"}, "slot": -1},
    {"player": {"policy_ref": "<policy>:vBASE"}, "slot": -1},
    {"player": {"policy_ref": "<field policy-version 1>"}, "slot": -1},
    {"player": {"policy_ref": "<field policy-version 2>"}, "slot": -1},
    {"player": {"policy_ref": "<field policy-version 3>"}, "slot": -1},
    {"player": {"policy_ref": "<field policy-version 4>"}, "slot": -1},
    {"player": {"policy_ref": "<field policy-version 5>"}, "slot": -1}
  ],
  "notes": "paired A/B <policy> vNEW vs vBASE, campaign <name>, field set <name>"
}
```

You rarely write this by hand. `tools/make_request.py` builds bodies from a
named opponent set in `field_sets.json`, and `tools/run_ab.py` runs the whole
A/B from an experiment record:

```sh
# 14 bodies: every power and both seat orders for each version, 2 games each = 28 games.
# A press set gets an LLM budget by default; a zero budget silences every LLM seat.
python3 games/webdiplomacy/tools/make_request.py paired --a <policy>:vNEW --b <policy>:vBASE \
    --field-set <paired set> -n 2 --balanced --no-maps --out games/webdiplomacy/.runtime/requests/<slug>.json
# the candidate-alone check for a paired win: 7 bodies per arm against a six-seat set
python3 games/webdiplomacy/tools/make_request.py field --a <policy>:vNEW \
    --field-set <field set> -n 5 --balanced --no-maps --out games/webdiplomacy/.runtime/requests/<slug>-alone.json
```

Dry-run it first: `skills/run-eval/scripts/eval_request.py create body.json --dry-run`
(it checks the body's shape, not that each version exists; a stale id fails at
create time). Set
`episode_player_llm_spend_limit_usd` to 0 when no seat uses an LLM.

## Episode-count floors

Sizes come from `tools/sizing.py` (press by default; `--league gunboat` for
the other league). Its SDs (press: 0.20 for a paired difference, 0.15 per
seat; gunboat: 0.34 and 0.22) are starting values, measured once
(2026-10-10/11, hosted, one or two opponent sets), not a fact about the game.
`paired.py` prints `sd` for your own batch: pass it with `--sd`.

- **Smoke / health: 1 episode.** Answers "does it run".
- **Directional: about 16 per arm.** With `sizing.py`'s starting SD only an
  effect of about 0.1 or more shows up (`sizing.py --games 16 --separate`).
  No verdict at this size.
- **Verdict: size it with `tools/sizing.py --effect <difference>`.** It prints
  the games for an even chance of reaching z = 2 and for an 80% chance, paired
  or (`--separate`) per arm.
- **|z| < 2 is no result**, whatever the episode count.

The calculation: the SE of a paired difference is the paired SD / √n; the SE of
a two-arm difference is about the per-seat SD × √(2/n).

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
  2026-10-10 (`results.countries` matched in every game checked). One request
  holds one assignment, so a full rotation of powers takes **one request per
  permutation**.
- Alternative (not tried): `game_config_overrides.seed` fixes
  every episode in a request to that seed, and therefore to that seed's power
  assignment. Every episode then repeats the same seed, so deterministic bots
  replay identical games.
- To ask about one power, use `--pin-a POWER`: our seat keeps that power and
  the field seats rotate through the others.

## Pacing

- Duration, as the platform reported it on 2026-10-11 (`tools/batches.py`
  measures your own batches): a full hosted `classic-press` game **ran about
  61 minutes** with 4-minute phases (with the 3-minute phases of
  Coworld 0.7.10 on, a median 45 over 171 league games), and games in one launch run in parallel, so a batch takes
  little longer than its slowest game; a late or restarted game, or a full
  queue, stretches it. A `classic-press-short` health game takes about 25
  minutes. A gunboat game runs about 2 minutes, but it has no press. The lab
  manual's "Run one A/B" has the table.
- Cost: the platform estimates **1.4 to 3.3 credits per press
  game** (short or full; it rose by half within one night) when the request is created and records a `cost_usd` of about
  **$0.5 per game** afterwards; 0.5 credits per gunboat game. The credits
  actually charged have not been read back
  ([platform.md](../../docs/platform.md#cost-and-duration)).
  Tell the user the estimate the create step printed, as an estimate.
- **Size before you launch.** `tools/sizing.py --games N` gives the smallest
  effect a run can see (with its starting SD: 0.08 at 28 press games, 0.04 at
  84). Compare it with what the nearest earlier test read
  (`../../open_levers.md`, `../../experiments/`). A run that
  cannot see the plausible effect is a mechanism check, not a test: say so in
  the record, or plan the larger total from the start
  ([ab binding](../ab/SKILL.md#extending-a-run)).
- **Stream artifacts while games run** (`fetch_artifacts.py XREQ --watch`).
  Never block a session on a whole request.
- A parent request shows `failed` as soon as one child fails; wait for all
  children before reading it.
- Fire both arms of a separate-arms A/B back to back, in the same window.
- The candidate-alone check may be launched with the paired run instead of
  after it (`run_ab.py --alone`, once the paired ids are in the record), at
  the cost of its games if the paired run is null.
- **A league entry is not an eval.** A round is a few games against whoever is
  entered, it is rated on finishing order, not on score vs par, and a player cannot
  start one ([game.md](../../docs/game.md#leagues)). Never plan evidence around
  a league round.

## Faster first reads (screens, never verdicts)

- **Price before you launch:** `tools/run_ab.py ... --dry-run` builds the bodies, launches
  nothing and prints the platform's last saved quote for requests of the same kind. The
  platform cannot price a request without creating it and the price moves, so treat the
  figure as a floor when the saved quote is more than an hour or two old.
- **Screen stage on the short variant:** `tools/run_ab.py --record <id> --a … --b … --field-set <set> -n 1
  --variant classic-press-short` plays the paired, balanced design on the short game (about 25
  minutes) and prints each version's health lines and `press_behaviour.py` table. Its ids go to
  the record's `screen:` list and are never pooled with the full run. No score read: the short
  game ends in 1904.
- **A shorter game than the short variant:** `end_year`, `phase_minutes` and
  `retreat_build_minutes` can be set per request (`make_request.py --config KEY=VALUE`,
  or `run_ab.py --variant <variant> --config KEY=VALUE` for a screen stage). A press game
  lasts about 2 × `phase_minutes` per year played, so `--variant classic-press --config
  end_year=1903 --config phase_minutes=2` is about 12 minutes. Cut `end_year` first: the
  years played stay the same game. A shorter `phase_minutes` gives every LLM seat, the
  field's too, less time to negotiate, so it suits a crash or health check and not a read
  of press behaviour. Never a score read, never pooled with the league's variant.
  [platform.md, "Shorter games"](../../docs/platform.md#shorter-games) has the settings and
  their limits.
- **Wake replay bench:** `tools/wake_bench.py` replays recorded phase-start decisions of our
  seats under another prompt, model or setting, through the policy's own code, and prints the
  `press_behaviour.py` table in minutes for cents. It shows whether a prompt changes what the
  agent does, never whether that scores: one decision has no consequences and no opponent
  reacts. It needs `tools/llm_sidecar_local.py` running with a working model key; `--scripted`
  checks the plumbing without one.
- **A credit limit on a launch:** `tools/run_ab.py ... --max-credits N` stops creating batches
  when the rest, at the price the platform just quoted, would pass N; `--add-set` launches a
  further full set into the same record. Plan the sets in the decision rule before the first.

## Local runs

Local runs debug; they never judge: the local field is not the hosted one.
Local tools need Docker and the `coworld` CLI.

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
