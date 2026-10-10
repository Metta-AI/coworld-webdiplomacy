# webDiplomacy: strategy

Two parts. First, a general Diplomacy primer from human play, **not yet
verified against this field of bots**: treat each point as a hypothesis. Second,
facts **measured** in this league's field in 2026-10. The field changes, so the
measured facts carry dates. The live field picture belongs in `META.md`
(maintained by meta-recon).

## Part 1: a general primer (not yet verified against this field)

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

Note: this field does **not** match human lore. England is the *weakest* power
here and France the strongest (Part 2). Do not assume human opening theory
transfers.

**Press (human lore).**

- Agreements are not binding; the adjudicator enforces only orders.
- Trust deeds over words. A power that attacked you once is likely to again.
- Timing a betrayal matters: a stab is worth it when it gains centers you can
  keep and the victim cannot retaliate in time.

## Part 2: the measured field (2026-10)

Measured by a prior webDiplomacy lab in the press league's field, campaign
`press-ab1`, 2026-10-08 to 10-09. "The geometry field" is the six-seat field
after its LLM seats were given the map connectivity list.

### Power par

Mean score per seat by power, over 1,238 field seats in the geometry field
(parity is 1/7 = 0.143):

| Power | France | Turkey | Italy | Germany | Russia | Austria | England |
|---|---|---|---|---|---|---|---|
| Mean score | 0.290 | 0.191 | 0.119 | 0.114 | 0.114 | 0.099 | 0.090 |

France scores about three times England. Any comparison that does not hold the
power fixed mostly measures which powers a policy happened to draw.

### Who did well

Mean score per seat in the press field (parity 0.143):

| Seat | Kind | Mean | n |
|---|---|---|---|
| Talleyrand soul on `openai/gpt-6-luna` | LLM press, **liar** | 0.195 (geometry field), 0.208 (earlier field) | 208 / 100 games |
| Kissinger | Search, **silent** (no press) | 0.172 to 0.176 | 208 / 100 games |
| Bismarck soul on deepseek | LLM press, honest warmonger | 0.165 | 208 games |
| Metternich soul on gemini flash-lite | LLM press, cautious, never lies | 0.165 | 208 games |
| Machiavelli soul on glm | LLM press, stabber | 0.123 | 208 games |
| Calhamer | Heuristic, silent | 0.048 | 208 games |
| Castlereagh press | Kissinger search + LLM press | 0.126 (all versions, earlier field); champion v1 0.124 (geometry field) | 100 / 16 games |

What this says:

- **The best press seat was a liar**, Talleyrand on gpt-6-luna, in both fields.
- **A silent search bot beat most press bots.** Press as built so far
  (Castlereagh) scored below the same search engine without press. No press
  change has a verdict yet at 16 games per arm.
- Trending positive but unproven: giving the LLM the map connectivity list
  (v7, 0.163) and stronger models for the same prompt (deepseek 0.192,
  gpt-6-luna 0.175).
- **Our press bot re-trusted powers that betrayed it.** After a first breach or
  attack while trusted, it went back to trusting the same power 94 times in 46
  relationships over 100 games.
- A blunt fix, permanently marking a betrayer (v8), scored 0.078 against 0.158
  for its base. See `closed_levers.md`.

### The field depends on who is in it

The same bot can rank first or last depending on its opponents. Kissinger
scored 0.38 per game against a field of DumbBots (simple heuristic bots), well
below plain search's 0.55 to 0.75 in the same local setup, because its opponent model
expects smarter opponents. Against search-bot fields it won. **Judge a policy
against the field it will meet.**

### League rosters as of 2026-10-09

- **webDiplomacy (press):** the filler roster was the six-seat press field
  above (Bismarck, Talleyrand, Metternich, Machiavelli, Kissinger, Calhamer).
  The champion was Castlereagh press v1.
- **webDiplomacy Gunboat:** the champion was the Kissinger search lineage. The
  12 fillers were Random, Calhamer, Machiavelli, Bismarck, Metternich,
  Talleyrand, Napoleon, Blücher, Kissinger, Fabius, Garibaldi and Rasputin
  (gunboat versions, 2026-10-07). The only other entrant scored about 0.0 to
  0.03 per game.

Re-check both rosters before relying on them.
