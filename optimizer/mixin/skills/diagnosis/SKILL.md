---
name: webdiplomacy-diagnosis
binding: diagnosis
description: >
  webDiplomacy binding for the core diagnose skill: this game's failure
  vocabulary and diagnostic instruments.
---

# Diagnosis binding — webDiplomacy

The core `diagnose` skill carries the method: signals into 2 to 4 varied,
mechanistic hypotheses, each pinned to a code location. This binding has two
parts: the failure modes already seen in this game, and a procedure for a
problem that is not on the list. Check `../../closed_levers.md` before
proposing anything; this game has a long list of refuted search ideas.

## Failure vocabulary

General failure modes observed in a prior webDiplomacy lab (2026-10). Each is
likely to recur in new policies.

- **Silent order drops.** Upstream returns HTTP 200 and keeps only the orders
  it accepts. The policy believes it moved; the replay shows it held. Detect:
  nonzero `rejected` in our `decision` lines, or our orders differing from the
  replay's adjudicated orders. Convoys and split coasts are the likely places
  (a guess; none were seen in the lab's hosted press games).
- **Invisible degradation.** A broken dependency fails every time while the
  policy keeps playing its fallback, with no error in the score. The common
  case: an LLM model or parameter mismatch at the sidecar makes every call fail
  and the seat plays plain search. Detect: per-seat `llm_call` statuses; a
  feature's own activation counters.
- **Wrong map knowledge.** An LLM reasons about adjacency from memory and gets
  it wrong (about 66 wrong adjacency claims per game in the lab; about 21 after
  it was given the connectivity list). Fix direction: hand the LLM the map.
- **Misplaced trust.** Re-trusting a power that already broke its word, or
  letting words restore trust before deeds do. The lab's press bot went back to
  trusting a betrayer 94 times in 46 relationships over 100 games. Also: trust
  logic built on our own record of promises, which was wrong in 10 of 30
  sampled "broken promise" verdicts. Prefer observed orders against our units
  and centers.
- **Ignoring the game horizon.** Planning past the end year (negotiating
  "1905 offensives" in a game that ends in 1904), or valuing position over owned
  centers in the final Autumn, when only owned centers score.
- **Over-tuning.** A change that wins against one field or one evaluation and
  loses against the next. Search that optimizes harder against the same
  position evaluation finds the evaluation's errors (see `closed_levers.md`).
  Judge against the field you will meet.

## Procedure for a new problem

**Sketch; to build out.** Use this when the signal does not match a known
failure mode.

1. **Rule out the plumbing.** Apply the ab binding's taint checks: rejected
   orders, exceptions, failing LLM calls, artifact coverage, cancelled or
   timed-out games. A plumbing failure looks like a strategy failure in the
   score.
2. **Locate the loss against par.** Which powers, which years, which phase
   types? Use `wd.py metrics` per power and `wd.py seats` trajectories by year.
3. **Read the worst games at that spot.** Open the replays at the phases where
   our centers fell (replay-inspection binding), next to our `decision` lines
   and, for press, the private press.
4. **Compare with the alternative.** What else could the policy have done? For
   the reference policy: the search's own choice against the orders finally
   played (for example, when the press layer constrained the search).
5. **Form 2 to 4 mechanistic hypotheses pinned to code** (the core `diagnose`
   method): "X happens because Y in `<file:function>`, causing Z", each with a
   predicted effect per power.
6. **Test the strongest** with a targeted eval (eval-design binding) and record
   the result in an experiment record, refutations included. A refuted lever
   goes in `closed_levers.md` with its numbers.

## Instruments

Run from the optimizer root; **exact flags live in each tool's docstring**.

- `wd.py metrics DIR... --policy NAME:vN`: where the loss is, per power, plus
  rejected orders and exceptions.
- `wd.py seats DIR...`: per-seat center trajectories by year.
- `wd.py costs DIR...`: LLM spend and call counts per seat.
- `webdip_episodes.py`: the loader for new instruments. Persist new analysis in
  `../../instruments/`.
