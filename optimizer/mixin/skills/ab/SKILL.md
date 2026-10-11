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
| Our seat crashed | any `exception` event, uncaught Python traceback or launcher `child_exit` line with a nonzero code in our seat log, or a seat log with no `decision` line at all (the bot died at startup and the seat held every phase) | **Our policy** |
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
  - Game counts: use `tools/sizing.py`, which carries the SDs measured
    in hosted gunboat on 2026-10-10 (0.22 per seat, about 0.34 for a paired
    difference). At those SDs a 0.04 difference needs about 290 paired games
    for an even chance of reaching z = 2 (about 240 per arm with separate
    arms, so pairing saves about 1.7x in games, not 2 to 3x). The prior lab's
    "about 150 per arm" came from press games with lower variance.
- **Do not peek and stop.** Fix the episode count when you write the decision
  rule.

**Run a same-code check first, and swap the two seats.** Measured 2026-10-10 in a test-drive lab: two uploads of identical code,
seated in fixed roster seats 0 and 1 under a cyclic power rotation, read +0.113
for seat 0 (z 2.6, n=84). `paired.py` prints `a_in_lower_slot` and warns when
the seat order is one-sided. Our two seats are board neighbours in that design and
only one of them has a weak filler on its other side. A paired A/B must give
each version both seat positions equally (`tools/make_request.py
--balanced` writes both orders), and a new design or field set should first be
run with identical code to confirm it reads zero.

**A paired win is not a result until the candidate has also played alone.**
With paired seating both of our policies sit in the same game, so they also
play against each other, and the league never seats two of our entries
together. Measured 2026-10-10 in a test-drive lab:
a change won its paired run by +0.079 (z 3.08, 168 games, powers and seat order
balanced, same-code check passed) and then scored exactly level with the
baseline when each played alone against the field (0.235 vs 0.243, 84 games
per arm). The paired gain was taken from the twin. So:

1. Use paired seating to **screen**. It costs about 1.7 times fewer games,
   and a paired null is usually a safe reason not to promote (it would hide a
   real gain only if the change lost to its own twin exactly what it won
   from the field). It is not proof of "no effect": one null checked alone
   read −0.049, z −1.7.
2. Any paired win must pass a **candidate-alone check** before it changes the
   baseline or is submitted: two separate arms, each with one of our seats and
   the same six field seats, powers balanced
   (`tools/make_request.py field --balanced`), read with `compare.py`.
   Pre-register its pass mark next to the paired rule.
   `tools/run_ab.py --alone` runs it in one command.
3. For a verdict that must stand on its own, use separate arms from the start
   and size them with `tools/sizing.py --separate`.

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
into `../../instruments/` (your own space; the mixin's tools are in `../../tools/`).
