# webDiplomacy: the strategy of the starter policy

How the starter policy (`players/castlereagh/`) decides what to play, in plain
words, with the file and the setting behind each choice. Read it before you change
the policy, so you know what you are changing.

This file describes a mechanism. It says nothing about how well the mechanism
does against any opponent: that depends on the field you play in, and you measure
it yourself. Your own findings go in [Field knowledge](#field-knowledge), which
ships empty.

For the rules of the game and how it is scored, see [game.md](game.md)
(scoring: [game.md](game.md#scoring)). For the modules, settings and how to
change them, see the policy's
[README](../players/castlereagh/README.md).

## In one paragraph

Every movement phase the policy guesses what each other power will play, sixteen
times over. It then looks for the set of orders for its own units that leaves it
with the most supply centers, on average over those sixteen guesses, if the phase
were adjudicated at once. It looks one phase ahead and no further. Retreats and
builds come from a simpler rule of thumb. In a press game an LLM can negotiate
and can change what the search assumes and what it is allowed to do, but the
search still writes the orders.

## How the search chooses movement orders

The code is `search.py`, `search_moves.py`, `opponent_model.py` and
`evaluation.py`. The settings are in `config.py`.

### Step 1: a value for every province (DumbBot)

The search is built on **DumbBot**, a well-known heuristic Diplomacy bot
(`dumbbot.py`). DumbBot gives every position on the map a value for our power:

- **A center we do not own** is worth more the larger its owner is. A power's
  size is `n² + 4n + 16` for `n` centers, so the centers of big powers attract
  more. The neutral centers count together as one power sized by how many
  neutrals remain.
- **A center we own** is worth defending in proportion to the size of the
  largest other power with a unit next to it.
- These values are spread across the map, so a province near valuable centers
  has value too. In Spring the provinces *next to* a target count most; in
  Autumn the target *itself* counts most, because ownership changes after Autumn.
- Attack counts for more than defense (700 to 300 in Spring, 600 to 400 in
  Autumn).
- A province more of our units can reach is worth more; a province another
  power can reach with several units is worth less.

DumbBot turns these values into orders by sending each unit to its
highest-valued reachable position, sometimes taking the next best when the two
are close, and supporting instead when one of our own units is already going
there or standing there. It chooses with some randomness, so asking it twice can
give two different plans.

### Step 2: guesses at the other powers' orders

`opponent_model.py` builds 16 samples (`SEARCH_OPPONENT_SAMPLES`). Each sample
holds one full set of orders for every other power, made like this for each
power:

1. Take a DumbBot plan for that power.
2. Either **improve it**: try each of its units' other legal orders, one unit
   at a time, and keep a change when it scores better from that power's side
   against DumbBot plans for everyone else. This is the "level 1" opponent
   (`OPP_MODEL_LEVEL = 1`): one step smarter than DumbBot.
3. Or, if the power has looked random so far, replace the plan with **uniformly
   random legal orders**.

Which of 2 and 3 happens is a per-power belief that the policy updates after
every movement phase from the orders that power actually played
(`update_type_beliefs`). An order counts as evidence of competence if DumbBot
would have sampled it, or if it is a plain hold or move, or a support or convoy
of the power's own unit. An order that only a random player would give (a
support of some other power's unit, say) counts the other way. The belief starts
at even odds, so in the first phase about half of each power's samples are
random.

The model has exactly these two kinds of opponent. It holds no picture of who
is allied with whom or who has attacked us.

### Step 3: candidate plans for our own units

`search_moves.py`:

1. **Seeds.** Twelve DumbBot plans for our own power (`SEARCH_SEEDS`). Each is
   scored (step 4) and the best one becomes the starting plan.
2. **Improvement, one unit at a time.** The search goes through our units in
   random order. For each it tries every other legal order, and keeps a change
   only if the plan's score goes up. It repeats for up to six passes
   (`SEARCH_PASSES`) and stops early when a pass changes nothing or the time
   budget (`WEBDIP_SEARCH_BUDGET_S`, 20 seconds) runs out.
3. **Two kinds of joint change.** Some good plans need two units to change
   together, which step 2 alone cannot find. So the search also tries a unit's
   move together with a support for that move from another of our units, and an
   army's convoyed move together with the convoy orders of our fleets on its
   path.

### Step 4: scoring a plan

`evaluation.py` (`score_fast`). For each of the 16 samples, the plan and that
sample's orders are adjudicated together by a fast adjudicator (`fastadj.py`).
The result is scored for our power as:

| Term | Weight | What it counts |
|---|---|---|
| Projected centers | 10 each (`SEARCH_SC_WEIGHT`) | Centers one of our units stands on after the moves, plus centers we own that no other power's unit stands on |
| Position | up to 1 per unit (`SEARCH_POS_WEIGHT`) | The DumbBot value of where each of our units ends, as a share of the best value on the map |
| Dislodged units | −3 each (`SEARCH_DISLODGED_WEIGHT`) | Our units that were dislodged |

The plan's score is the average over the samples. `SEARCH_RISK` (0 by default)
pulls that average toward the worst sample; at 1 the plan is judged by its worst
case alone.

So the search wants, in this order: more centers after this phase, then not
losing units, then standing on provinces DumbBot likes. Position is the only
term that looks past the current phase, and only as far as DumbBot's province
values do.

`SEARCH_OBJECTIVE = "share"` is an alternative that scores the squared-center
share instead of the center count. It is off by default.

## Retreats and builds

Not searched. DumbBot chooses them (`dumbbot.py`, `_retreats` and
`_adjustments`) from the same province values:

- **Retreat:** to the highest-valued legal province not already taken by
  another of our retreating units. A unit with nowhere to go is disbanded.
- **Build:** the legal build (army or fleet, at a free home center) with the
  highest value. In the build phase a home center's value includes an extra
  term for how large the powers next to it are.
- **Remove:** the unit standing on the lowest-valued position goes first.

Near-ties are sometimes broken toward the second choice, as in movement.

## How the press layer can steer the search

In `press` mode, in a press game, an LLM agent is woken during each movement
phase (`press/`). It can send messages and it can commit a **policy**. A policy
does not contain orders for the whole power; it changes the search's inputs:

| Policy field | What it changes in the search |
|---|---|
| `stances` (`ally`) | In each sample, with probability = trust, that power's moves and supports into our provinces become holds (`apply_press`). The power is also modeled as competent, never random. |
| `stances` (`hostile`) | The power is modeled as competent, never random. Nothing else. |
| `trust` | The probability used above and for `expected_orders`. 0.7 when not given. |
| `expected_orders` | In each sample, with probability = trust, that unit plays the named order. |
| `require_orders` | Those units' orders are fixed. The search chooses the others. |
| `forbid_moves_into` | Our orders that move or support into those provinces are never tried. |
| `center_values` | Added to the center count for each center we would take from that power (step 4). 1.0 doubles what such a center is worth; −1.0 makes it worth nothing. |
| `risk` | `SEARCH_RISK` for this search. |

The agent also has tools that run the search without committing (`search`,
`evaluate`, `assess_deal`, `predict`), a notes store, the press log, and a list
of who moved or supported into whose units and centers, taken from the
adjudicated orders. The policy's
[README](../players/castlereagh/README.md#press-harness-castlereaghpress)
has the full list.

### What the default does with that

The shipped press layer is a **neutral harness**. Its system prompt tells the
agent the objective (the best score under the game's scoring rule), how the
tools and the policy work, and that press is untrusted. It gives no style, no
rule for whom to trust, no opening, and no rule for when to keep or break a
promise. What the agent says and commits is whatever the model you upload with
makes of that.

The briefing also names who plays each power, when the game gives names
(`WEBDIP_PLAYERS`, Coworld 0.7.16; see [protocol.md](protocol.md#environment)).
The default only shows the names: it does not look anything up by them, and the
search does not read them. Using them, for example to bring a player's
[opponent profile](../skills/opponent-profile/SKILL.md#who-the-opponent-is-in-a-live-game)
into the briefing, is for your own policy to add.

Two things hold whatever the agent does:

- **The Default search's orders are saved first** each phase. If the agent
  commits nothing, fails or runs out of time, the seat plays exactly what
  `search` mode would have played.
- **Any legal policy is accepted.** The harness does not stop the agent from
  fixing every unit's order, forbidding every province, or trusting a power
  completely.

Retreats, builds and NoPress games never reach the press layer.

## Structural limits

Things the mechanism cannot do as built. Each is from the code, not from a
measurement, and each is a place you could build.

- **One phase ahead.** A plan is scored on the board after this phase's moves.
  The search does not plan a second move, does not look ahead to the retreats or
  builds that follow, and does not set up a later attack except through
  DumbBot's province values.
- **No knowledge of the end year or the scoring rule in the search.** The last
  Autumn is searched like any other Autumn, and a center is worth the same 10
  points whoever owns it and however large we are. Only the press agent is told
  the end year and the rule.
- **Spring and Autumn count centers the same way.** A unit standing on a center
  after Spring is counted as holding it, although ownership changes only after
  Autumn.
- **Two units at most change together.** Plans that need three or more units to
  change at once are found only if the single and paired changes lead there.
  The search starts from one seed, so it can stop at a plan that no single or
  paired change improves.
- **Convoys are approximated.** A convoy counts as a plain move when every fleet
  on its path orders it, and the search proposes one only when all those fleets
  are ours. A convoy that fails because a fleet is dislodged is not modeled.
  DumbBot never orders a convoy, so the opponent samples almost never contain
  one.
- **Opponents are DumbBot-like or random.** There is no model of a particular
  opponent's habits, of alliances between other powers, or of a power that has
  been attacking us. In a no-press game nothing makes the search treat one
  neighbor differently from another, beyond the board itself.
- **Retreats and builds are a rule of thumb.** They are not checked against what
  the other powers may do next.
- **The press agent works one phase at a time.** Each wake starts fresh; its only
  memory is its notes. `assess_deal` values a deal for the current phase only.
  The harness keeps no record of agreements and does not judge whether one was
  kept. There is no press during retreat and build phases.
- **No draw votes.** The policy never votes for a draw.
- **Classic map only.** Province names are a fixed table for the Classic map
  (`dipmap.py`); another map fails at once instead of playing badly.

## Field knowledge

**This section ships empty, on purpose.** What works against a field of
opponents is true of that field on that date. A finding copied from another lab
would read as current fact here and would not be. Add your own entries as your
experiments close.

One entry per finding, newest first:

```
### <the finding, as one plain sentence>                     YYYY-MM-DD
**Field:** which league and which opponent set (the name in `field_sets.json`).
**n:** how many games or seats, and whether they were paired.
**Finding:** what was measured, with the number, its standard error and z.
**Evidence:** the experiment record or batch directory, as a path.
**Limits:** what this does not show (one field, one model, small n).
```

Put a finding here when it is about **how this policy plays or should play**.
Other findings have other homes:

| What | Where |
|---|---|
| Who is in the field now and how each opponent plays | [META.md](../META.md) |
| A change that was tested and gave no result | [open_levers.md](../open_levers.md) |
| A change that was tested and refuted | [closed_levers.md](../closed_levers.md) |
| A practice that has held up across sessions | [best_practices.md](../best_practices.md) |

*(no entries yet)*

## Rebuilding the field picture

Field knowledge starts with knowing who you play against. From the optimizer
root:

1. **Who is seated.** `coworld leagues <league_id> --json` lists the league's
   filler roster as version ids (`filler_policy_version_ids`).
   `python3 games/webdiplomacy/tools/field.py press` (or `gunboat`) lists every
   policy the league's recent rounds seated, entrant or filler, with its name,
   version id and its player as bots see it (the name in `WEBDIP_PLAYERS`), and
   ends with the seating of each round. Use both: the roster
   has no names, and `field.py` sees only the rounds that have run
   ([platform.md](platform.md#leagues-and-the-field)). Standings:
   `coworld results <league_id>`, then `coworld results <div_id>`
   ([game.md](game.md#leagues)).
2. **Name your opponent sets.** Put the version ids into `field_sets.json` as
   dated sets (five seats for a paired A/B, six for a field eval); the file is
   written by hand. Say in each set's `defined` line where it came from. Results
   against two different sets are two different measurements: do not pool them.
3. **How strong each is, and the average score of each power.** Run a field
   eval (`tools/make_request.py field --balanced`, the
   [eval-design binding](../skills/eval-design/SKILL.md)), fetch it, then
   `tools/wd.py metrics DIR --policy NAME:vN` for any seated policy and for the
   average by power.
4. **How each plays.** Replays carry every power's adjudicated orders and public
   press: the [survey](../skills/survey/SKILL.md) and
   [replay-inspection](../skills/replay-inspection/SKILL.md) bindings, and
   `tools/wd.py seats` for center trajectories. Other players' logs are not
   readable.
5. **Write it down, dated,** in [META.md](../META.md) (the optimizer's
   `meta-recon` skill runs this whole pass and keeps the file current).
