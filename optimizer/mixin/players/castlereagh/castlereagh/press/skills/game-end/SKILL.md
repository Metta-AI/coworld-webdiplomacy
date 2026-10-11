---
name: game-end
description: How the end year and the scoring rule work, and what the search knows about them.
---
# The end of the game and the score

## When the game ends

The briefing states the end year when the game has one. The game ends after the autumn
movement phase of that year and its retreats. The score uses the centres owned at that
point; no later move is played, so builds after the last autumn change nothing. The
briefing also counts the movement phases that remain, this one included.

A supply centre changes owner only after an **autumn** phase: a unit standing on a centre
after spring does not yet own it. In the last year, only a unit that is on a centre when
the autumn moves and retreats are done takes it.

A game can also end earlier: with a solo win at 18 centres, or with a draw when every
surviving power votes for one (this harness has no tool for draw votes).

## How the score is computed

The briefing names the rule:

| Rule | Your score if nobody wins outright |
| --- | --- |
| `sum_of_squares` | Your centres squared, divided by the sum of every survivor's centres squared. |
| `supply_centers` | Your centres divided by all survivors' centres. |
| `draw_size` | An equal share for every survivor. |

Under every rule a solo winner scores 1 and everyone else 0, an eliminated power scores 0,
and the scores of one game sum to 1.

Worked example for `sum_of_squares`: you hold 8 centres and the other survivors hold
10, 7, 5 and 4. Squares: 64, 100, 49, 25, 16; total 254. Your score is 64 / 254 = 0.25.

## What the search knows about this

- The search values your projected centre count after the current phase. It does not
  compute the score rule, and it does not know the end year.
- It counts a centre your unit would stand on as yours in spring as well as in autumn.
- `center_values` and `risk` are the policy fields that change what the search values;
  the harness rules describe them.
