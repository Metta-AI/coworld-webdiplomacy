# webDiplomacy: the league field

Who the league's filler opponents are. Read 2026-10-10 from the fillers' own
seat logs; the fillers can change, so check
`python3 games/webdiplomacy/tools/field.py gunboat` before relying on
the roster. The dated live picture belongs in [META.md](../META.md); this file
is the slower-moving reference behind it.

**How the designs are known.** Every filler prints a one-line description of
itself in the `start` event of its seat log. Those logs are readable only by
the player that owns the fillers (James Botts, as of this date). Another
player sees only replays and cannot read these lines, which is why they are
copied here.

## Gunboat league (`classic-gunboat`)

| Filler | Its own description | What that means in this code base |
|---|---|---|
| `webdip-rasputin:v1` | "Unkillable, unreadable: Kissinger's mind, but rolls the dice among its best plans." | The search with random choice among near-best plans ("mixed selection", dropped from the reference policy) |
| `webdip-kissinger:v2` | "Assumes you are clever too: best-responds to opponents who best-respond." | The same search as the reference policy (level-1 opponent model), in an older build |
| `webdip-napoleon:v2` | "Thinks one season ahead: spring moves judged by the autumn they set up." | Rollouts: a closed lever (`closed_levers.md`) |
| `webdip-bismarck:v2` | "Blood and iron: attack weights up, losses shrugged off." | Aggressive heuristic weights |
| `webdip-talleyrand:v2` | "Plays the scoreboard, not the map: maximizes its SC-squared share." | `SEARCH_OBJECTIVE=share`; it also hits the search time budget |
| `webdip-metternich:v2` | "Balance of power: never lose a unit, keep the leader small." | Defensive: heavy penalty on losing units |
| `webdip-fabius:v1` | "Cunctator: wins by not losing. Plans for the worst opponent sample, never gives ground." | Risk aversion: a closed lever |
| `webdip-blucher:v1` | "Marshal Forwards. Bred by evolution (g2-0ed5), not designed: always attacking." | A product of the evolutionary tuning run (a closed lever) |
| `webdip-calhamer:v1` | "Classic DumbBot, frozen as it was first uploaded. The honest yardstick." | The plain heuristic, no search |
| `webdiplomacy-random:v1` | (prints no description) | Random legal orders |
| `coworld-smoke/…:v1` | (not readable) | The platform's smoke-test seat |

## Press league (`classic-press`)

Seen in the league's two rounds to date. Each LLM seat names its model in a
`press_start` event.

| Filler | Kind | Model |
|---|---|---|
| `webdip-kissinger:v2` | Search, silent (seated twice in round 2) | none |
| `webdip-metternich-press:v5` | LLM press (seated twice in round 2) | `google/gemini-3.5-flash-lite` |
| `webdip-talleyrand-press:v5` | LLM press | `openai/gpt-6-luna` |
| `webdip-machiavelli-press:v2` | LLM press | `z-ai/glm-5.3-flash` |

Strength in the press field as the prior lab measured it is in
[strategy.md](strategy.md).

## What this says about levers

Several fillers are ideas this code base has already tried (rollouts, the share
objective, defensive and aggressive weights, risk aversion, evolutionary
tuning); check `closed_levers.md` before re-testing what a filler already does.
Measure the fillers' current strength yourself (`tools/wd.py metrics` on a
field batch) and record it in `META.md`.
