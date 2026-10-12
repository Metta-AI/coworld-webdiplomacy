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
parts: kinds of failure to check for in this game, and a procedure for a
problem that is not on the list.

## Before you propose anything

Three reads, every time. `closed_levers.md` alone is not enough: it lists only
what was refuted, not what was tested with no result.

1. **`../../closed_levers.md`, every heading**, not the first screen.
2. **`../../open_levers.md`**: what was tested and gave no result. An entry
   there is a prior on the size of any idea in the same family.
3. **Every record in `../../experiments/`**, whatever its status, newest first
   (the IDE's `/experiments` page lists them). A record just closed may not be
   in either register yet.

Then say, with the proposal, which earlier test is its nearest relative and
what yours changes. If the relative read a small effect, check that your run
could see one of that size (`tools/sizing.py --games N`) and size it
accordingly ([ab binding, "Extending a run"](../ab/SKILL.md#extending-a-run)).

**Two tests with no result in one family: stop turning that knob.** After a
second null in a family, the next step is reading games (below), not a third
dose.

## Failure vocabulary

Kinds of failure a policy in this game can have, and how to detect each.

- **Silent order drops.** Upstream returns HTTP 200 and keeps only the orders
  it accepts. The policy believes it moved; the replay shows it held. Detect:
  nonzero `rejected` in our `decision` lines, or our orders differing from the
  replay's adjudicated orders. Convoys and split coasts have the least obvious
  order format ([game.md](../../docs/game.md#orders)).
- **Invisible degradation.** A broken dependency fails every time while the
  policy keeps playing its fallback, with no error in the score. The common
  case: an LLM model or parameter mismatch at the sidecar makes every call fail
  and the seat plays its search floor. Detect: per-seat `llm_call` statuses; a
  feature's own activation counters.
- **Wrong map knowledge.** An LLM reasons about adjacency from memory and gets
  it wrong. Detect: press or reasoning in our seat log that names a move
  between provinces that do not border (`variant.json` has the adjacency). Fix
  direction: hand the LLM the map.
- **Misplaced trust.** Re-trusting a power that already broke its word,
  letting words restore trust before deeds do, or building trust on our own
  record of promises and not on observed orders against our units and centers.
  Detect: the [press-audit skill](../press-audit/SKILL.md) (who broke which
  promise, and whether we had relied on it).
- **Ignoring the game horizon.** Planning past the end year (negotiating
  "1905 offensives" in a game that ends in 1904), or valuing position over owned
  centers in the final Autumn, when only owned centers score.
- **Over-tuning.** A change that wins against one field or one evaluation and
  loses against the next. Detect: the candidate-alone check, and a re-run
  against the current field. Judge against the field you will meet.
- **The press layer freezes its own units.** A press layer that constrains the
  order choice (orders it pins, provinces it forbids) can leave most of our
  units holding. Detect: `tools/holds.py --policy <ours> --variant classic-press`
  (hold share beside the field at the same power, and split by what was
  committed). A high hold share is a behaviour, not yet a cost: apply the next
  item.
- **A visible oddity that does not go with score.** The step after "we do X
  far more than the field" is "do our seats that do X more score less?", in the
  games already on disk. If they do not, the oddity is a weak hypothesis about
  score however striking it looks, and its test must be sized for a small
  effect.
- **Routing around a cap.** A limit on one field of an LLM's output can move
  the behaviour to another field. Guard the outcome you care about, and
  measure that outcome.

## Procedure for a new problem

**Sketch; to build out.** Use this when the signal does not match a known
failure mode.

1. **Rule out the plumbing.** Apply the ab binding's taint checks: rejected
   orders, exceptions, seats that never played, pods the platform deleted
   mid-game, failing LLM calls, artifact coverage, cancelled, failed or
   timed-out games. A plumbing failure looks like a strategy failure in the
   score.
2. **Locate the loss against par.** Which powers, which years, which phase
   types? Use `wd.py metrics` per power and `wd.py seats` trajectories by year.
   Read the user's replay notes first (`ide/ide annotations`): they are
   evidence, and they say where the user thinks the loss is.
3. **Read the worst games at that spot, before ranking any lever.**
   `tools/seat_rows.py --policy <ours> --as <power> --limit 5` lists them; open
   each at the phase our centres fell (`opponent_profile.py --game … --decisions --versus <ours>`
   for the orders, `tools/seat_log.py --game … --power … --when …` for what our
   seat was told and committed that turn). An aggregate can point at the wrong
   cause, and the games correct it. Read a good game at the same power too,
   and ask whether the "cause" was there as well.
4. **Compare with the alternative.** What else could the policy have done? For
   a policy with a press layer: the orders it would have chosen without press
   against the orders finally played.
5. **Form 2 to 4 mechanistic hypotheses pinned to code** (the core `diagnose`
   method): "X happens because Y in `<file:function>`, causing Z", each with a
   predicted effect per power. For each, say whether the pattern goes with
   score in the games on disk (a count over all games with `tools/holds.py` or
   `tools/board_counts.py`, split by good and bad games), and name its nearest
   earlier test. Games picked for being bad cannot show that a rule helps on
   balance: say so when that is all you have.
6. **Write each hypothesis you offer as a `proposed` experiment record**
   (`skills/experiment/scripts/record.py new`; hypothesis, decision rule and
   expected cost filled, nothing built). `WORKING_CONTEXT.md` gets one line
   that points to it. A hypothesis that lives only in the working context, a
   chat message or an idea card is lost at the next prune, and the IDE cannot
   show it. Tell the user where it is.
7. **Test the strongest** with a targeted eval (eval-design binding) and close
   the record by its rule. A refuted lever goes in `closed_levers.md` with its
   numbers; one with no result goes in `open_levers.md` with its numbers, what
   the run could have seen, and what a next test would need.

## Tools

Run from the optimizer root; **exact flags live in each tool's docstring**.

- `wd.py metrics DIR... --policy NAME:vN`: where the loss is, per power, plus
  rejected orders and exceptions.
- `wd.py seats DIR...`: per-seat center trajectories by year.
- `wd.py costs DIR...`: LLM spend and call counts per seat.
- `wd.py seats DIR... | flag_episodes.py --policy NAME:vN`: the games worth
  opening. `… | year_deltas.py`: where in the game centers are won or lost.
  `… | mine_variance.py`: which measured behaviours go with our own good and
  bad games (hypothesis fuel only).
- `seat_rows.py DIR... --policy NAME [--as POWER] [--versus OTHER] [--limit N]`:
  the games themselves, worst first, one row per seat.
- `seat_log.py DIR... --game ID --power POWER --when A1902`: what our seat
  received, sent, committed and decided that turn (private press: terminal only).
- `holds.py DIR... --policy NAME --variant V`: hold share beside the field and
  what in the committed press policy goes with it.
- `hold_reasons.py DIR... --policy NAME`: each hold as fixed by the agent or left to the
  search, and where the unit stood.
- `press_behaviour.py DIR... --policy NAME`: what the press agent fixes, commits and sends, per
  version (orders fixed, every unit fixed, stances, messages per phase).
- `centre_losses.py DIR... --policy NAME [--going-in] [--rows]`: every supply centre we lost:
  which one, who took it, the stance and trust we held toward them beforehand and whether
  we were talking; and how often a power the agent called an ally took a centre from us,
  beside neutral and hostile powers.
- `wake_bench.py`: recorded phase-start decisions replayed under another prompt or setting,
  for a read of the agent's behaviour in minutes before a hosted run (a screen, never a
  score; needs a working LLM key).
- `board_counts.py DIR... --policy NAME --as POWER --order "…" --owns PROV`: a
  claim about orders or centres counted over every game, the field beside it.
- `webdip_episodes.py`: the loader for new instruments. Persist new analysis in
  `../../instruments/`, after checking that the tools above do not already
  print it.
