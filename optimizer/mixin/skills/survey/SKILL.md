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
  an `exception`, seats that never played (`no_decisions`), seats whose pod the
  platform deleted mid-game (`pod_deleted`), failing LLM seats. The `taint:`
  line of `wd.py metrics` counts each. Infrastructure problems go here, not in
  the score table. Report `http errors` from the `telemetry` line when it is
  not zero; "no errors" means every counter on that line is zero.
- **Which games the headline is from.** Say it with the number, every time:
  alone runs or all games (`matchups.py --alone` leaves paired games out),
  which sources (league, experience requests), how many games, how many
  dropped as tainted. The same policy reads differently raw and against par,
  and in alone runs and in all runs; unlabelled, those look like different
  headlines. Pick the alone view for "how good is it" and name it.
- **Field par by power** for the batch, so a reader sees whether the field
  itself looked unusual.

A batch with fewer than about 16 seats per power is directional only. Say so.

## Structure worth surfacing

- Which powers we gain or lose on relative to par. A policy can be fine at
  one power and broken at another.
- When our trajectory falls behind: the center count by year
  (`wd.py seats`) separates opening, midgame and endgame losses.
- Who wins the games we lose: one opponent soloing often, or a field-wide
  pattern.

## What makes an episode interesting

Flag cheaply from results and seat rows, rarer flags first:

| Flag | How to detect |
|---|---|
| Our seat crashed or dropped orders | `exception` events or nonzero `rejected` in our seat log, or a seat log with no `decision` line (taint `no_decisions`) |
| Our pod was deleted mid-game | taint `pod_deleted` in the seat's `wd.py seats` row: the seat held from then on. `flag_episodes.py` lists it under "crash or dropped orders" |
| Failing LLM seat | at least half of the `llm_call`s failed in our seat log (`wd.py metrics` shows it as taint) |
| Opponent solo | `outcome == "won"` and the winner is not us |
| Our power eliminated early | our center count reaches 0 before the last two years |
| A big swing within one year | our centers drop (a stab or collapse) or jump by 3 or more between consecutive years |
| Our best and worst game per power | max and min score vs par per power |

Write one specific reason per flagged episode: power, year, what happened, the
number. Point the human at the replay with the hosted viewer
(`coworld replay-open <episode-request-id> --hosted`), or in the IDE at
`/replays/<episode id>?seat=<slot>&turn=T` (T is 2 × (year − 1901), plus 1 for
Autumn; a phase number counted by hand is wrong in any game with a retreat).

**Check a line before it goes on a card.** A card stays as posted. What you
did not look at is left out or marked "not checked".

**A count from a tool nobody read is quoted as that.** Give a number such as
the press audit's "betrayed" count with "by the tool's count, flags not
read", or read the flags first (the press-audit skill says how).

## Tooling

Run from the optimizer root. **Exact flags live in each tool's docstring**; they
may shift slightly.

- `python3 games/webdiplomacy/tools/wd.py metrics DIR... --policy NAME:vN [--json]`:
  the per-power overview, coverage and telemetry.
- `python3 games/webdiplomacy/tools/wd.py seats DIR... [--policy NAME:vN]`: one
  JSON line per seat with its center trajectory by year. Pipe it into the
  two tools below, or into your own instrument in `../../instruments/`.
- `… wd.py seats DIR... | python3 games/webdiplomacy/tools/flag_episodes.py --policy NAME:vN`:
  a first cut of the table above (crashes, opponent solos, early eliminations,
  swings, best and worst games by raw score).
- `… wd.py seats DIR... | python3 games/webdiplomacy/tools/year_deltas.py`: mean
  center change per game year, by policy.
- `python3 games/webdiplomacy/tools/wd.py costs DIR...`: LLM spend per seat.
- `python3 games/webdiplomacy/tools/seat_rows.py DIR... --policy NAME [--as POWER] [--limit N]`:
  the games themselves, worst score first, with centres by year, taint and
  first targets: "our worst games as Austria" without a script.
- `python3 games/webdiplomacy/tools/batches.py DIR...`: what each batch cost and
  how long it took, from the episode rows.
