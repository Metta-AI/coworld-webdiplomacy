# webDiplomacy: strategy

Two parts. First, a general Diplomacy primer from human play, **not verified
against any field of bots**: treat each point as a hypothesis. Second, lessons a
prior lab measured, each with its date and numbers. This file deliberately says
nothing about who is in the league now or how strong each opponent is: the
field changes, and that picture belongs in `META.md`, which you build with
meta-recon ([how](#rebuilding-the-field-picture)).

## Part 1: a general primer (not verified against a field of bots)

**What scoring rewards.** A game that reaches the year cap is scored by
SC² / total SC² over survivors ([game.md](game.md#scoring)). So:

- Being the largest power is worth far more than being one of several mid-sized
  ones. A small, safe position is worth little.
- Survival still matters: an eliminated power scores 0.
- Only **owned centers at the end** count. In the last Autumn, a center taken is
  worth more than any position for next year, because there is no next year.

**Tactics.**

- Moves of equal strength bounce. A supported move beats an unsupported hold.
- A support is cut when the supporting unit is attacked (except by the unit it
  is supporting against). Attacking a supporter is often the cheapest defense.
- Convoys need every fleet in the chain to hold its position.
- Leaving a home center empty in Autumn invites a capture that also denies you a
  build.

**Openings and position (human lore).**

- Corner powers (England, Turkey) are traditionally easier to defend; central
  powers (Germany, Austria, Italy) can be attacked from many sides.
- Common human alliances: England-France-Germany pairs in the west, Austria-Italy,
  and Russia-Turkey ("the Juggernaut").
- The 12 neutral centers (Belgium, Holland, Denmark, Sweden, Norway, Spain,
  Portugal, Tunis, Serbia, Rumania, Bulgaria, Greece; verified against upstream
  `variants/Classic/install.php`) decide the first builds.

Note: do not assume human opening theory transfers to a field of bots. In one
measured field (2026-10, Part 2) England was the weakest power and France the
strongest, the reverse of the corner-power lore. Measure power par in your own
field.

**Press (human lore).**

- Agreements are not binding; the adjudicator enforces only orders.
- Trust deeds over words. A power that attacked you once is likely to again.
- Timing a betrayal matters: a stab is worth it when it gains centers you can
  keep and the victim cannot retaliate in time.

## Part 2: lessons from a measured field

Measured by a prior webDiplomacy lab in 2026-10. The numbers are evidence for
the lessons, not a description of today's field: re-measure before relying on
any of them.

### Powers are far from equal

Mean score per seat by power, over 1,238 field seats in one press field
(2026-10-08 to 10-09; parity is 1/7 = 0.143):

| Power | France | Turkey | Italy | Germany | Russia | Austria | England |
|---|---|---|---|---|---|---|---|
| Mean score | 0.290 | 0.191 | 0.119 | 0.114 | 0.114 | 0.099 | 0.090 |

France scored about three times England. Any comparison that does not hold the
power fixed mostly measures which powers a policy happened to draw. The exact
par depends on who is playing, so compute it from your own batches
(`tools/wd.py metrics`).

### What that field showed about press

- **The best press seat lied.** The highest-scoring LLM seat was a prompt that
  deceives, on a stronger model; honest and cautious prompts scored lower.
- No press change reached a verdict at 16 games per arm: press is under-measured,
  not settled.
- Trending positive but unproven: giving the LLM the map connectivity list, and
  stronger models for the same prompt.
- **The prior lab's press bot re-trusted powers that betrayed it.** After a first breach or
  attack while trusted, it went back to trusting the same power 94 times in 46
  relationships over 100 games.
- A blunt fix, permanently marking a betrayer, scored 0.078 against 0.158 for
  its base. See `closed_levers.md`.

### The field depends on who is in it

The same bot can rank first or last depending on its opponents. The reference
search scored 0.38 per game against a field of simple heuristic bots, well
below plain search's 0.55 to 0.75 in the same local setup, because its opponent
model expects smarter opponents. Against search-bot fields it won. **Judge a
policy against the field it will meet.**

## Rebuilding the field picture

Nothing here names the current opponents, on purpose. To see the field as it
is today, from the optimizer root:

1. **Who is seated.** `python3 games/webdiplomacy/tools/field.py press` (or
   `gunboat`) lists every policy in the league's recent rounds, entrant or
   filler, with its version id. Standings: `coworld results <league_id>`, then
   `coworld results <div_id>` ([game.md](game.md#leagues)).
2. **Name your opponent sets.** Put the version ids into `field_sets.json` as
   dated sets (five seats for a paired A/B, six for a field eval). Copy a real
   seating: `field.py` ends with "Seating by round", and a league that seats one
   filler twice is a different field from one that seats it once. A workable
   rule: the six-seat set is the most recent round's seating minus the one
   entrant seat you would take; the five-seat set drops one more seat (say
   which, and why, in the set's `defined` line). "Entrant" in that table is as
   of the round; check the standings to see who is still entered.
3. **How strong each is, and power par.** Run a field eval
   (`tools/make_request.py field --balanced`, the
   [eval-design binding](../skills/eval-design/SKILL.md)), fetch it, then
   `tools/wd.py metrics DIR --policy NAME:vN` for any seated policy and for
   par by power. Any batch against the set will do: the same-code check that
   your first A/B needs anyway seats every field policy, so it doubles as the
   field eval.
4. **How each plays** (optional on a first pass; steps 1 to 3 and 5 are enough
   to start measuring). Replays carry every power's adjudicated orders and
   public press: the [survey](../skills/survey/SKILL.md) and
   [replay-inspection](../skills/replay-inspection/SKILL.md) bindings, and
   `tools/wd.py seats` for center trajectories. Rivals' logs are not readable.
5. **Write it down, dated,** in `META.md` (the optimizer's `meta-recon` skill
   runs this whole pass and keeps the file current).
