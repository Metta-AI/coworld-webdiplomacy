# Best practices — webDiplomacy

Durable, graduated practice for optimizing in this game. Mixin authors: seed
this with the game community's earned lessons — it's a mixin's biggest gift.
User graduations accumulate alongside, marked with their recurrence evidence.

Entries marked `[mixin]` shipped with this mixin. Each was measured in a prior
webDiplomacy lab campaign (2026-10-06 to 2026-10-09) and carries its evidence.

---

## Measuring

- `[mixin]` **Treat |z| < 2 as no result.** *(Evidence: three leads of about
  +0.08 at z ≈ 1.4 shrank to zero when re-run.)*
- `[mixin]` **Seat both policies in the same games (paired seating).** Separate
  arms needed 2 to 3 times more games for the same precision. *(Measured in
  gunboat.)*
- `[mixin]` **Stratify every result by power, against the same-batch field
  par.** Powers are shuffled per episode and par ranged from 0.290 (France) to
  0.090 (England) over 1,238 field seats. Pooled scores mostly measure which
  powers a policy drew.
- `[mixin]` **Judge against the field you will meet.** The same bot ranked
  first or last depending on its opponents: Kissinger scored 0.38 against
  DumbBots, below plain search, yet won against search-bot fields. Local wins
  do not transfer either: a version that won a local tournament scored below
  par hosted.
- `[mixin]` **A nonzero `rejected` count is a bug, not noise.** Upstream drops
  invalid orders silently, so the orders adjudicated are not the ones chosen.
- `[mixin]` **Take final centers from `results.json` `members`,** not the
  replay's `Finished` entry, which shows ownership from before the last Autumn.

## Building policies

- `[mixin]` **Floor first.** Save legal orders from the search before any LLM
  call, so the LLM can never leave the seat without legal orders. Timeouts,
  429s and failing models then cost nothing worse than the floor.
  *(Evidence: no missed deadlines and no rejected orders in the lab's hosted
  press games with the floor design.)*
- `[mixin]` **Give the LLM the map.** Hand it the province connectivity list,
  labeled as possible moves. Without it, about 66 wrong adjacency claims per
  game; with it, about 21. *(Score effect trending positive, v7 0.163, no
  verdict at n = 16.)*
- `[mixin]` **Model opponents one step smarter than a heuristic, no more.**
  The level-1 opponent model (each competent opponent plays its heuristic plan
  improved by one best-response pass) beat level 0 by 0.135 (paired, z 2.4).
  Level 2 and 50/50 mixes lost 0.10 to 0.11.
- `[mixin]` **Classify opponents by whether their orders are sensible,** not by
  whether they match your model. Treating "unlike the heuristic" as "random"
  made the bot treat strong opponents as random; fixing it was worth +0.106
  (paired, z 2.25).
- `[mixin]` **After any model or prompt change, run one health check** on
  `classic-press-short` and confirm every LLM call in our seat logs succeeded.
  A failing seat silently plays its floor.
