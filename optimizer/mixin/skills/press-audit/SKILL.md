---
name: webdiplomacy-press-audit
description: >
  Check what powers said in a press game against what they then ordered: find
  every promise, threat, request and statement in the press our seat saw, and
  mark each kept or broken, true or false, and whether we relied on it. Use
  when a press game went badly and you need to know who lied, when we were
  betrayed, when we distrusted someone who was honest, or whether our own bot
  kept its word; and before changing how the policy decides whom to trust.
---

# Press audit — webDiplomacy

This skill
turns one game's press into a checked record: **what was said, what was done,
and how we stood**. It answers four questions that the score cannot:

- Who lied to us, and how often did each power's word hold?
- Where did we rely on a promise and get betrayed?
- Where did we doubt a promise that was kept (a missed alliance)?
- Did our own bot keep its word?

It works on **one of our seats in one game**. Only our own seat's private press
is readable; other powers' private talk with each other is not in our data.

## How it divides the work

| Step | Who | What |
|---|---|---|
| 1. Extract | `tools/press_audit.py extract` | `ledger.json`: every message our seat saw, every movement phase's adjudicated orders and board, and our policy's logged beliefs. `annotate.json`: the same messages with each turn's starting board and **no orders or results**. An empty `claims.json` |
| 2. Annotate | **an agent** (a sub-agent per game) | Reads `annotate.json` only. Fills `claims.json`: for each message, the claims it makes, in a fixed vocabulary |
| 3. Verify | `tools/press_audit.py verify` | `audit.json`: every claim checked **by code** against the orders |
| 4. Report | `tools/press_audit.py report` | `audit.html`: one page, turn by turn, said beside done |

The split matters. Reading language is a job for a model; deciding whether an
order was given is a job for code. **The annotator records what was said. It
never decides whether it came true.**

## Method

From the optimizer root. `L=games/webdiplomacy`, `EP` is one fetched or local
episode directory, `OUT=$L/.runtime/press/<episode id>`.

```sh
python3 $L/tools/press_audit.py extract $EP --policy <policy>:vN --out $OUT --by-year   # --slot N if we hold two seats
#   ... annotate $OUT/claims.json (below) ...
python3 $L/tools/press_audit.py check $OUT         # the annotator's format check: no verdicts shown
python3 $L/tools/press_audit.py verify $OUT
python3 $L/tools/press_audit.py report $OUT        # prints the path of audit.html
```

`verify` refuses a `claims.json` that skips a message, breaks the format, or
has a `quote` that is not in its message, and names the entry. Fix that entry
and run it again.

`annotate.json` for a full game is longer than an agent can take in one read
(about 2,000 lines for 100 messages; a full game has 230 to 300). `--by-year`
also writes the same content as `annotate-1901.json`, `annotate-1902.json`,
…, one game year a file; `extract` lists them under `annotate_by_year`. The
annotator reads those in order. `claims.json` stays one file for the game.

**Choosing the games.** An audit costs a sub-agent about ten minutes a game, so
pick on purpose: `python3 $L/tools/seat_rows.py $L/.runtime/artifacts --policy
<policy> --variant classic-press --as <power> --limit 3` lists our worst games
at a power (drop `--limit` and read from the bottom for the best), with the
episode ids `extract` needs. Audit a good game beside a bad one at the same
power. `extract` keeps an existing `claims.json` ("use --force to start it
again"): pass `--force` only when you mean to throw the annotation away, for
example after the tool's rules changed.

### Annotating: use a sub-agent per game

Annotating one full `classic-press` game of 230 to 300 messages took a
sub-agent about 10 minutes and 160,000 to 200,000 tokens (2026-10-10/11);
`extract`, `verify` and `report` add about a minute. **Give each game to its own
sub-agent** (several games: several sub-agents at once). The reading then stays
out of your own context, and each game is read in one pass by an agent that
holds the whole conversation. Give the sub-agent this brief, with the paths
filled in:

> Read `<OUT>/annotate-1901.json`, then `annotate-1902.json`, and so on to
> the last year, every file in full (together they are `<OUT>/annotate.json`,
> which is too long for one read). They hold one Diplomacy game seen from
> `<our_power>`'s seat, turn by turn: the board at the start of each movement
> turn (`units_at_start`, `centres_at_start`) and the press that turn
> (`messages`: sent by us, `direction: out`, or received, `in`). Work through
> the turns in order. Fill in `<OUT>/claims.json`: for every message id, the
> list of claims that message makes. Follow "The claim vocabulary" in
> `games/webdiplomacy/skills/press-audit/SKILL.md` exactly. Record only what
> the message says, and do not mark anything true or false: code does that.
> **Do not open `ledger.json`, `audit.json` or `audit.html`, or the episode's
> replay**: they show how each turn came out, and your reading must not depend
> on that. Use the starting boards only to resolve references ("my fleet",
> "your army in Warsaw", "the Baltic") to powers and provinces. When you are
> done, run `python3 games/webdiplomacy/tools/press_audit.py check <OUT>` and
> fix every format error it reports until it prints `ok` (`check` tests the
> format and shows no verdicts; do not run `verify` or `report`). Report how
> many messages had claims, how many claims use `replaces` and `to`, and which
> claims you marked unverifiable.

Then read `verify`'s summary yourself and spot-check a few claims in
`audit.html` against their messages before you rely on the numbers. Check the
flagged ones first: for each `betrayed`, read the evidence line beside the
message and ask "was this promise made to us, did they choose to break it, and
had anything been said since?".

**How far to trust the flags.** A flag can be a false alarm. The kinds: the
plan was changed in the open by a later message before the orders; the letter
was broken but nobody was hurt or misled; the annotator read a forecast, a
boast or an offer as a promise; our logged distrust did not match what we did;
a kept promise that could not have been broken, or that sat beside an attack on
us; the order was given and bounced; the other side broke a mutual deal first;
the wrong turn was checked; the words were about a third power. `verify`
decides most of these by code (see "Reading the result") and the rules below
cover the rest. Still read a flag before you act on it.

**Read the flags, then also read the turn we lost.** Two checks the counts
cannot make for you:

- *A flagged count nobody read is not a finding.* Quote a count you did not
  check only with "by the tool's count, not read" beside it.
- *The lie that decided the game may not be flagged at all.* A broken promise
  is `betrayed` only when our policy's log shows it relied on the speaker that
  turn. When the log holds no stance toward that power for the turn, the claim
  lands in `false_no_stance` and is not flagged, though our orders show we went
  along with it. So: find the turn our centres fell (`opponent_profile.py --game … --powers`),
  and read every claim made to us in that turn and the one before, whatever
  its category. `tools/seat_log.py --game … --power … --when …` shows what our
  seat committed in reply.

**The annotator is kept blind to results.** `annotate.json` has no orders and
no outcomes. One leak remains: the next turn's starting board shows where units
ended up.

### The claim vocabulary

One message can make several claims, or none (`[]`: greetings, small talk,
questions, vague goodwill). Split a message into its separate commitments.

```json
{"kind": "promise", "quote": "I keep PRU/SIL quiet",
 "commitment": [{"not": {"p": "moves_to", "power": "GERMANY", "province": "PRU"}},
                {"not": {"p": "moves_to", "power": "GERMANY", "province": "SIL"}}]}
```

**The speaker is always the message's sender**, and it is the sender's word
that gets weighed. The powers inside the predicates say whose orders decide it.

Optional fields on any claim:

| Field | Meaning |
|---|---|
| `"to": "FRANCE"` | Whom the promise was made to, when that is **not** the message's recipient. A private "as agreed with Austria, I stay out of Greece" said to us is `"to": "AUSTRIA"`; a public "we have agreed a DMZ in Burgundy with France" is `"to": "FRANCE"`. Left out, a private claim is to the recipient and a public one to everyone. A promise made to someone else is never counted as a betrayal of us |
| `"replaces": ["prv-82#1"]` | This claim takes the place of an earlier claim **by the same sender**: the plan changed, or was called off. `"prv-82#1"` is the first claim of message `prv-82`; `"prv-82"` is all of its claims. The earlier claim then stops at the turn before this message's turn. See "A changed plan" below |
| `"context": "to prv-209: hold VIE, stay out of TRI"` | Your own note on what the words refer to. `quote` holds only the message's own words |
| `"turns": [3, 4]` | First and last turn covered; see "Turns" below |

| Kind | The message says | Verdicts |
|---|---|---|
| `promise` | The sender will or will not do something: "I will X", "I won't X", "I'll X if you Y". Also the sender announcing its own order for this turn ("A MAR is bound for Spain"), and a declared intent to act ("we will retake Trieste") | kept, broken, released (condition not met) |
| `threat` | "If you X, I will Y", "Don't X or I'll Y". `condition` is X, `commitment` is Y. A threat always has a condition | carried out, bluff, not triggered |
| `statement` | The sender asserts a fact, about anyone: "thanks for keeping SIL quiet", "France is being dislodged in RUH", "you hold 9 centres", "Austria is pressing TRI this turn" | true, false |
| `request` | The sender asks the addressee to do or not do something: "please keep out of X", "support me into Y". Counted against the power asked, not the sender. In a public message add `"asked": "<POWER>"` | complied, refused |
| `proposal` | An offer not yet agreed: "Austria proposes a DMZ in Galicia", "shall we split it: KIE mine, DEN yours?". `commitment` is the sender's own side. It does not count for or against anyone's honesty | they did their part, they did not |

Rules that keep annotations checkable:

- **A deal is two claims.** An agreed "DMZ in Galicia" from Austria to us is a
  `promise` (Austria stays out of GAL) and a `request` (we stay out of GAL). If
  it is only being offered, it is a `proposal` and a `request`.
- **Promise or proposal.** A flat "I will X" is a `promise`, also inside a
  trade ("please keep out of TYR; I will stay out of TRI"): it is the sender's
  word. Use `proposal` when the sender frames its own side as an offer
  awaiting an answer ("I propose", "shall we", "let us", "I suggest",
  "confirm and I'll commit", "coordinate?", "agreed in principle"), or makes it
  depend on the other side accepting.
- **A bare "Agreed" takes the terms of the message it answers.** Copy that
  message's terms as the sender's `promise`. The `quote` is the word itself
  ("Agreed."); the terms go in `context` ("to prv-209: hold VIE, stay out of
  TRI").
- **Soft verbs.** "I can keep…", "I am prepared to…" said as part of settled
  terms are promises; said as an opening offer they are proposals. "I trust you
  will…" is a request.
- **A changed plan.** Powers revise a turn's plan many times before the orders
  go in: "change of plan: NTH supports NWY instead", "my BUR support for BEL is
  off", "final orders: …". Record the new terms on the message that states
  them, and name the earlier claims they take the place of in `replaces`. Do
  this for a withdrawal too: "I can no longer support you into BEL" is a
  `promise` of `{"not": {"p": "supports", ...}}` that `replaces` the promised
  support. Only replace what the new message really changes: a plan for the
  same unit, the same province, or the same deal. A new message that merely
  adds something replaces nothing. The details:
  - **A "final orders" list replaces the turn's earlier plan.** "Final orders:
    RUH takes BUR with GAS and PAR support, fleets hold" takes the place of
    every earlier claim by that sender to that party about those units for
    that turn. So does "I can't do X this turn; instead …" and an "Agreed" to a
    change the other side asked for.
  - **The party a promise was made to can let it go.** "No need to support me
    into BEL after all", "let us postpone the GRE attack to spring": that
    party's claim, said to the promiser, may name the promiser's claim in
    `replaces`. No other power's claim can be replaced.
  - **Notice goes to the same party.** A replacement counts only when the new
    message is to the power the earlier claim was made to. "No move at HOL from
    me", told to France, does not end "I move F NTH - HOL", told to Germany:
    leave both, the contradiction is the finding. (The code ignores a
    `replaces` across recipients.)
  - A replacement in the same turn ends the earlier claim entirely; in a later
    turn it ends it from that turn on, and the earlier turns are still checked.
  - You may replace your own earlier `request` or `proposal` the same way ("no
    PIC pin needed after all").
  - A calling-off that states nothing new ("all agreements are void", "the
    truce is dead", "go ahead and take BUL") still needs a claim to carry
    `replaces`: a `promise` with `[{"p": "unverifiable", "why": "withdrawal"}]`.
    A `proposal` may carry `replaces` too.
  - A proposal that the same sender later states flatly ("Confirmed: I hold
    VIE") is a new `promise` on the later message; it replaces nothing.
  - The same plan told to a second power is a separate claim, to that power.
- **Check your `replaces` before you finish.** Go through each turn once more,
  one pair of powers at a time, reading their messages in order. Wherever a
  later message changes what an earlier one said about that turn, the later
  claim must carry `replaces`. This is the most common miss.
- **Describing is not ordering.** "BUL is covered by CON", "my BUL, which I
  hold with support", "pressure the North Sea", "contain England", "my SER
  holds watch", "I'll back you against Turkey next year" name no order. Leave
  them out or mark them `unverifiable`. Encode an order only when a unit and
  what it will do are both clear.
- **An aside is not a separate promise.** A detail inside a larger offer ("my
  fleet stays out of the Channel (it goes to Spain)") is one claim: the
  commitment the other side cares about (stay out of ENG). "Nothing else
  moves" covers the front under discussion, not every unit the sender owns.
- **Always record both halves of a deal in the same message.** "NWY is mine,
  STP and FIN are yours" is a `promise` (we stay out of STP, FIN) and a
  `request` (they stay out of NWY), even when the request is only implied.
  The code releases a promise once the other side has broken its half in an
  earlier turn, and it can only see that half as a `request` beside the
  promise.
- **What is not a claim.** An explicit refusal to commit ("I cannot promise to
  leave Trieste"); a question; a hedged guess about another power's coming
  orders ("Italy looks set to move west", "your F ENG is aimed at BRE", "I
  expect F BEL to head for PIC", "your attack will bounce"); defiance or a
  boast aimed at an enemy ("SEV is mine and it holds", "your fleet dies on that
  rock"); a threat whose consequence names no order ("that means war", "our
  pact is void"); a courtesy about the addressee's past conduct that names no
  order ("your restraint has been noted"). Leave them out.
- **"I will not attack you"** is `{"not": {"p": "attacks", "power": <sender>,
  "target": <addressee>}}`. When the words are narrower, narrow it: "your
  centres" is `"what": "centre"`; "my fleet in Albania stays peaceful" is
  `"unit": "ALB"`; "leave RUM and SER alone" is `"provinces": ["RUM", "SER"]`.
- **`holds` or an exact order.** `holds` is true for any order that keeps the
  unit in place, including a support. Use `{"p": "order", ...}` only when the
  message writes the order out.
- **"Hold" often means "keep".** "I hold NWY and STP against Russia", "we hold
  BUR and PIC", "BEL stays mine" are about keeping a position, and are kept
  when a unit is shuffled between the sender's own provinces. Record them as
  `{"any": [unit_at, owns]}` per province (below). Use `holds` only when the
  message says a named unit will not move ("A VEN holds", "F ENG stays put",
  "all my units hold this turn").
- **What a promise to hold is for.** "I hold GAL, nothing toward VIE or BUD"
  is a pledge not to move on VIE and BUD. Record the pledge
  (`not attacks ... provinces`), and add `holds` only if the message makes the
  hold itself the point.
- **Turns.** Leave `turns` out when the claim is about the turn it was said in
  (the turn the message is listed under). "This year" is both turns of the year; "until 1903"
  is that range. A claim that says "this turn" or names its season is one
  turn, even inside a message that also restates standing terms.
  Turn 0 is Spring 1901, turn 1 Autumn 1901. An open-ended
  claim of any kind ("we stay at peace", "DEN stays yours", "please keep clear
  of BUL") covers the turn it was said in and the three after it (two game
  years): a convention, so that a "lasting peace" broken next year still shows
  as broken. Standing language is open-ended ("no designs on", "respect your
  position", "content to keep the peace", "stays yours"); a reply about this
  turn's moves is one turn. Do not stretch a one-turn claim.
  **The code does not add those three turns: you write them.** `verify`
  checks exactly the turns in `turns`, and a claim without `turns` is checked
  in the one turn it was said in. So an open-ended claim said in turn 4 must
  carry `"turns": [4, 7]`; left without, a peace broken the next year comes
  out kept. A range that runs past the game's last turn is fine: the turns
  that were played are checked.
- **A statement about the past covers the turns it speaks of.** "Your spring
  holds were appreciated" is last Spring's turn; "thanks for staying out of GRE",
  with no period named, is the turn before the message. Do not stretch it over
  the whole game. (A courtesy that names no province or order is no claim.)
- **A standing position is not a new claim each time.** "Trieste is rightfully
  ours", repeated, is a claim of right: no claim. Record it only when it names
  an action ("we will move on Trieste this turn").
- **Stated as fact, or forecast.** "Austria is pressing TRI this turn", said
  flatly with units or provinces named, is a `statement`; the code marks a
  statement about another power's orders in a turn not yet played as a
  forecast (right or wrong), never as a lie. "The signals show", "I expect",
  "likely", "looks set to" are hedged: no claim.
- **An accusation or acknowledgement that names an order and a season** ("your
  F SKA - NWY last autumn", "thanks for keeping SIL quiet this spring") is a
  `statement` on that past turn. The code treats a wrong one as a slip about
  the public record, not a deception.
- **"Occupy" or "hold" a centre** can mean a unit there or owning it: use
  `{"any": [unit_at, owns]}`. `holds` needs a unit in the province, so name
  only provinces where that power has one.
- **"X is yours"** is a promise not to move on X:
  `{"not": {"p": "attacks", "power": <sender>, "provinces": ["X"]}}`. In a
  private message the sender supporting the addressee's own move into X keeps
  this promise (the code spares the addressee). When the sender's own unit
  already sits in X, add `{"p": "leaves", "power": <sender>, "province": "X"}`
  only if the message says it will go.
- **A restated agreement is a fresh promise for this turn.** "Our understanding
  stands" renews the terms. If the same message announces an order that breaks
  them, record both: the contradiction is the finding. A restatement covers
  **one turn** (the turn it is said in), whatever the first statement's range
  was. When both readings fit ("I will continue to respect BUL"): the first
  time a set of terms is stated it is open-ended; every later repeat of the
  same terms is one turn.
- **Record each deal once per sender per turn.** Bots confirm the same terms
  many times in a phase ("Locked.", "Confirmed.", "Orders locked as agreed").
  Give the claim to the first message of the turn that states the terms; later
  echoes in the same turn get `[]`. A later message that **changes** the terms
  is not an echo: see "A changed plan". (`betrayal_events` in the summary also
  guards against one broken deal counted many times.)
- **"Quiet".** "ARM/BLA quiet", "I keep SEV quiet": the sender's units there do
  not move on or support a move on anyone:
  `{"not": {"p": "attacks", "power": <sender>, "target": <addressee>, "unit": "ARM"}}`,
  one predicate per province named. Not `holds`: a unit that supports an attack
  also "holds". A sign-off like "Quiet Black Sea." with nothing else is
  goodwill: no claim.
- **Counts and "every turn"** ("your 13th attack", "three phases running")
  cannot be written: predicates are true when any order in the window matches.
  Mark the count `unverifiable`; when the message also names one specific
  season, add that as a separate one-turn statement.
- **A condition in one turn and a commitment in a later one** ("if you attack
  RUM now, we are at war in 1903"; "stand down this turn and I restore the DMZ
  next year") does not fit: a claim has one `turns` window for both. Mark it
  `unverifiable` with `"why": "condition and commitment in different turns"`.
  Do not widen the window to cover both: an order from before the trigger would
  then count as carrying out the threat.
- **Season words that contradict the phase** ("this fall", listed under a
  Spring turn): cover **both** turns, the message's own and the one it names
  (`"turns": [4, 5]`). A sender that writes "this fall" in a spring phase may
  mean the orders it is about to enter; checking only the named turn gives
  false flags. "Next
  fall" and "next year" are not this case: they mean the following game year.
- **Encode the gist of a loosely described move.** "Your SWE-DEN with BAL
  support" means a supported move on DEN: `moves_to DEN` plus `supports` into
  DEN, not an exact order with the units the message may have swapped. Use an
  exact `order` only when the claim is about that exact order.
- **Conditions must be checkable** ("if you stay out of TRI"). Drop a condition
  on intent or goodwill ("if we stay friends", "say the word") and keep the
  commitment.
- **Use `unverifiable` instead of guessing.** Feelings, intentions, focus,
  flattery, regions with no clear border ("the north Adriatic", "my coast"),
  directions ("I'll head west"): if no order or board fact settles it, the
  commitment is `[{"p": "unverifiable", "why": "<short reason>"}]`. Never
  invent provinces a message does not name or plainly mean.
- **One vague part spoils the claim.** A commitment with an `unverifiable`
  predicate beside checkable ones comes out "cannot be checked" unless a checkable
  part is broken. When a sentence has a clear half and a vague half, record the
  clear half as one claim and the vague half as another.
- **Record what was said, even when it is odd.** "Keep clear of TYR" said to a
  power already in TYR is still `not moves_to TYR`; it will come out trivially
  kept, and the page shows the orders beside it.
- **Quote the words.** `quote` is the part of the message the claim comes from,
  copied exactly, so a reader can check your reading. `verify` refuses a quote
  that is not in the message. Leave words out with `...` (the parts must stay in the message's order); put your own notes in
  `context`, not in the quote.
- **`success` is for results, not intentions.** "I will take Belgium" as a
  promise is `moves_to BEL`; if you add `"success": true`, an order that was
  given and bounced still comes out "tried, but the move failed", not broken. Use
  `success` in statements about what happened ("my fleet took DEN").

Predicates, with powers as upper-case names and provinces as three-letter
abbreviations (`units_at_start` in `annotate.json` shows the spelling):

| Predicate | True when |
|---|---|
| `{"p": "order", "power": P, "order": "A BUD - SER"}` | P gave exactly this order (`H` hold, `-` move, `S` support, `C` convoy) |
| `{"p": "moves_to", "power": P, "province": "TYR"}` | P ordered a unit into TYR. Optional `"unit": "TRI"`: only P's unit in TRI ("keep F TRI out of VEN") |
| `{"p": "holds", "power": P, "province": "DEN"}` | P's unit in DEN was not ordered to move |
| `{"p": "leaves", "power": P, "province": "TRI"}` | P's unit in TRI was ordered to move |
| `{"p": "supports", "power": P, "of": Q, "province": "X", "kind": "move"}` | P supported a unit. Optional: `of` (whose unit), `province` (into or in X), `kind` (`move` or `hold`), `unit` (only P's unit in that province) |
| `{"p": "attacks", "power": P, "target": Q}` | P moved on, or supported a move on, a unit or supply centre of Q. Optional: `"what": "unit"` or `"centre"`; `"unit": "ALB"` (only that unit of P's); `"how": "move"` or `"support"` ("no support against your centres" is `"how": "support", "what": "centre"`) |
| `{"p": "attacks", "power": P, "provinces": ["SER", "RUM"]}` | The same, for a list of provinces. P supporting the move of the power the claim was made to (the addressee, or `to`) into the province is help, not an attack (the code spares that power; `"spare": Q` names another power) |
| `{"p": "dislodged", "power": P, "province": "RUH"}` | P's unit in RUH was dislodged |
| `{"p": "unit_at", "power": P, "province": "PRU", "when": "start"}` | P has a unit there at the start (or `"end"`, the default) of the window |
| `{"p": "owns", "power": P, "province": "DEN"}` | P owns that supply centre (`when` as above) |
| `{"p": "centers", "power": P, "count": 9}` | P owns exactly 9 centres (`"at_least": 9` for "9 or more"; `when` as above) |
| `{"not": <predicate>}`, `{"any": [...]}`, `{"all": [...]}` | negation; at least one; all (for "either this pair of orders or that pair": two `all` groups inside an `any`) |

Every predicate in a list must hold. Over several turns a predicate holds if it
holds in any movement phase, and `not` only if it never does. On `order`,
`moves_to`, `leaves` and `attacks`, `"success": true` requires that the move worked ("I
will take Belgium") and `"success": false` that it was ordered and failed
("your fleet bounces off KIE").

## Reading the result

`audit.json` holds, per message, each claim with its `condition` (none, met,
unmet, unverifiable), `outcome`, the `evidence` (the orders that settled it, then `note:`
lines for any rule below that changed the verdict), `relied` and a `category`.

Its layout, so you do not have to probe it:

| Key | Contents |
|---|---|
| `episode`, `slot`, `policy`, `our_power`, `score`, `outcome` | The game and our seat |
| `belief_logged` | False when our policy's log carried no press policy: every claim is then a "no stance" one |
| `summary.messages`, `summary.messages_with_claims` | Counts |
| `summary.powers.<POWER>` | Per speaker (upper-case name): `messages`, `claims`, `held`, `did_not_hold`, `unverifiable`, `held_share`, `asked`, `complied`, `categories` (category to count), `flagged` (the flagged claims, with quotes) and `betrayal_events` |
| `messages[]` | `id`, `turn`, `sent_in`, `from`, `to`, `direction`, `text`, and `claims[]`: `kind`, `quote`, `commitment`, `turns`, `window`, `condition`, `evidence`, `outcome`, `to`, `relied`, `category` |
| `phases[]` | Per movement phase: `turn`, `label`, `orders`, `units`, `centers`, `units_end`, `centers_end`, `end_known`, and `belief` (our committed stances, trust, required and expected orders that turn). An order's `success` is true or false for a move, a support or a convoy and `null` for a hold, which cannot succeed or fail (an `audit.json` written before 2026-10-12 has `false` there: it does not mean the hold failed) |

Outcomes beyond kept / broken / true / false:

| Outcome | Meaning |
|---|---|
| `attempted` | The promised order was given and it failed (bounced, was cut, the unit was dislodged). Counted as the speaker keeping its word |
| `superseded` | The plan was changed in the open before the orders: a later claim `replaces` it, or every order that broke it was announced to the same party, or asked for by that party, in a later message. `replaced_by` names the replacing message; in the other two cases a `note:` line names it |
| `released` | A conditional promise whose condition was not met |
| `released_by_them` | The other side broke the deal first: a pledge not to move on someone, broken only after that power had attacked the speaker earlier in the claim's window; or a promise broken only after the other party had, in an earlier turn, not done what the same message asked of it |
| `forecast_right`, `forecast_wrong` | A statement about another power's orders in a turn not yet played. Nobody's honesty |
| `unverifiable` | Not checkable, including a claim about a unit that no longer exists and about the board after the last turn |

| Category | Meaning | What to do with it |
|---|---|---|
| `betrayed`, `deceived` | A promise made **to us** (`betrayed`), or a statement of the speaker's own coming orders or a threat that was not carried out (`deceived`), that we relied on and that did not hold, with no notice beforehand | The cases that cost centers. Open the turn: what did we commit because of it? |
| `doubted_wrongly` | Perhaps a missed alliance: a pledge **not to move on us** was kept, the speaker had a unit that could have broken it, it did not move on us in the window or the turn before, we had not relied on it, **we moved on the speaker** in the window, and we had not given that power our own word for those turns (that would be `we_broke_our_word`) | Rare by design, and still the least certain flag. Was our distrust earned? |
| `kept_despite_doubt` | Kept or true, and we had not relied on it, but nothing shows we lost by that | No action. It still counts for the speaker's honesty |
| `kept_but_attacked_us` | Kept in the letter while the speaker moved on our units or centres that turn or the turn before (the orders are in the `note:` lines) | Evidence the distrust was right |
| `trusted_rightly`, `doubted_rightly` | Our stance matched what happened | Evidence the trust rule works |
| `attack_announced`, `attack_not_made` | The sender said it would move on our own unit or centre ("PIC falls this autumn"), and did or did not. Worked out by code from the board; never counted as a betrayal or a missed alliance | Whether a power's threats to us are real |
| `kept_to_other`, `broken_to_other` | A promise made to another power (`to`), which we only watched | A power that breaks its word to others; never a betrayal of us |
| `changed_plans`, `we_changed_plans` | The only thing broken was "this unit will stay put" (`holds`, or a hold order; a promised support-hold of its own unit too, but not one of the other party's unit: that is help withheld), and the speaker made no move on the party it was said to | A changed plan nobody was told about. Not a stab |
| `our_attack_announced`, `our_attack_not_made` | We told a power we would move on its unit or centre, and did or did not | Whether our threats are real. Not a matter of our word |
| `misstated`, `we_misstated` | A wrong statement about orders already played. Everyone can read those off the board, so nobody was deceived | Sloppy or taunting talk. Counted in `did_not_hold`, never flagged |
| `true_no_stance`, `false_no_stance` | It held or did not; our policy recorded no stance on that power that turn | Count them per power: this is each power's honesty |
| `we_kept_our_word`, `we_broke_our_word` | Our own outgoing promises, and statements of our own coming orders | Whether the bot says one thing and orders another |

Only `betrayed`, `deceived`, `doubted_wrongly` and `we_broke_our_word` are
flagged (`summary.powers.<POWER>.flagged`) and marked on the IDE's replay
timeline.

**The codes above are for you; the pages show words.** `audit.html` and the
IDE's replay viewer never print an outcome or a category. `tools/press_report.py`
turns each claim into a label and a note: `broken` + `betrayed` reads "broke
their word · we relied on it", `kept` + `kept_to_other` reads "kept their word ·
promise was to Turkey, not us", `attempted` reads "tried, but the move failed",
`superseded` reads "plan changed openly", and a `*_no_stance` claim shows the
label alone. Red is kept for `betrayed`, `deceived` and `we_broke_our_word`.
When you tell the user about a claim, use the page's words, not the code; each
label's one-line meaning is under "What the labels mean" on both pages
(`press_report.LEGEND`).

Each claim made to us by another power also carries `attacks_on_us` (the
speaker's moves, supports and convoys against our units and centres in the
claim's window), `attacks_on_us_before` (the turn before), `our_attacks_on_them`
and `could_break`. A statement carries `scope`: `own_orders`, `forecast` or
`record`.

"Relied" is read at the **first turn of the claim's window**, from that turn's
final committed policy. A trust number below 0.5 counts as "did not rely" even
when the stance is `ally`;
`hostile` (or `enemy`) counts as "did not rely" whatever the trust.

`summary.powers` gives, per speaker, its messages, its claims, how many held,
how often requests made to it were met, and the flagged claims. A power's
`claims` leaves out the requests it made: a request is weighed against the
power asked (`asked`, `complied`), not its sender. So the per-power `claims`
add up to fewer than the claim count `check` prints. `verify` prints that
column as `claims_without_requests` beside `requests_made`, and the two add up
to its `claims` total, which is `check`'s number. `claims_without_requests`
still includes proposals and claims that came out `unverifiable`; `held` and
`did_not_hold` are the ones that could be judged. `betrayal_events` counts the
distinct sets of orders behind a power's `betrayed` and `deceived` claims: a deal
restated ten times and broken by one order is ten claims and **one** event. Quote the
events, not the claims, when you say how often a power betrayed us. **"Relied" comes from our policy's own log** (its committed press policy
for the turn: an ally stance, trust of 0.5 or more, or expected orders from
the sender). A policy that does not log one gets `relied: null`, and every
claim lands in the two "no stance" categories. That still shows who lied.

## Limits, stated plainly

- **The reading is a model's; the checking is code's.** A wrong annotation gives
  a wrong verdict with real-looking evidence. Spot-check before quoting numbers,
  and never pool a power's honesty over games you have not looked at.
- **A changed plan is only seen when it is recorded.** `superseded` needs the
  annotator's `replaces`, or a later claim that names the very order. A plan
  dropped with a vague "things have changed" still reads as broken.
- **"Relied" is the logged stance, not what we did.** A policy can log low
  trust and go along with the deal anyway. That is why a kept promise is a
  missed alliance only when we attacked the speaker.
- **Counts are small.** One game gives a power a handful of checkable claims.
  "Germany kept 4 of 5" is an observation about this game, not a rate.
- **An ordered move is not a successful one.** A promise to "move to X" is kept
  when the order was given, even if it bounced; with `success` it reads
  "tried, but the move failed". A deliberately hopeless order looks the same.
- **Only movement phases are checked.** Retreat and build promises are
  `unverifiable`. A retreat onto our centre is not seen as an attack.
- **Reach ignores convoys.** `could_break` looks for a unit next to the
  protected province; an army that could only arrive by sea counts as out of reach.
- **The page holds private press.** Keep `audit.html` and the `.runtime/press`
  folder on your machine.

## Handoffs

- A pattern across games (a power that lies, a trust rule that fails) is a
  hypothesis: take it to `diagnose` and an experiment record.
- Episodes worth the human's eyes: give them `audit.html` and the hosted replay
  (`coworld replay-open <episode-request-id> --hosted`), or the IDE's viewer,
  `/replays/<episode id>?seat=<our slot>`, which shows the audit beside the
  game.
