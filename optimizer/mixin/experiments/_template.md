---
id: YYYY-MM-DD-short-slug
policy: <policy name>
baseline: <policy:vN>
candidate: <policy:vM or "n/a" until built>
status: proposed        # proposed | running | confirmed | refuted | inconclusive
hypothesis: >
  One sentence: X happens because Y (at <code location>), causing Z.
decision_rule: >
  Pre-committed: ship iff <metric> moves <threshold> at <significance>
  with no significant regression elsewhere. Written BEFORE the run.
evals: []               # batch ids, filled as they run
---

# <Experiment title>

## Context

What was observed that motivated this, with links (META.md entries, survey
findings, replay evidence). Confirm `closed_levers.md` was checked.

## Predictions — pre-registered

- **If TRUE we expect:** …
- **If FALSE we expect:** …

*(These must differ. Never run an experiment whose outcome couldn't change
your mind.)*

## Design

The instrument (re-analysis of existing data / a designed eval / new
instrumentation), the arms, the N and why it's adequate, and the adversarial
critique: what could mask the effect, what confounds exist, what would make
this result untrustworthy.

## Result

What the eval showed, decomposed and taint-filtered. Numbers with N and
uncertainty.

## Verdict

Read against the pre-committed decision rule — no post-hoc goalposts.
- **confirmed / refuted / inconclusive**, and why.
- What closes: if refuted, add the lever to `closed_levers.md` with the
  numbers. If confirmed, what ships and what the rollback is.
- Status transitions are validated by the seed's
  `skills/experiment/scripts/record.py` once this lab is installed in an
  optimizer; refuted records are never deleted.
