# Closed levers — webDiplomacy

Refuted levers in this game, with the numbers that killed them. `diagnose`
consults this before proposing. Same format as the root register; keep it
short and point at the experiment records for detail.

Seeded from a prior webDiplomacy lab campaign (2026-10). There are no experiment
records for these in this lab; the numbers are the record. Most were measured
with the Kissinger search policy in gunboat games, in paired local games unless
noted. The common thread: **more search over the same position evaluation does
not help and often hurts**, because the search finds the evaluation's errors.

---

## Learned position evaluation                       closed 2026-10-07
**Mechanism:** replace or blend the hand-written evaluation with a ridge model
predicting centers two years ahead (R² 0.75).
**Killed by:** local arena score fell from 0.64 to 0.33. The search exploited it:
its features reward standing next to targets instead of taking them.
**Would reopen if:** an evaluation trained causally from game outcomes (not
regression over observed positions), verified in paired games.

## Rollouts (spring plans judged by a heuristic autumn)  closed 2026-10-07
**Mechanism:** look one phase ahead by playing a heuristic Autumn after each
candidate Spring plan.
**Killed by:** −0.126 paired (z −1.78). The heuristic Autumn misjudges plans.
**Would reopen if:** a rollout policy as strong as the search itself.

## Opponent model level 0, level 2, or a mix          closed 2026-10-07
**Mechanism:** model opponents as plain heuristic players (level 0), as two
best-response passes (level 2), or as a 50/50 mix of levels 0 and 1.
**Killed by:** level 0 lost by 0.135 (paired, z 2.4); level 2 lost by about
0.11; the mix lost by 0.10 (z −2.07). Level 1 stays.
**Would reopen if:** a field whose opponents are much weaker or much stronger
than search bots.

## More search effort: restarts, three-unit attacks, more samples  closed 2026-10-07
**Mechanism:** 3 restarts instead of 1; three-unit attack alternatives; 24
instead of 16 sampled opponent plans.
**Killed by:** all null or negative. Triples −0.06 (z −1.51, dilutes a fixed
budget); 24 samples −0.016 (z −0.26); restarts scored below single runs.
**Would reopen if:** a better evaluation (see the first entry).

## Risk aversion                                      closed 2026-10-07
**Mechanism:** weight bad outcomes more heavily (risk 0.5) when scoring a plan.
Evolution repeatedly picked this knob.
**Killed by:** −0.055 in the final four-way paired test (48 games).
**Would reopen if:** a field where losses are much more costly than now.

## Build search                                       closed 2026-10-07
**Mechanism:** search over winter builds instead of using the heuristic's.
**Killed by:** +0.044 (z 0.66), then +0.010 in the four-way test. Null, and it
costs time. Combined builds + risk + diplomacy: −0.016.
**Would reopen if:** evidence that builds decide games in the target field.

## Fabius (defensive personality)                     closed 2026-10-07
**Mechanism:** risk 0.8 plus defensive weights.
**Killed by:** −0.122 paired (z −2.6).
**Would reopen if:** none foreseen.

## Evolutionary tuning                                closed 2026-10-07
**Mechanism:** continuous evolutionary self-play over knob genomes.
**Killed by:** with the champion as the anchor, no genome beat it in 53
generations. With a weak anchor, genomes tuned against each other's quirks.
Its repeated pick (risk ≈ 0.5) failed the paired test above.
**Would reopen if:** used only to suggest knobs, each then tested in a paired
A/B.

## Permanent liar marks (press)                       closed 2026-10-09 (provisional)
**Mechanism:** permanently distrust a power that attacked us while we trusted
it: trust capped, its expected orders dropped, alliance refused.
**Killed by:** 0.078 against 0.158 for its base (hosted press field, 16 games
each, pooled means, not stratified by power). Provisional: n is small, but the
gap is large and in the wrong direction.
**Would reopen if:** a softer version (for example explicit opponent profiles
with reasons) shows a paired gain.
