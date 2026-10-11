---
name: agreements
description: How to express a DMZ, a support or a convoy agreement in a policy, and how to read assess_deal.
---
# Agreements and the policy

Press agreements are not binding: the game adjudicates orders only. This skill shows how
each common kind of agreement maps onto policy fields, so the search plans with it. It
does not say which agreements to make.

## The three common kinds

**Demilitarised zone (DMZ).** Two powers agree that neither enters a province.
- Your side: put the province in `forbid_moves_into`, e.g. `["BUR"]`. Your units will not
  move or support into it.
- Their side: there is no field for "they will stay out". If they named the orders they
  will play instead, list those in `expected_orders`. A stance of "ally" covers only your
  own provinces (your centres and the provinces your units stand in).

**Support.** One power's unit supports another power's move or hold.
- They support you: put their support order in `expected_orders`, e.g.
  `"A BUD S A VIE - GAL"`, and the supported move in `require_orders`, e.g. `"A VIE - GAL"`.
- You support them: put your support order in `require_orders`, e.g. `"F TRI S A BUD - SER"`,
  and their move in `expected_orders`.
- A support order names the supported unit and its destination exactly. If the supported
  unit plays a different order, the support does nothing.

**Convoy.** A fleet carries an army across sea provinces.
- The army's order is written with VIA: `"A LON - BEL VIA"`. The fleet's order is
  `"F NTH C A LON - BEL"`. Every fleet on the path must order the convoy.
- Your army on their fleet: the army move in `require_orders`, their convoy order in
  `expected_orders`. Their army on your fleet: the reverse.
- The search treats a convoyed move as a plain move when every fleet on the path orders that
  convoy, and as a hold otherwise. It does not model a convoy that fails because a fleet
  is dislodged.

## What trust does to an agreement

Each entry in `expected_orders` is sampled with that power's `trust`. The search plans
against a set of sampled opponent plans; at trust 0.7 that unit plays the expected order in
about 70% of them. In the rest it plays what the opponent model would have chosen. Trust
1.0 plans as if the order is certain; trust 0 ignores it.

## Checking a deal before you commit

`assess_deal(power, their_orders, our_orders, our_forbidden)` runs three searches:

| Field | What was searched |
| --- | --- |
| `both_honour` | They play `their_orders` for certain, you play `our_orders` and stay out of `our_forbidden`. Gives your expected centres and your full order set. |
| `they_betray` | You play the `both_honour` orders; they are modelled as hostile and free to play anything. Gives expected and worst-case centres. |
| `we_betray` | They play `their_orders` for certain and are modelled as an ally; your units are free. Gives expected centres and the orders the search would choose. |

Each number is your centre count after this one phase. Compare them with the report of a
plain `search({})` to see what the deal changes. The tool says nothing about later phases
or about how a power will react.

## Keeping track

The harness does not record agreements for you. A note (`notes(key, text)`) is the only
record a later wake will see. The referee facts and `facts(POWER)` show the orders that
were actually played.
