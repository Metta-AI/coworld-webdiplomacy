---
name: webdiplomacy-ab
binding: ab
description: >
  webDiplomacy binding for the core ab-compare skill: this game's metrics,
  decompositions, taint definition, statistical tests, and N floors.
---

# A/B binding — webDiplomacy

The core `ab-compare` skill carries the comparison standard (fresh + matched,
taint before means, decompose before judging, noise is a verdict, regression
sweep). This binding supplies everything game-shaped. Fill every section —
a section you can't fill yet is a gap worth telling users about in MIXIN.md.

## Metrics that matter

*(each metric: name, type (rate | mean | other), direction (higher/lower is
better), and one line on why it matters for winning here)*

## Decompositions

*(the splits that must be applied before any verdict — roles? seats? phases?
map types? — and why the aggregate misleads without them)*

## Taint — what an invalid episode is

*(exactly how to detect an episode that must be dropped before any mean:
disconnects, no-shows, platform incidents. Include how to distinguish
"our policy crashed" from "the platform failed" — they're different findings)*

## Tests and floors

*(which statistical tests fit which metrics here; the N floor below which
results are directional only, informed by this game's variance; anything
about pooling or pairing that this game rewards or punishes)*

## Tooling

*(the working comparison tooling this binding ships — any language. Document
the CLI: inputs, outputs, and an example invocation. If analysis needs grow
beyond it, the agent builds lab instruments in `../../instruments/` — never
regenerates throwaway code per session)*
