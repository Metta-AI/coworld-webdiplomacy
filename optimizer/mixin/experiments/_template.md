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
cost: <what a run would spend, e.g. 28 press games, 62 credits by the platform's estimate, about 70 minutes>
artifacts: []           # other folders under .runtime/artifacts to read with this record's own; see the note below
---

# <Experiment title>

*(A record is `proposed` from the moment the idea is written down: hypothesis, decision rule
and `cost` filled, `candidate: n/a`, nothing built. The IDE's Experiments page lists it with
a "Run this" request. `tools/run_ab.py` refuses to launch while the front matter still has a
`<...>` placeholder.)*

*(A survey or a baseline run tests nothing, but its games still need a record so their batch
ids and cost are kept. Write `hypothesis: "Not a test: a survey of <what>"`, put what you will
report and what would make you distrust the run into `decision_rule`, `candidate: n/a`, and
close it `inconclusive` with the numbers in "Result": the status list has no "read" value.)*

*(Where the result is read from: this record's own folder, `.runtime/artifacts/<record id>`,
which is where `tools/run_ab.py` fetches, and it is always read. `artifacts:` lists any other
folders under `.runtime/artifacts` to read with it, by name, in the order to read them: an
earlier record's folder when the decision rule pools its games with this record's, or a
folder you fetched into by hand. `tools/run_ab.py` and the Experiments page use this one
rule, and neither reads a folder named only in the text below.)*

## Context

What was observed that motivated this, with links (META.md entries, survey
findings, replay evidence). Confirm `closed_levers.md`, `open_levers.md` and the earlier
records in `experiments/` were checked.

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
  numbers; if inconclusive, to `open_levers.md`. If confirmed, what ships and what the rollback is.
- Status transitions are validated by the seed's
  `skills/experiment/scripts/record.py` once this lab is installed in an
  optimizer; refuted records are never deleted.
