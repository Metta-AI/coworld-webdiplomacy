---
name: trust
description: When to treat a power as an ally, how to move trust, and when (not) to stab.
---
# Trust and stabs

Searches use your stances and trust directly: an ally is assumed not to attack you, and
trust is how often a power plays the orders it promised. Wrong trust costs centres.

## Move trust on orders, not words

| Evidence (from the referee facts) | Change |
| --- | --- |
| A concrete promise kept (order played, DMZ respected) | +0.1 |
| A promise broken | -0.3 or more |
| An attack on you while allied | trust 0.2 or lower, stance not ally |
| Words only: apologies, explanations, new offers | no change |

Re-trusting a power that broke its word, on reassurance alone, cost the lab's press bot
more than any other negotiation mistake. One bounce in a shared border province is not a
war; a move into your centre or a support of someone else's attack on you is.

## Stab checklist

Break an agreement only if every answer is yes:
1. `assess_deal` "we_betray" beats "both_honour" by **two or more expected centres**.
2. The gain lasts: the victim cannot retake those centres next year
   (check `predict` for that power with stance hostile).
3. You do not need this ally against a stronger threat in the next two years.

If you stab, commit fully: stance hostile, raise `center_values` for their centres, and do
not announce it in advance.
