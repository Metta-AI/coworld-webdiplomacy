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

Negotiation only pays when the policy trusts the right powers. This skill
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
| 1. Extract | `tools/press_audit.py extract` | `ledger.json`: every message our seat saw, every movement phase's adjudicated orders and board, and our policy's logged beliefs. An empty `claims.json` |
| 2. Annotate | **an agent** (a sub-agent per game) | Fills `claims.json`: for each message, the claims it makes, in a fixed vocabulary |
| 3. Verify | `tools/press_audit.py verify` | `audit.json`: every claim checked **by code** against the orders |
| 4. Report | `tools/press_audit.py report` | `audit.html`: one page, turn by turn, said beside done |

The split matters. Reading language is a job for a model; deciding whether an
order was given is a job for code. **The annotator records what was said. It
never decides whether it came true.**

## Method

From the optimizer root. `L=games/webdiplomacy`, `EP` is one fetched or local
episode directory, `OUT=$L/.runtime/press/<episode id>`.

```sh
python3 $L/tools/press_audit.py extract $EP --policy <policy>:vN --out $OUT   # --slot N if we hold two seats
#   ... annotate $OUT/claims.json (below) ...
python3 $L/tools/press_audit.py verify $OUT
python3 $L/tools/press_audit.py report $OUT        # prints the path of audit.html
```

`verify` refuses a `claims.json` that skips a message or breaks the format, and
names the entry. Fix that entry and run it again.

### Annotating: use a sub-agent per game

A chatty seat sees 100 to 160 messages in a short game and 230 to 300 in a full
`classic-press` game (measured 2026-10-10). Annotating one full game took a
sub-agent 9 to 14 minutes and 160,000 to 200,000 tokens. **Give each game to its own
sub-agent** (several games: several sub-agents at once). The reading then stays
out of your own context, and each game is read in one pass by an agent that
holds the whole conversation. Give the sub-agent this brief, with the paths
filled in:

> Read `<OUT>/ledger.json`. It holds one Diplomacy game seen from
> `<our_power>`'s seat: `messages` (press we sent, `direction: out`, or
> received, `in`) and `phases` (each movement turn's orders and units).
> Fill in `<OUT>/claims.json`: for every message id, the list of claims that
> message makes. Follow "The claim vocabulary" in
> `games/webdiplomacy/skills/press-audit/SKILL.md` exactly. Record only what
> the message says. Do not look at later orders to decide what a message
> "really meant", and do not mark anything true or false: code does that.
> Use the board in `phases` only to resolve references ("my fleet", "your
> army in Warsaw", "the Baltic") to powers and provinces. When you are done,
> run `python3 games/webdiplomacy/tools/press_audit.py verify <OUT>` and fix
> every format error it reports until it passes. Report how many messages had
> claims and which claims you marked unverifiable.

Then read `verify`'s summary yourself and spot-check a few claims in
`audit.html` against their messages before you rely on the numbers. Check the
flagged ones first: for each `betrayed`, read the evidence line beside the
message and ask "was this promise made to us, and did this order hurt us?".
The first real games audited (2026-10-10) had three kinds of false alarm, two
since fixed in the code (an announced attack on us; help into a province read
as an attack on it) and one not: **a promise made to a third power**. "We have
agreed a DMZ in Burgundy with France", said in public, is checked like any
promise, and when it breaks while we trust the speaker it is marked `betrayed`
although nothing was promised to us.

The ledger's `phases` hold results (`success`, `dislodged`, `units_end`) next to
the starting board the annotator needs, so the annotator can see how every
order came out. The brief tells it not to use that; it is not blind.

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
  word. Use `proposal` only when the sender frames its own side as an offer
  awaiting an answer ("I propose", "shall we", "let us", "I suggest").
- **A bare "Agreed" takes the terms of the message it answers.** Copy that
  message's terms as the sender's `promise`, and put both in the `quote`
  ("Agreed. [to prv-209: hold VIE, stay out of TRI]").
- **Soft verbs still commit.** "I can keep…", "I am prepared to…" are promises;
  "I trust you will…" is a request.
- **What is not a claim.** An explicit refusal to commit ("I cannot promise to
  leave Trieste"), a forecast of what a third power might do, a question.
  Leave them out.
- **"I will not attack you"** is `{"not": {"p": "attacks", "power": <sender>,
  "target": <addressee>}}`. When the words are narrower, narrow it: "your
  centres" is `"what": "centre"`; "my fleet in Albania stays peaceful" is
  `"unit": "ALB"`; "leave RUM and SER alone" is `"provinces": ["RUM", "SER"]`.
- **`holds` or an exact order.** `holds` is true for any order that keeps the
  unit in place, including a support. Use `{"p": "order", ...}` only when the
  message writes the order out.
- **Turns.** Leave `turns` out when the claim is about the turn it was said in
  (the message's `turn`). "This year" is both turns of the year; "until 1903"
  is that range. Turn 0 is Spring 1901, turn 1 Autumn 1901. An open-ended
  claim of any kind ("we stay at peace", "DEN stays yours", "please keep clear
  of BUL") covers the turn it was said in and the three after it (two game
  years): a convention, so that a "lasting peace" broken next year still shows
  as broken. Standing language is open-ended ("no designs on", "respect your
  position", "content to keep the peace", "stays yours"); a reply about this
  turn's moves is one turn. Do not stretch a one-turn claim.
- **A statement about the past covers the turns it speaks of.** "Your spring
  holds were appreciated" is last Spring's turn; "your restraint has been
  welcome", with no period named, is the turn before the message. Do not
  stretch it over the whole game.
- **A standing position is not a new claim each time.** "Trieste is rightfully
  ours", repeated, is a claim of right: no claim. Record it only when it names
  an action ("we will move on Trieste this turn").
- **Stated as fact, or forecast.** "Austria is pressing TRI this turn" is a
  `statement`. "The signals show", "I expect", "likely" are forecasts: no claim.
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
  was.
- **Record each deal once per sender per turn.** Bots confirm the same terms
  many times in a phase ("Locked.", "Confirmed.", "Orders locked as agreed").
  Give the claim to the first message of the turn that states the terms; later
  echoes in the same turn get `[]`. (Before this rule, one broken deal showed
  as six to twelve betrayals. `betrayal_events` in the summary also guards
  against it.)
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
- **Season words that contradict the phase** ("this fall", said in a Spring
  phase): record the season the message names, as the next turn.
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
  predicate beside checkable ones comes out "not checkable" unless a checkable
  part is broken. When a sentence has a clear half and a vague half, record the
  clear half as one claim and the vague half as another.
- **Record what was said, even when it is odd.** "Keep clear of TYR" said to a
  power already in TYR is still `not moves_to TYR`; it will come out trivially
  kept, and the page shows the orders beside it.
- **Quote the words.** `quote` is the part of the message the claim comes from,
  copied exactly, so a reader can check your reading.

Predicates, with powers as upper-case names and provinces as three-letter
abbreviations (the ledger's `phases` show the spelling):

| Predicate | True when |
|---|---|
| `{"p": "order", "power": P, "order": "A BUD - SER"}` | P gave exactly this order (`H` hold, `-` move, `S` support, `C` convoy) |
| `{"p": "moves_to", "power": P, "province": "TYR"}` | P ordered a unit into TYR. Optional `"unit": "TRI"`: only P's unit in TRI ("keep F TRI out of VEN") |
| `{"p": "holds", "power": P, "province": "DEN"}` | P's unit in DEN was not ordered to move |
| `{"p": "leaves", "power": P, "province": "TRI"}` | P's unit in TRI was ordered to move |
| `{"p": "supports", "power": P, "of": Q, "province": "X", "kind": "move"}` | P supported a unit. Optional: `of` (whose unit), `province` (into or in X), `kind` (`move` or `hold`), `unit` (only P's unit in that province) |
| `{"p": "attacks", "power": P, "target": Q}` | P moved on, or supported a move on, a unit or supply centre of Q. Optional: `"what": "unit"` or `"centre"`; `"unit": "ALB"` (only that unit of P's); `"how": "move"` or `"support"` ("no support against your centres" is `"how": "support", "what": "centre"`) |
| `{"p": "attacks", "power": P, "provinces": ["SER", "RUM"]}` | The same, for a list of provinces. In a private message, P supporting the other party's own move into the province is help, not an attack (the code spares the addressee; `"spare": Q` names another power) |
| `{"p": "dislodged", "power": P, "province": "RUH"}` | P's unit in RUH was dislodged |
| `{"p": "unit_at", "power": P, "province": "PRU", "when": "start"}` | P has a unit there at the start (or `"end"`, the default) of the window |
| `{"p": "owns", "power": P, "province": "DEN"}` | P owns that supply centre (`when` as above) |
| `{"p": "centers", "power": P, "count": 9}` | P owns exactly 9 centres (`"at_least": 9` for "9 or more"; `when` as above) |
| `{"not": <predicate>}`, `{"any": [...]}`, `{"all": [...]}` | negation; at least one; all (for "either this pair of orders or that pair": two `all` groups inside an `any`) |

Every predicate in a list must hold. Over several turns a predicate holds if it
holds in any movement phase, and `not` only if it never does. On `order`,
`moves_to` and `attacks`, `"success": true` requires that the move worked ("I
will take Belgium") and `"success": false` that it was ordered and failed
("your fleet bounces off KIE").

## Reading the result

`audit.json` holds, per message, each claim with its `condition` (none, met,
unmet), `outcome`, the `evidence` (the orders that settled it), `relied` and a
`category`:

| Category | Meaning | What to do with it |
|---|---|---|
| `betrayed`, `deceived` | We relied on a promise or statement that did not hold | The cases that cost centers. Open the turn: what did we commit because of it? |
| `doubted_wrongly` | We did not rely on a promise that was kept | Perhaps a missed alliance: was our distrust earned? Look at what else that power ordered the same turn first. A narrow promise ("my fleet stays out of Belgium") is "kept" by a power that attacked us somewhere else |
| `trusted_rightly`, `doubted_rightly` | Our stance matched what happened | Evidence the trust rule works |
| `attack_announced`, `attack_not_made` | The sender said it would move on our own unit or centre ("PIC falls this autumn"), and did or did not. Worked out by code from the board; never counted as a betrayal or a missed alliance | Whether a power's threats to us are real |
| `true_no_stance`, `false_no_stance` | It held or did not; our policy recorded no stance on that power that turn | Count them per power: this is each power's honesty |
| `we_kept_our_word`, `we_broke_our_word` | Our own outgoing claims | Whether the bot says one thing and orders another |

"Relied" is read at the **first turn of the claim's window**, from that turn's
final committed policy. A trust number below 0.5 counts as "did not rely" even
when the stance is `ally` (the reference policy does log "ally at trust 0.4");
`hostile` (or `enemy`) counts as "did not rely" whatever the trust.

`summary.powers` gives, per speaker, its messages, its claims, how many held,
how often requests made to it were met, and the flagged claims. `betrayal_events` counts the
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
- **Counts are small.** One game gives a power a handful of checkable claims.
  "Germany kept 4 of 5" is an observation about this game, not a rate.
- **An ordered move is not a successful one.** A promise to "move to X" is kept
  when the order was given, even if it bounced, unless you asked for `success`.
- **Only movement phases are checked.** Retreat and build promises are
  `unverifiable`.
- **The page holds private press.** Keep `audit.html` and the `.runtime/press`
  folder on your machine.

## Handoffs

- A pattern across games (a power that lies, a trust rule that fails) is a
  hypothesis: take it to `diagnose` and an experiment record.
- Episodes worth the human's eyes: give them `audit.html` and the hosted replay
  (`coworld replay-open <episode-request-id> --hosted`).
