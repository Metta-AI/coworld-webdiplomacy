---
name: webdiplomacy-survey
binding: survey
description: >
  webDiplomacy binding for the core survey skill: what a batch overview
  shows for this game and what makes an episode interesting.
---

# Survey binding — webDiplomacy

The core `survey` skill carries the process: aggregate, decompose, flag,
narrate. This binding says what those mean in webDiplomacy. Metric definitions
are in the [ab binding](../ab/SKILL.md#metrics-that-matter).

## The overview table

One table per policy version, **one row per power**, plus a pooled row:

| Column | Source |
|---|---|
| Games (seats) | count of our seats at that power |
| Score vs par | our score minus the same-batch field mean at that power |
| Raw score | `results.json` `scores[slot]` |
| Final centers | `results.json` `members[].supplyCenterNo` |
| Survival rate | final centers > 0 |
| Solo rate | our solo; opponent solo listed separately |

Under it, one line each:

- **Outcome and reason mix:** counts of `drawn` / `won` / `cancelled` and of
  `end_year` / `episode_timeout` / other.
- **Health:** artifact coverage, episodes with nonzero `rejected`, episodes with
  an `exception`, failing LLM seats. Infrastructure problems go here, not in the
  score table.
- **Field par by power** for the batch, so a reader sees whether the field
  itself looked unusual.

A batch with fewer than about 16 seats per power is directional only. Say so.

## Structure worth surfacing

- Which powers we gain or lose on relative to par. A policy that is fine as
  France and broken as Austria is a common shape.
- When our trajectory falls behind: the center count by year
  (`wd.py seats`) separates opening, midgame and endgame losses.
- Who wins the games we lose: one opponent soloing often, or a field-wide
  pattern.

## What makes an episode interesting

Flag cheaply from results and seat rows, rarer flags first:

| Flag | How to detect |
|---|---|
| Our seat crashed or dropped orders | `exception` events or nonzero `rejected` in our seat log |
| Failing LLM seat | every `llm_call` failed in our seat log |
| Opponent solo | `outcome == "won"` and the winner is not us |
| Our power eliminated early | our center count reaches 0 before the last two years |
| A big swing within one year | our centers drop (a stab or collapse) or jump by 3 or more between consecutive years |
| Our best and worst game per power | max and min score vs par per power |

Write one specific reason per flagged episode: power, year, what happened, the
number. Point the human at the replay with the hosted viewer
(`coworld replay-open <episode-request-id> --hosted`).

## Tooling

Run from the optimizer root. **Exact flags live in each tool's docstring**; they
may shift slightly.

- `python3 games/webdiplomacy/tools/wd.py metrics DIR... --policy NAME:vN [--json]`:
  the per-power overview, coverage and telemetry.
- `python3 games/webdiplomacy/tools/wd.py seats DIR... [--policy NAME:vN]`: one
  JSON line per seat with its center trajectory by year. Feed it to ad-hoc
  flags or to an instrument in `../../instruments/`.
- `python3 games/webdiplomacy/tools/wd.py costs DIR...`: LLM spend per seat.
