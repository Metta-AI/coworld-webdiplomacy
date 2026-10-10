---
name: negotiation
description: How to make, test and keep track of deals (DMZs, supports, spheres of influence).
---
# Negotiation playbook

1. **Find who matters this phase.** Neighbours whose units can reach your centres, and
   powers whose support would win you a contested centre. Use the board's map
   connectivity and `predict`.
2. **Make one concrete offer per power.** Good forms:
   - DMZ: "Neither of us moves into GAL or TYR this phase."
   - Support: "If you order A BUD S A VIE - GAL, I order F TRI S A BUD - SER."
   - Sphere: "You take the north (SWE, NWY); I stay out. I take the south."
3. **Test it before you send it.** `assess_deal(power, their_orders, our_orders, our_forbidden)`.
   Offer only deals where "both_honour" beats your current committed plan and "they_betray"
   is survivable.
4. **When they agree, commit and note it.** `commit_orders` with their promised orders in
   `expected_orders`, your promised orders in `require_orders`, the DMZ in
   `forbid_moves_into`. Write the deal in a note (who, what, which phase) so the next
   wake knows it.
5. **Check it next phase** against the referee facts: what they actually ordered.
