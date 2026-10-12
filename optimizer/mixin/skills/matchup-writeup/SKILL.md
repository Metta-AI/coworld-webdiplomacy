---
name: webdiplomacy-matchup-writeup
description: >
  Write up why our policy wins or loses against each opponent policy (or one
  named opponent): where the differences are, whether they are real, which
  games carry them, and what happened in those games, with the mechanism kept
  apart from the result. Writes reports/matchups/. Use when the user asks
  "why do we lose to X", "who do we beat and why", or "what is going on
  against the field"; after a field eval or a league round shows one opponent
  far above or below us; and before choosing what to work on next.
---

# Matchup write-up — webDiplomacy

The dashboard says **how much** we score with each opponent at the table. This
skill writes down **why**, in a file the user can read and argue with:
`reports/matchups/<our policy>-vs-<opponent or "field">.md`.

Two rules shape everything below.

- **The numbers come from one place.** `tools/matchups.py` computes every
  score, par, SE and z (the dashboard uses the same code). Quote them. Counts
  of games (how often a pattern holds, ahead and behind for some split) are
  yours to make in a script; means, pars, SEs and z come only from the tools.
- **"What happened" and "why" are different sentences.** What happened is in
  the orders and the scores. Why is an explanation, and every explanation
  names its evidence and how sure it is. When the games cannot tell two
  explanations apart, list both and say so. A confident story with nothing
  under it is the failure this skill exists to prevent.

"No result against X in N games" is a complete and common answer. Most of the
method below is about not turning it into a story.

## Method

From the optimizer root, with these names:

| Name | Meaning |
|---|---|
| `L` | `games/webdiplomacy` |
| `A` | `$L/.runtime/artifacts` |
| `P` | Our policy: `NAME` for every version, `NAME:vN` for one |
| `V` | The variant: `classic-press` (the main league) or `classic-gunboat`. One variant per write-up |
| `O` | Empty, or `--ours <name>` for each other policy name that is also ours (a search-only build, a second lineage: the first column of `players/castlereagh/VERSION_LOG.md` lists every name). The tools know "ours" only by `P` |
| `S` | A scratch folder for this write-up: `$L/.runtime/matchup-<report file name without .md>`. Create it. A refresh uses a new one (add the time) so the old run stays for comparison |

### 1. Where the differences are, and whether they are real

```sh
python3 $L/tools/matchups.py $A --policy $P --variant $V $O --out $S/matchups
```

Pass `$O` on every `matchups.py` and `holds.py` command below. Without it a
seat of our other policy is counted as a field seat, gets its own row in "By
opponent", and a game that seats it beside `$P` passes for an alone game.

One read writes `$S/matchups.json` (the record: work from it) and
`$S/matchups.txt` (the same numbers, to read). The JSON lists the games it
read (`episodes_read`) and our clean games among them (`episodes`), so the
write-up is frozen on that run: every later command takes
`--episodes $S/matchups.json` and reads the same games, and
`matchups.py ... --episodes $S/matchups.json` prints the same numbers again
however many games have arrived since. Those later games are named in "What
this does not show", not mixed in. Note the time of the run in the report.

**Say what the games are.** Read the header, its `sources:` line (games from
league matches, from experience requests and local, then how many seat one of
our seats and how many two or more), the caveats and "By variant and
source". `xp` rows are our own eval batches; `league` rows are league rounds.
`$A` holds every fetched folder, `league-press` included, and a folder with
no seat of our policy adds nothing to our numbers (its field seats still count
toward par). The tool prints "no clean game of <policy> from league matches:
N such games were read and count toward par only" when that happens: copy
that fact into the report, and do not call the write-up a league result.
If the user asked about league games and there are none (`--source league`
then answers with the error "no seats for this policy and these filters":
that is the answer), lead the report with that. "N games seat more than one
of our seats" means paired runs are mixed in. Then also save the alone view:

```sh
python3 $L/tools/matchups.py $A --policy $P --variant $V $O --episodes $S/matchups.json --alone --out $S/matchups-alone
```

`--alone` leaves out every game that seats two or more seats of our policy
(any version, and any name given with `--ours`), from par too, and its header
says how many. Quote our level
and the opponent rows from the alone view, name the paired games as left
out, and say so when the alone view is too small to decide anything.

**Check our own seats before anything else.** Run the profile tool on our own
policy, on the same games:

```sh
python3 $L/tools/opponent_profile.py $A --opponent $P --variant $V --episodes $S/matchups.json --out $S/ours
```

Its header counts our tainted seats, including dead pods (`pod_deleted`;
`matchups.py` drops those games), and our seats that only held to the end.
A stalled seat of ours loses to everyone and is in every number below. Name
those episodes in the report, keep them out of the games you read for a
mechanism, and say that the tool's means include them (you cannot recompute
the means without them; say how many of our "behind" games they are). The
same output shows our order mix beside the field's at each power, which is
the quick answer to "is this about how we play that power?". Do not quote its
"vs par" numbers for us: its par is drawn from different seats than
`matchups.py`'s, and `matchups.py` is the record for scores.

When our hold share stands out beside the field's, one more command says
where it comes from:

```sh
python3 $L/tools/holds.py $A --policy $P --variant $V $O --episodes $S/matchups.json --alone > $S/holds.txt
```

It gives our hold share by version, power and year beside the field, our seats
that stopped moving, and, for a press build, the holds split by what our own
press layer committed that phase. Quote it as what we do, not as why we lose:
that a behaviour costs score is a hypothesis until an A/B tests it.

**Then the "By opponent" table.** Per opponent: our score vs par with them at
the table and without, the difference, their own score vs par, the
head-to-head count (games we finished ahead of them and behind them) and the
paired gap (our score vs par minus theirs, per game). The text table prints
each verdict to the right of its z, in the words of the JSON
(`by_opponent[].difference.verdict`, `.head_to_head.verdict`,
`.paired.verdict`); `-` means the number does not exist (no "without" games,
or too few games for an SE).

A row is a **result** when it passes two tests, in this order. Passing only
the first makes it a **lead**. Everything else is **no result**, and the
write-up says exactly that.

1. The tool's verdict: |z| ≥ 2 and at least 16 games.
2. The many-rows allowance. The table is not corrected for the number of
   rows. With k opponent rows, call a row a result only at about |z| ≥ 2.5
   for k up to 5, |z| ≥ 2.8 for k up to 12, and |z| ≥ 3 beyond (a
   Bonferroni-style allowance: the chance that some row passes by luck stays
   near 5%). An opponent the user named is still one row of the k.

Which column decides depends on how the opponents were seated:

| Seating | Use |
|---|---|
| The opponent sat in some of our games and not others, mixed within the same batches | "With − without" (`difference`) |
| Several rows show the same with and without numbers | Those opponents always sat together (one opponent set per batch). The difference is between two sets, not between opponents: it belongs to none of them. Use head to head and the paired gap inside each set |
| One row whose "with" games are one batch and "without" another (an opponent in every alone run and no paired run) | The same: a batch difference. Head to head and paired gap |
| The opponent sat in every game (no "without") | Head to head and the paired gap. "Ours with them" is then our overall score, the same in every row; it says nothing about this opponent, even at z = 3 |

Wording for the Verdict cell:

- A paired-gap verdict reads "below par" in the JSON; write "we finish behind
  them" (or "ahead").
- When the head-to-head count and the paired gap fall on different sides of a
  line, write both ("ahead on the count; paired gap lead only", "behind on
  the paired gap; count alone no result"). The paired gap is the stronger of
  the two because it uses how far ahead.
- A lead is "lead only".

Two counts that differ from the Versus section of step 2, so say which you
quote: when an opponent holds two seats in a game, `matchups.py` compares our
score with the mean of its seats, once per game, and Versus counts seat by
seat; when we hold two seats, `matchups.py` counts the game once and Versus
counts each pair. Quote `matchups.py` for the verdict and Versus for what
happened pair by pair.

Limits to state in the report when they apply: every opponent sat in every
game; many rows; and that opponent rows are associations (seats are not dealt
at random across opponents, so the power draw and the rest of the table are
mixed in).

**Choose the opponents to read games for:** those with a result or a lead,
and any the user named. With no result anywhere, read games only for an
opponent the user named or for the one largest gap, and label what you find a
lead. Two to four opponents is usual. Every other opponent gets one summary
row with "not read" as its mechanism.

### 2. The games that carry the effect

For each chosen opponent, one command gives the per-pair picture on the same
games as step 1:

```sh
python3 $L/tools/opponent_profile.py $A --opponent <opponent> --variant $V --versus $P \
    --episodes $S/matchups.json --out $S/versus-<opponent>
```

Read its "Versus" section before opening any game. (The list is every game
step 1 read, so the per-power tables above Versus also count its games
without one of our seats, and games `matchups.py` dropped for a tainted seat
of ours are in Versus, marked.)

- **Power pairs.** One row per (its power, our power), neighbours first:
  games ahead, behind and level, the mean of our score minus its score, who
  made the first hostile act, and the centres each took from the other. A gap
  that sits in one pair (we are Austria, it is Italy) is a different problem
  from one spread over all of them. A gap that sits in the pairs that are
  **not** neighbours is not something it does to us: it is its result against
  the rest of the table.
- **Other policies at our power.** The same ahead-behind count with any third
  policy in our seat. When they finish behind it as often as we do, the pair
  is about its strength at that power (or the power itself), not about our
  play.
- **Tables.** Eval batches often replay one seating many times. Eight games
  at one power pair from one table are close to one observation, and any SE
  or z on them (the `pairs` z values in the matchups JSON too) is far too
  confident. Say how many seatings a gap rests on.
- **One of our seats, or two.** The lines "games with one of our seats" and
  "games with two or more" split alone runs from paired runs. A gap that
  lives in the paired runs is about pairing, not about this opponent.
- **Tainted games.** `matchups.py` drops games where **our** seat is tainted;
  a crashed opponent seat stays in its numbers, and we "beat" a crashed seat
  every time. The line "pairs in a game where some seat is tainted" says how
  many of our ahead and behind games those are: put it in the report.
- **Episodes.** "Our worst games with it" and "Our best games with it" rank
  the neighbouring pairs that fought by our score minus its score. Each link
  opens at the autumn a centre first changed hands between the two (or, when
  none did, at the first hostile act, which may be only a bounce). Start
  there. For a loss, also read a win at the **same power pair**; every pair
  is in the saved JSON (`versus.pairs`: episode, both powers, both scores,
  `link`).

Marks on those lines, and what to do with them:

| Mark or wording | Meaning |
|---|---|
| "never made a hostile act on each other" | The cause is somewhere else on the board. Do not build this opponent's mechanism on the game |
| `[it soloed: every other seat scores 0]`, or a first centre between the two after about 1905 | The game was decided elsewhere. Print it without `--powers` and follow where its centres came from in the early years |
| `[a seat in this game is tainted]` | Some seat crashed, lost its pod or lost its LLM (ours, its, or a third) |
| `[OUR seat held to the end]`, `[its seat held to the end]` | That bot stopped playing or was locked in place. Ours: not evidence about the opponent |
| `[press audit on disk]` | Step 4 can read an audit for this game |

**Count the pattern over all the games** before it becomes a "what happened"
sentence. Three tools print what write-ups keep needing, each on the same
games with `--episodes $S/matchups.json`:

```sh
# every game of ours with this opponent: both scores, who finished ahead, first hostile act each way,
# centres taken each way, and every tainted seat in the game (matchups.py prints none of these per game)
python3 $L/tools/seat_rows.py $A --policy $P --versus <opponent> --variant $V --episodes $S/matchups.json
# "our Austria leaves Trieste empty in Spring 1901", "its Italy orders A VEN - TRI", with the field beside it
python3 $L/tools/board_counts.py $A --policy $P --as Austria --variant $V --episodes $S/matchups.json \
    --unit-at TRI --when S1901 --owns TRI --split-by Italy --rows
python3 $L/tools/board_counts.py $A --policy <opponent> --as Italy --variant $V --episodes $S/matchups.json \
    --order "A VEN - TRI" --when 1901-1902
```

Write a script in `instruments/` only for a count these cannot make, with
`opponent_profile.load_games` and `seat_facts` (the tool's docstring has the
skeleton and the shape of a phase's order rows). Give it an `--episodes FILE`
flag and pass `$S/matchups.json`, so it counts the same games and a refresh
can re-run it (`matchups.read_episode_list(Path(FILE))` returns the ids).

### 3. Read the opponent's profile, or make one

Look for `$L/reports/opponents/<opponent>.md` (`<opponent>-gunboat.md` for
gunboat). Check its date and the version it names against the version in
these games.

- Same version: use it, and note its date and game count if more games have
  arrived since. Its patterns (fixed openings, first targets) are the first
  candidate mechanisms.
- No profile, or an older version, for an opponent that beats us or has a
  lead against us: follow the
  [opponent-profile skill](../opponent-profile/SKILL.md) first.
- No profile for an opponent we simply beat: the step 2 output is enough. Say
  in the report that it has no profile.

### 4. Read the games

Open each chosen game at its link (`/replays/<episode id>?phase=N` in the
IDE), or print it:

```sh
python3 $L/tools/opponent_profile.py $A --game <episode id> --powers <ours>,<theirs> --decisions --versus $P
```

The print has the orders phase by phase with their results, retreats and
builds, the centres that changed hands, and each seat's centres by year, with
the same phase numbers as the links. `--decisions --versus $P` adds, under
each phase, the stances, trust and required orders our seat's log committed
that turn. It prints the log lines of `$P`'s seats only: when other seats'
logs are on disk the header names them as left out, and they stay out of the
write-up. For a seat of another policy of ours, run it again with that name.
`--years 1902-1904` narrows the print; a unique prefix of the episode id is
enough; leave `--powers` out to see who else was involved (and which policy
held each power: "takes from Italy" in a tool table names a power, not a
policy).

Find the phase where our centre count turned (the "centres by year" line gives
the year, the "centres changed" lines the phase). A phase number belongs to
one game: Autumn 1902 is `phase=5` in one game and `phase=4` in another,
because retreat phases shift the count. In the report, name a link by what
the print calls that phase, or link by turn, which needs no count:
`?turn=T`, where T is 2 × (year − 1901), plus 1 for Autumn (Autumn 1903 is
`?turn=5`).

For each game, collect:

| Source | What it answers |
|---|---|
| The orders around the turning phase | What happened: who moved on whom, with whose support |
| Our `decision` lines for those phases: the "committed (its log)" lines of `--decisions`. For more, `--logs` prints the seat's log path and `webdip_episodes.read_log(Path(...))` returns its rows (`event == "decision"`, with `turn` and `phase`). The replay page shows them too | Press builds: what the press layer committed (`press_policy`), so whether it overrode the search. Search builds log only counts (`trace`): skip the log, the adjudicated orders are all there is |
| Press games only: the press audit, when `.runtime/press/<episode id>/audit.json` exists | Who lied, where we were `betrayed`, where we `doubted_wrongly`, whether we broke our own word. Read the evidence beside each flagged claim before quoting a count; a count you did not check may appear only with "not checked" beside it |
| The user's annotations: `ide/ide annotations <episode id>` (or `$L/annotations/<episode id>.json`) | What an expert reader saw. Quote them as evidence, with the phase, and say they are the user's reading |

For the turning phase, `python3 $L/tools/seat_log.py $A --game <episode id>
--power <ours> --when <A1902>` prints what our seat received, what it sent,
every policy it committed that turn and the decision line, in order. It is the
quickest way to see whether the press layer chose the order that lost the
centre. It prints private press: describe it in your own words in the report.

Read only our own seats' logs. When a batch seats only our account's policies
every seat has a log on disk; a rival's log is not evidence a matchup may rest
on, because league games will not have it.

A press audit costs a sub-agent about ten minutes a game. Run one
([press-audit skill](../press-audit/SKILL.md)) for the one or two games where
the turning point looks like a broken or doubted promise, not for all six.

Read the best games as carefully as the worst. "We win when they attack
someone else first" is as useful as "we lose when they attack us".

### 5. Separate what happened from why

For each opponent write the result, then the mechanism, as separate parts:

- **Result:** the numbers from step 1, with n and the verdict, in the tool's
  words. No adjectives.
- **What happened:** what the games show, as counts where you can make them:
  "in `<k>` of our `<n>` worst games with it we held `<power>` and it took a
  home centre from us by 1903".
- **Why (mechanism):** each causal sentence carries its evidence and one of
  three confidence words:
  - **seen**: the orders, our logs or an audit show it directly in the games
    named;
  - **likely**: consistent across the games read and with the opponent's
    profile, but not shown directly;
  - **guess**: fits, with nothing that rules out the alternatives.
- **Cannot tell apart:** the candidate causes the data does not separate. "We
  are weak as Austria" and "it is strong as Italy" look the same in the
  Austria-Italy games; so do "it attacks us" and "it attacks whoever is
  Austria". The "other policies at our power" column separates some of these;
  say what data would separate the rest (a pinned-power eval, a balanced
  field eval).

With no result, the write-up leads with "no result against X in N games".
Anything the games then show goes under it as a lead, never as the reason for
a result that is not there. Leads are often about our own play rather than
this opponent (a centre we leave empty that any neighbour takes): say so.

### 6. Write the report

The file is `$L/reports/matchups/<our policy>-vs-<opponent>.md` for one
opponent and `…-vs-field.md` for several: full policy names in lower case, no
version, and `-gunboat` at the end for a gunboat write-up so it does not
overwrite the press one (`<our policy>-vs-<opponent>-gunboat.md`,
`<our policy>-vs-field-gunboat.md`). Create the folder if it is not
there (`mkdir -p $L/reports/matchups`). For one opponent, use the same
sections with a one-row summary table and a title that names it.

```markdown
---
title: Why <our policy> wins and loses, by opponent
date: <YYYY-MM-DD>
policy: <our policy>:vN
opponent: field
games: <n>
variant: classic-press
sources: <folder> (<n> games), <folder> (<n> games)
---

# Why <our policy> wins and loses, by opponent

Two or three sentences: the one or two matchups that matter and what to do.

## Summary

| Opponent | Games | Ours with them (z) | Head to head | Paired gap (z) | Verdict | Mechanism, in a phrase |
|---|---|---|---|---|---|---|

## <opponent>

**Result.** …
**What happened.** …
**Why.** … (seen / likely / guess, each with its episodes)
**Cannot tell apart.** …
**Evidence.**
- [ereq_… Autumn 1902](/replays/ereq_…?phase=5): we were <power>; …
**What to try.**
- Hypothesis: … Predicted effect: … Test: …

## What this does not show

## How this was made
```

Front matter rules:

| Field | Value |
|---|---|
| `date` | Today, Pacific Time |
| `policy` | Our policy with every version the numbers pool (`ours:v1, ours:v6`; "By version" in the tool's output lists them) |
| `opponent` | The one opponent (`name:vN`), or `field` |
| `games` | The number of our games, from the tool's header |
| `variant` | The variant id |
| `sources` | The `sources` line from the header of the step 1 profile run (`$S/ours.md`), copied as it is |

Evidence links are IDE paths, `/replays/<episode id>?phase=N`, so the IDE
makes them clickable; `N` indexes the last replay frame's `history.phases`.
The IDE link of the report is `/reports/matchups/` plus the file name without
`.md`.

Reports are tracked files: never paste private press or an audit's `quote`
text into one (the `flagged` lists in `audit.json`'s summary carry quotes
too). Cite an audit by episode, turn and category, and describe what our
`decision` lines show (a stance, an order we required) in your own words.

**Refreshing a write-up** (the IDE's "Ask the agent to refresh" button asks
for this): run every step again on the games now on disk, in a new scratch
folder, and rewrite the file.

- Compare the old and new `matchups.json` first (game counts, the `episodes`
  lists; a file saved before the tool wrote them has the ids in `our_seats`).
  If no game arrived, say so at the top; the refresh is then a
  re-check of the explanations.
- Do not carry a mechanism over without re-checking it against the new
  numbers and reading at least one game for it again (a game that arrived
  since, when there is one). Re-run the old write-up's instruments on the new
  list. A sentence you did not re-check is dropped, an explanation the new
  count contradicts is dropped or replaced, and the report says so.
- End with a short "Changes since the write-up of <old date, run time, game
  count>" section: which verdicts moved and which explanations were dropped
  or added.

### 7. Hand off the hypotheses

"What to try" lines are **hypotheses, not changes**. For each, check
[closed_levers.md](../../closed_levers.md),
[open_levers.md](../../open_levers.md) (tested, no result),
[best_practices.md](../../best_practices.md) and the records in
`experiments/`. If it was refuted before, say so in the report and name the
new evidence, or drop it. If a neighbouring idea was tested without a result,
say what that test read and what size of run yours would need.

The write-up ends there. Turning a hypothesis into a tested change is a
separate task: the [diagnosis binding](../diagnosis/SKILL.md) (core skill
`diagnose`) pins it to a code location and a predicted effect per power, and
an experiment record tests it. Offer that to the user; do not change the
policy from a write-up alone.

`$L/META.md` gets one line, with a link to the report, under "Where the field
looks weak", only for a **weakness in an opponent's play** that has a result
or was counted over all the games. First read what is there: when the
opponent's profile already wrote the line, add only what the matchup adds, or
nothing. An opponent's strength belongs in its profile, and a pattern in our
own play goes to the user and the diagnosis skill; neither goes into
`META.md` from here. With no result, leave `META.md` alone (on a refresh,
update a line the earlier write-up wrote).

### 8. Tell the user

```sh
ide/ide show --kind report --title "<our policy> vs <opponent or the field>: <the verdict in a few words>" \
  --body "<the finding in two lines, with n and z>" --link "/reports/matchups/<file name without .md>"
```

The title says what was found, "no result" included ("`<our policy>` vs the press
field: no result; one lead against `<opponent>`").

Run it whether or not the IDE is open: the card is stored and shows when the
IDE next starts. If the `ide/ide` command is not installed, skip it; the file
is the record. Either way, give the user the file's path and the summary
table in your reply.

## Pitfalls

- **A paired run is not a matchup.** With two of our seats in a game, our
  score level is off in either direction (see the ab binding). Use alone runs
  and league games for a matchup: `matchups.py --alone` leaves the paired
  games out (`alone_games` and `paired_games` in the JSON count both), and
  the Versus section's "one of our seats" line is the same view pair by pair.
- **Three games do not make a mechanism.** The games you read are examples of
  the number, not the proof of it. Count the pattern over all the games when a
  count is possible, and say when it is not.
- **The story follows the result.** After a loss every opponent move looks
  like the cause. Read a win against the same opponent at the same power pair
  and ask whether the "cause" was there too.
- **Failures first, ours and theirs.** A seat that crashed, died or lost its
  LLM loses to everyone. `matchups.py` drops only games where our seat carries
  a loader taint (a dead pod is one); crashed or dead opponent seats stay in
  its numbers. The profile tool's headers count both (step 1 for ours, step 2 for
  theirs). Check them before explaining anything with strategy.
- **Who struck first is a weak fact.** "First hostile act by us" can be a
  fleet bouncing off a fleet that had sat on our border for a year. Open the
  phase before writing "we attacked".
- **Press and gunboat are not one matchup.** One variant per write-up.
- **Versions.** Name ours and theirs. A write-up about `v3` is history after
  `v4` ships; say in the summary which versions it covers.
- **A report that a later count overturned must be corrected in the file.** A
  correction that lives only in a chat message leaves the tracked report
  teaching the old claim. When a later check reverses a sentence, edit the
  report: strike the claim, add a dated line under "Changes" saying what
  replaced it and where the count is.
- **A lead about our own play is not this opponent's doing.** A habit of ours
  that shows against every opponent is not the reason we finish behind one
  policy. Say so and hand it to the diagnosis skill.

## Handoffs

- **Uses** `matchups.py` (the numbers), the
  [opponent-profile skill](../opponent-profile/SKILL.md) and its tool (how
  they play, and the per-pair picture), the
  [press-audit skill](../press-audit/SKILL.md) (who lied) and the
  [replay-inspection binding](../replay-inspection/SKILL.md) (the formats).
- **Feeds** [diagnosis](../diagnosis/SKILL.md) with hypotheses, `META.md`'s
  "Where the field looks weak" with a one-line pointer when an opponent's
  weakness has a result, and the user's choice of what to work on.
