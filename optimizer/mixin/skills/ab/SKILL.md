---
name: webdiplomacy-ab
binding: ab
description: >
  webDiplomacy binding for the core ab-compare skill: this game's metrics,
  decompositions, taint definition, statistical tests, and N floors.
---

# A/B binding — webDiplomacy

The core `ab-compare` skill carries the comparison standard (fresh + matched,
taint before means, decompose before judging, noise is a verdict, regression
sweep). This binding supplies the webDiplomacy specifics. Game rules are in
[docs/game.md](../../docs/game.md).

## Metrics that matter

One observation is **one seat of our policy in one episode**.

| Metric | Type | Direction | Why it matters |
|---|---|---|---|
| **Score vs par** | mean | higher | The headline. Our seat's score minus the **same-batch field par**: the mean score of every non-target seat at the **same power** in the same set of episodes. Removes power luck (France scores about 3× England) |
| Raw score | mean | higher | What the league ranks (mean score). Report it, but never judge on it alone |
| Final supply centers | mean | higher | Drives the SC² score. From `results.json` `members[].supplyCenterNo` (strings), **not** the replay's `Finished` entry |
| Survival rate | rate | higher | Eliminated powers score 0 |
| Solo rate (ours) | rate | higher | A solo scores 1. Rare in mixed fields |
| Opponent solo rate | rate | lower | A rival's solo zeroes every other seat |
| `rejected` orders per game | count | must be 0 | Upstream silently dropped orders. Any nonzero is a bug (see Taint) |

For LLM policies also report LLM calls and failures per seat-phase and cost
(`wd.py costs`), so "the change fired" is checked next to "the score moved".

## Decompositions

- **By power, always.** Powers are shuffled per episode and differ hugely in
  strength (par from 0.290 France to 0.090 England in the 2026-10 field). Report
  score vs par per power, then pooled across powers. A pooled raw mean mostly
  measures which powers each arm drew.
- **By game year** for "where is the loss": the center trajectory by year (from
  `wd.py seats`) shows whether a change loses early (openings) or late (the
  endgame).
- **By phase type** when a change touches retreats or builds.
- **By model and prompt** for LLM policies: model × soul is the unit under
  test. Never pool versions that differ in model.

## Taint — what an invalid episode is

Drop or flag at the episode level **before** any mean, and report the count for
each arm:

| Taint | How to detect | Whose fault |
|---|---|---|
| Cancelled game | `results.json` `outcome == "cancelled"` (scores are 1/7 each) | Platform |
| Episode timeout before the year cap | `reason == "episode_timeout"` | Usually platform or a slow bot; check timing |
| Dropped orders | nonzero `rejected` in our seat's `decision` log lines | **Our policy** (a bug to fix, not just filter) |
| Our seat crashed | any `exception` event in our seat log | **Our policy** |
| Missing artifacts | results, replay or our seat log not downloaded | Fetch problem. Re-run the fetcher; report coverage, **never impute** |
| Failing LLM seat | every `llm_call` in our seat log failed, so the seat silently played its floor | Configuration (model or parameter mismatch). Check per seat, per episode |
| Mixed opponent sets | the batch spans a field change | Design error. Never pool across opponent sets |

"Our policy crashed" versus "the platform failed": our exceptions and rejections
are visible only in our own seat log; platform failures show as `cancelled`,
`episode_timeout`, or a request with failed child episodes. Rivals' logs are not
readable (403), so a rival's crash looks like a seat that holds every phase.

In the lab's hosted press games, 208 of 208 ended normally (`drawn` or `won`
at the end year) and none had rejected orders. Taint is rare but must still be
checked every time.

## Tests and floors

- **Default design: paired seating.** Seat the baseline and the candidate in
  the **same games** (plus five field seats). Each game gives a paired
  difference: (candidate − par at its power) − (baseline − par at its power).
  This needed 2 to 3 times fewer games than separate arms for the same
  precision. Use separate arms only when pairing is impossible, for example
  when the question needs our policy against the league's exact six-opponent
  field.
- **Test:** the mean paired difference over its standard error, z = mean / SE.
  For separate arms, compare per-power score vs par with a two-sample test per
  power and pooled (`compare.py`).
- **|z| < 2 is no result.** Three leads of about +0.08 at z ≈ 1.4 vanished when
  re-run. Report "no detectable change" plainly.
- **Priors for sizing**, from 2026-10 measurements (recompute after your first
  batch):
  - Per-seat score SD is about 0.12 to 0.18 (0.09 to 0.13 for the lab's press
    policy, 0.08 to 0.18 for field seats).
  - At 16 episodes per arm, SE is about 0.02 to 0.03, so only effects of about
    0.08 or more can show up.
  - Resolving a 0.04 difference takes about **150 episodes per arm** (separate
    arms). Paired seating needs fewer.
- **Do not peek and stop.** Fix the episode count when you write the decision
  rule.

Caution (inference, not measured): with paired seating both of our policies sit
in the same game, so they also play against each other. If the change alters
how our policy treats a same-family opponent, the paired result may not transfer
to the league. Confirm a paired win with a candidate-only batch against the
field before submitting.

## Tooling

Standard-library Python in `tools/`, run from the optimizer root. They read
episode directories from the optimizer's `fetch_artifacts.py` or from a local
`coworld run-episode`. **Exact flags live in each tool's docstring** (run with
`--help`); they may shift slightly from what is shown here.

| Tool | What it answers | CLI |
|---|---|---|
| `wd.py metrics` | Per-power score vs same-batch field par, final centers, survival, solo; artifact coverage; our telemetry (rejected orders, exceptions) | `python3 games/webdiplomacy/tools/wd.py metrics DIR... --policy NAME:vN [--json]` |
| `paired.py` | Paired difference and z for two policies seated in the same games | `python3 games/webdiplomacy/tools/paired.py ...` (see docstring) |
| `compare.py` | A/B by power for separate arms: groups `all` plus each power, with verdicts per cell | `python3 games/webdiplomacy/tools/compare.py BASE_DIR CAND_DIR --baseline NAME:vN --candidate NAME:vM` |
| `wd.py costs` | LLM spend per seat and per movement phase | `python3 games/webdiplomacy/tools/wd.py costs DIR...` |

All of them load episodes through `webdip_episodes.py`, which handles
slot-to-power mapping and bytes-literal seat logs. Analysis beyond these goes
into `../../instruments/` as a persistent instrument.
