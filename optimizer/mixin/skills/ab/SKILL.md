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
| **Score vs par** | mean | higher | The headline. Our seat's score minus the **same-batch field par**: the mean score of every non-target seat at the **same power** in the same set of episodes. Removes power luck: the powers do not start equal, and a shuffle assigns them |
| Raw score | mean | higher | What decides a seat's place among the entrants in a league game (the league's OpenSkill rating moves on that order). Report it, but never judge on it alone |
| Final supply centers | mean | higher | Drives the SC² score. From `results.json` `members[].supplyCenterNo` (strings), **not** the replay's `Finished` entry |
| Survival rate | rate | higher | Eliminated powers score 0 |
| Solo rate (ours) | rate | higher | A solo scores 1. Rare in mixed fields |
| Opponent solo rate | rate | lower | A rival's solo zeroes every other seat |
| `rejected` orders per game | count | must be 0 | Upstream silently dropped orders. Any nonzero is a bug (see Taint) |

For LLM policies also report LLM calls and failures per seat-phase and cost
(`wd.py costs`), so "the change fired" is checked next to "the score moved".

**Check the mechanism beside the score, and keep the two apart.** A change is
meant to alter a behaviour so that the score rises. Measure the behaviour in
the same games: the counter the change logs, if it has one, and the behaviour
itself (`tools/holds.py` for anything meant to free units;
`tools/board_counts.py` for an order or a centre). Three outcomes, and they mean different things:

| Behaviour | Score | What it says |
|---|---|---|
| did not move | any | The change did not bite. The run says nothing about the hypothesis |
| moved | moved, \|z\| ≥ 2 | A result |
| moved | \|z\| < 2 | The behaviour is real and is not (at this dose) where the points are. Inconclusive on the score; say both halves |

## Decompositions

- **In a paired run, read a power from `vs_par_by_power`.** `paired.py` prints
  it: each version's mean score vs par *at the same power*, and the difference
  with its (unpaired) standard error. Do not read `pair_diff_when_a_plays` as a
  per-power effect: in each of those games the other version holds a different
  power, so identical code can read strongly negative at one power and
  strongly positive at another. With 7 powers and the game counts a session
  can afford, a per-power cell is a prompt to look, rarely a verdict.
- **By power, always.** Powers are shuffled per episode and differ in
  strength. Report score vs par per power, then pooled across powers. A pooled raw mean mostly
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
| Cancelled game | `results.json` `outcome == "cancelled"` (scores are 1/7 each; taint `cancelled`) | Platform |
| Failed hosted episode | `episode.json` `status` is `failed`, `error` or `cancelled` (taint `episode_failed`) | Platform |
| Episode timeout before the year cap | `results.json` `reason == "episode_timeout"` (taint `episode_timeout`) | Usually platform or a slow bot; check timing |
| Dropped orders | nonzero `rejected` in our seat's `decision` log lines (taint `rejected_orders`) | **Our policy** (a bug to fix, not just filter) |
| Our seat crashed | any `exception` event, uncaught Python traceback or launcher `child_exit` line with a nonzero code in our seat log (taint `exception`), or a seat log with no `decision` line at all (taint `no_decisions`: the bot died at startup and the seat held every phase) | **Our policy** |
| Missing artifacts | results, replay or our seat log not downloaded | Fetch problem. Re-run the fetcher; report coverage, **never impute** |
| Our pod was deleted mid-game | the seat log is one line, "No logs collected for pod …: the pod was deleted before log collection" (taint `pod_deleted`) | Platform: about 2.5% of press seats on 2026-10-10 and 2026-10-11, more under heavy load. Re-fetching does not help. **A taint, not only a lost log:** the bot stopped and the seat held from then on (28 of 29 such seats held their last three or more movement phases; 21 of 3,513 other logged seats did). It does not depend on how we were doing, so dropping these games does not bias the mean. Report the number |
| Failing LLM seat | at least half of the `llm_call`s in our seat log failed (taint `llm_failing`), so the seat mostly played its floor in silence | Configuration (model or parameter mismatch). Check per seat, per episode |
| Mixed opponent sets | the batch spans a field change | Design error. Never pool across opponent sets |
| Another seat's pod was deleted, or another seat crashed | only visible when that seat's log is on disk (an account that owns the field bots); otherwise a field seat that holds to the end (`tools/holds.py`, "stopped seats"). `wd.py metrics` prints "other seats tainted in N counted game(s)" with the episodes, and `paired.py` lists them under `other_seats_tainted` | Platform, or the other bot. The tools drop games where **our** seat is tainted and keep these, so "taint: none" on the line above it speaks only of our seats. In a paired run both our seats sit beside the dead seat, so the difference is mostly unharmed; in an alone run our level is flattered (a dead neighbour is free centres). Count them and say so |

**A taint that goes with losing biases the mean.** Dropping an episode is safe
only when the fault is unrelated to the result. For example, a policy that
raises an exception in a phase where it has no units left: the `exception`
filter then removes exactly the games in which our seat was wiped out. When a
taint appears, look at the score of the games
it drops, and report the read with and without them (`paired.py --keep-tainted`).

"Our policy crashed" versus "the platform failed": our exceptions and rejections
are visible only in our own seat log; platform failures show as `cancelled`,
`episode_failed`, `episode_timeout`, `pod_deleted`, or a request with failed
child episodes. Rivals' logs are not
readable (403), so a rival's crash looks like a seat that holds every phase.

Check taint every time, however rare it has been.

## Tests and floors

- **Default design: paired seating.** Seat the baseline and the candidate in
  the **same games** (plus five field seats). Each game gives a paired
  difference: (candidate − par at its power) − (baseline − par at its power).
  It needs fewer games than separate arms for the same precision (compare
  `tools/sizing.py` with and without `--separate`; the separate count is per
  arm). Use separate arms only when pairing is impossible, for example
  when the question needs our policy against the league's exact six-opponent
  field.
- **Test:** the mean paired difference over its standard error, z = mean / SE.
  For separate arms, compare per-power score vs par with a two-sample test per
  power and pooled (`compare.py`).
- **|z| < 2 is no result.** Report "no detectable change" plainly.
- **Sizing.** Game counts come from `tools/sizing.py` (press by default;
  `--league gunboat` for the other league). Its SDs (press: 0.20 for a paired
  difference, 0.15 per seat; gunboat: 0.34 and 0.22) are starting values,
  measured once (2026-10-10/11, hosted, one or two opponent sets), not a fact about
  the game. `paired.py` prints `sd` for your own batch: pass it with `--sd`.
- **The 16-game floor.** Fewer than about 16 games per arm is directional
  only: with `sizing.py`'s starting SD, two arms of 16 can show only an effect
  of about 0.1 or more (`sizing.py --games 16 --separate`).
- **Do not peek and stop.** Fix the episode count when you write the decision
  rule.

### Extending a run

A run that ends with no result is often followed by "play more of the same".
That is a second look at the data. It is allowed only in one of two forms; any
other extension is a new experiment whose first read is thrown away.

1. **Planned before the first game (preferred).** Write both stages into the
   record's decision rule before launch, for example: "Stage 1, 28 games: check the health
   line and that the mechanism fired; stop only if it did not fire, or for a
   difference of −0.08 or worse at z ≤ −2. No score verdict at stage 1. Stage
   2, to 84 games: one read on all 84, confirmed iff +0.04 or more at z ≥ 2."
   The threshold is the one the full size can see (`tools/sizing.py --games
   84`), chosen before any game.
2. **Decided after a first read with no result.** Then say so in a follow-on
   record that names the first (its `artifacts:` front matter lists the first
   record's folder; `run_ab.py` and the IDE read it pooled with the new
   record's own folder), and fix three things
   before launch: the total, one read on the pooled games, and the threshold.
   Because the data have been looked at once, ask more of the pooled result:
   **|z| ≥ 2.2** for a result (two looks at the 5% level), and treat 2.0 to 2.2
   as a lead. The threshold may follow from the new size; it may not follow
   from the first read ("it read +0.02, so call +0.02 a win" is the failure).
   No third extension under the same rule.

What an extension cannot rescue: a first run sized for an effect the change
was never likely to have. Before the first launch ask what size of effect the
mechanism could plausibly have (earlier tests in the same family, in
`../../open_levers.md` and `../../experiments/`, are the best guide) and size
for that.

**Small leads of one sign are not a trend.** Three readings of the same sign
inside the noise happen by chance one time in four. Count a lead as a reason
to size the next test properly, never as evidence that adds up.

**Run a same-code check first, and swap the two seats.** Two uploads of
identical code in fixed roster seats under a cyclic power rotation can read a
difference that looks real: our two seats are board neighbours in that design
and their other neighbours differ. `paired.py` prints `a_in_lower_slot` and
warns when the seat order is one-sided. A paired A/B must give
each version both seat positions equally (`tools/make_request.py
--balanced` writes both orders), and a new design or field set should first be
run with identical code to confirm it reads zero.

**A paired win is not a result until the candidate has also played alone.**
With paired seating both of our policies sit in the same game, so they also
play against each other, and the league never seats two of our entries
together. A paired gain can be taken from the twin and not from the field. So:

1. Use paired seating to **screen**. It costs fewer games, and a paired null
   is usually a safe reason not to promote (it would hide a real gain only if
   the change lost to its own twin exactly what it won from the field). It is
   not proof of "no effect".
2. Any paired win must pass a **candidate-alone check** before it changes the
   baseline or is submitted: two separate arms, each with one of our seats and
   the same six field seats, powers balanced
   (`tools/make_request.py field --balanced`), read with `compare.py`.
   `compare.py` gives a verdict only at adjusted p < 0.05, |z| >= 2 and at
   least 30 seats per side, so with 7 bodies a per-power verdict needs many
   games; judge the check on the pooled `all` row.
   Pre-register its pass mark next to the paired rule.
   `tools/run_ab.py --alone` runs it in one command, and it can be launched as
   soon as the paired run has written its ids, without waiting for the paired
   result. That costs the alone games when the paired run turns out
   null, so do it when the clock matters more than the credits. Size it to be
   able to answer: `-n 2` is 14 games per arm, below `compare.py`'s floor of 30
   seats per side, so it can only catch a large reversal; `-n 5` (35 per arm)
   is the least that can pass or fail.
3. For a verdict that must stand on its own, use separate arms from the start
   and size them with `tools/sizing.py --separate`.

## Tooling

Standard-library Python in `tools/`, run from the optimizer root. They read
episode directories from the optimizer's `fetch_artifacts.py` or from a local
`coworld run-episode`. **Exact flags live in each tool's docstring** (every
tool takes `--help`); they may shift slightly from what is shown here.

| Tool | What it answers | CLI |
|---|---|---|
| `wd.py metrics` | Per-power score vs same-batch field par, final centers, survival, solo; artifact coverage; our telemetry (rejected orders, exceptions) | `python3 games/webdiplomacy/tools/wd.py metrics DIR... --policy NAME:vN [--json]` |
| `paired.py` | Paired difference and z for two policies seated in the same games | `python3 games/webdiplomacy/tools/paired.py ...` (see docstring) |
| `compare.py` | A/B by power for separate arms: groups `all` plus each power, with verdicts per cell | `python3 games/webdiplomacy/tools/compare.py BASE_DIR CAND_DIR --baseline NAME:vN --candidate NAME:vM` |
| `wd.py costs` | LLM spend per seat and per movement phase | `python3 games/webdiplomacy/tools/wd.py costs DIR...` |
| `make_request.py`, `run_ab.py` | Build the request bodies for a balanced A/B; run one end to end, and the candidate-alone check | see the lab manual's "Run one A/B" |
| `seat_bias.py` | Whether one roster seat outscores another whoever sits there: the read for a same-code check | `wd.py seats DIR \| python3 games/webdiplomacy/tools/seat_bias.py` (see docstring) |
| `sizing.py` | Games needed for an effect, or the smallest effect a run can see | `python3 games/webdiplomacy/tools/sizing.py --effect 0.04` |
| `press_behaviour.py` | The mechanism check for a prompt or press-guard change: per version, the share of orders fixed, fixed as holds, every unit fixed, stances, messages, and `press_freed_holds` | `python3 games/webdiplomacy/tools/press_behaviour.py DIR... --policy NAME` |
| `holds.py` | The mechanism check for a change meant to free units: hold share by version beside the field, and any refusal counters the press layer logs | `python3 games/webdiplomacy/tools/holds.py DIR... --policy NAME --variant classic-press` |
| `batches.py` | What the run cost and how long it took, from the episode rows | `python3 games/webdiplomacy/tools/batches.py DIR...` |

All of them load episodes through `webdip_episodes.py`, which handles
slot-to-power mapping and bytes-literal seat logs. Analysis beyond these goes
into `../../instruments/` (your own space; the mixin's tools are in `../../tools/`).
