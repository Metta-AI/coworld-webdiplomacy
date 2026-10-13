---
name: webdiplomacy-opponent-profile
description: >
  Work out how one opponent policy actually plays, from the public orders in
  our replays: its openings by power, whom it attacks first and when, where it
  expands, how it defends and how its games end, and how it treats our policy.
  Writes a dated profile to reports/opponents/. Use when the user asks "how
  does X play" or "what is X's strategy", when one opponent keeps beating us
  or a new version of it appears, before a matchup write-up, before designing
  a counter, or when META.md's row for a policy is empty or old.
---

# Opponent profile — webDiplomacy

`META.md` is the picture of the whole field, one row per policy. This skill
produces the **deep dive behind one row**: a dated file,
`reports/opponents/<opponent>.md`, that says what one opponent does, with the
counts and the games that show it, and what we could do about it. `meta-recon`
decides who is worth profiling and cites the profile from `META.md`; it does
not repeat it.

The work is split the way the press audit is: **code counts, you read and
explain.** `tools/opponent_profile.py` measures every order the opponent gave.
You open the games, decide what the counts mean, and write claims that each
carry their evidence. Nothing goes into the profile that a reader cannot check
against a number or a replay.

## What can and cannot be seen

- Every power's adjudicated orders, units, centres and public press are in
  every replay. That is the whole evidence base.
- An opponent's private press with other powers, its logs and its reasons are
  **not** readable for a rival. When a batch seats only our own account's
  policies, every seat's log is on disk. The tool then uses the logs for one
  thing: taint (a crashed seat, a dead pod, failing LLM calls). Do the same: a profile
  rests on orders, so it means the same thing for every opponent. If you do
  read a log for a reason, say in the report that this opponent's logs were
  readable.
- Our own seats' private press with the opponent is readable, through the
  [press-audit skill](../press-audit/SKILL.md).

## Method

From the optimizer root. `L=games/webdiplomacy`, `A=$L/.runtime/artifacts`,
`V` is the variant id (step 1).

### 1. Pick the opponent, the variant and the games

```sh
python3 $L/tools/matchups.py $A --list          # policies in the data, with versions and games
```

Profile **one variant at a time**: press and gunboat are different games with
different last years, and a press policy in a gunboat game plays its fallback.
The ids are `classic-press` (the main "webDiplomacy" league) and
`classic-gunboat` (the "webDiplomacy Gunboat" league). `--list` counts games
over every variant unless you add `--variant`; the profile's header gives the
count for the one you chose. Name one version (`NAME:vN`) when the data holds more than one and they
may differ; a bare `NAME` pools them.

### 2. Run the tool

```sh
python3 $L/tools/opponent_profile.py $A --opponent <name>[:vN] --variant $V \
    --versus <our policy> --out $L/.runtime/opponent-<name>-$V
python3 $L/tools/matchups.py $A --policy <our policy> --variant $V --opponent <name> \
    --episodes $L/.runtime/opponent-<name>-$V.json
```

`--out` saves the text (`.md`) and the same numbers as JSON (`.json`, with the
list of episodes read). **Work from that one saved run.** While games are
still being fetched a second run reads more games and every count moves; to
repeat the run, or to check something in your own script on the same games,
pass `--episodes $L/.runtime/opponent-<name>-$V.json`.

The second command is the score between us and them, on the games the first
one read (`--episodes`; its `--opponent` takes the name without a version).
The profile's "Versus" section describes behaviour and does not judge the
score. From its "By
opponent" row quote the head-to-head count and the paired gap with their z:
|z| < 2 is "no result" and fewer than 16 games is "too few games" (a row
there may carry a `lean`: a lead to play more games for, never a result). `matchups.py`
drops the games where one of our seats is tainted and the profile keeps them,
so its game count can be lower: give its game count beside its numbers. The
two tools will not agree exactly on "vs par" (par is
drawn from slightly different seats) or on ahead and behind (Versus counts
seat pairs, `matchups.py` counts games). Use the profile's numbers for how the
opponent does and `matchups.py`'s for anything about us.

Read the whole output once. The tool's docstring defines every measure
(`python3 $L/tools/opponent_profile.py --help`: definitions first, flags at
the end). What to look for:

| Section | What to look for |
|---|---|
| Header | Seats and games, versions, sources, twin games, tainted and stalled seats (below), and the powers it never played (no row, so no claim) |
| Results by power | Where it is above or below the field at the same power, and how its games end. `*` marks fewer than 16 seats: means and rates are directional only, though "8 of 8" still stands as what happened. `tables` is how many different seatings its games at that power had |
| Openings | One Spring 1901 order set in every game at a power means a fixed opening. Then read how many of the field's seats at that power play the same set: when most do, it is the shared default and not a habit of this opponent. Several sets means it varies (an LLM, a sampled search, or press) |
| Whom it attacks | Its first target per power and the season of the first hostile act (two powers hit in the same first turn both count, so the counts can sum past n). "In reply" counts the games where that power had hit it first: a target it only ever answers is not a target it chooses. A first target that never changes is a commitment we can punish or avoid |
| Centres taken and lost | Where it grows, who takes its centres, its fleet share, and its order mix beside the field's at the same power (a hold share means something only beside the field's at the same power) |
| Centre trajectory | When it pulls ahead of or falls behind the field: opening, midgame or the last years |
| Versus | Our versions, how many shared games held two of our seats, who struck first between it and us, whether we were its first target, what we took from each other, and how other policies in our seat did beside it |
| Episodes to open | The games for step 3, as IDE links |

**Seats that were not the policy playing.** Three header lines say which games
to read with care. The first and third name their first six episodes, and all
are in the JSON; the second is a count, and its games carry the mark
`[another seat tainted]` in "Episodes to open".

- *Its tainted seats.* `llm_failing`, `no_decisions` and `pod_deleted` (the
  seat's pod died; its log holds one line, "No logs collected for pod") mean
  the seat played a fallback or nothing: do not read those games as its
  strategy, and say in the profile how many there were. A pod can die late:
  the "only held" line below gives how many phases each seat stood still, and
  its orders before that are still its own. `exception` needs a
  look at when: some bots throw on every phase once their last unit is gone,
  and the header says how many seats tainted only by `exception` ended with no
  centres. Those
  games were the policy's own play until it was eliminated. Keep them, or you
  drop its worst results and flatter it.
- *Its seats beside another policy's tainted seat*, with its score there and
  elsewhere. A neighbour that crashed is free centres, so its best games are
  often among them.
- *Its seats that only held* in their last four or more movement phases, with
  the number of units each still had. Orders cannot say whether that is a
  dead bot or a locked position (one unit holding a last centre is usually
  the latter). Print the game: if every unit holds from some phase to the end
  while neighbours walk in, treat it as a dead seat and say so. When its log
  is on disk (`--game <id> --logs` gives the path), a last `decision` line
  many turns before the end settles it.

Links in "Episodes to open" carry the marks `[its seat tainted]`,
`[another seat tainted]` and `[held to the end]`.

### 3. Open three to five games

The counts say what happened on average. They do not say what the opponent
was doing. Pick **different** games from "Episodes to open": at least one for
each power you will make a claim about, and at least one game that
**contradicts** the pattern you think you see ("does not fit the usual first
target", "unusual opening"). Three to five games is enough for one or two
powers; a profile that makes claims at six powers needs more, read more
briefly. A profile built only from the best and worst games tells a story the
middle games do not support. Prefer games without a taint mark.

For each, read the orders phase by phase:

- With the IDE running, open the link (`/replays/<episode id>?phase=N`).
- Without it, print the game (same phase numbers as the links):

  ```sh
  python3 $L/tools/opponent_profile.py $A --game <episode id> --powers Turkey,Russia --years 1901-1903 --versus <our policy>
  ```

  `--versus` marks our seats "(ours)" in the seat list and on their order lines.

  Leave `--powers` out for all seven and `--years` out for the whole game; a
  unique prefix of the episode id is enough. `coworld replay-open <episode id>
  --hosted` opens the hosted viewer for the user.

Write down what you see as you go: the phase, the orders, what they achieved.
These notes are the evidence lines of step 4. Three checks to make while
reading, because the counts cannot make them:

- **Was the "first hostile act" a real attack?** It can be a bounce in a sea
  province, mutual (Austria and Italy both ordering into Trieste and Venice
  in Spring 1901 is each "attacking first"), or a counter-attack on a neutral
  centre the other power had just taken from it (the tool leaves out moves
  into its own centres, and marks replies, but cannot see every case).
- **Did the centres it took from a power come from an attack, or from a
  neighbour that had already collapsed?**
- **Did a rival solo?** A solo zeroes every other seat; its "worst game" may
  say nothing about its own play.

**Check each claim over all games, not five; do not eyeball it.** Three tools
count what profiles keep needing, each with the field beside the opponent and
each taking `--episodes $L/.runtime/opponent-<name>-$V.json` so it counts the
same games as the profile:

```sh
# an order, a centre, a unit: "as Turkey it opens F ANK - BLA and owns Sevastopol after 1902"
python3 $L/tools/board_counts.py $A --policy <name> --as Turkey --variant $V --episodes <saved>.json \
    --order "F ANK - BLA" --when S1901 --owns SEV --split-by Russia
# any move into a province, over a year: "it goes for Holland in 1902"
python3 $L/tools/board_counts.py $A --policy <name> --as England --variant $V --order "* - HOL" --when 1902 --rows
# how much it holds, by year, and the seats that stopped moving (a dead bot or a locked position)
python3 $L/tools/holds.py $A --policy <name> --variant $V --episodes <saved>.json
# the seats themselves, worst first: taint, first targets, home centre lost, who sat beside it
python3 $L/tools/seat_rows.py $A --policy <name> --as Russia --variant $V --versus <our policy>
```

`--split-by POWER` answers "only beside one neighbour?", which eval batches
that replay one seating make the first question to ask.

In the `seat_rows.py --versus` lines the two policies are written by name
("<name> finished behind; first hostile act: <our policy> on <name> Spring
1902, …"), so the same line reads the right way round here, where `--policy`
is the opponent, and in a matchup write-up, where it is ours.

Write a script in `instruments/` only for what those cannot count (a supported
attack and how the defender answered; a retreat onto a home centre). The
profile tool's docstring has the import skeleton, the fields of `seat_facts`
and the shape of a phase's order rows. Give the script an `--episodes FILE`
flag and pass the saved run
(`load_games(..., only=read_episode_list(Path(args.episodes)))`) so it counts
the same games as the profile, the field's included, and a refresh can re-run
it. In the loader's order rows a hold always has `success: false`: do not count
holds as failed. Keep the script in `instruments/` (tracked), not in a scratch
folder, or the refresh cannot find it.

### 4. Write claims, not impressions

Every claim in the profile has four parts:

| Part | Contents |
|---|---|
| **Pattern** | What it does, as a rule a reader could falsify: "As `<power>` it opens `<order set>` and makes its first hostile move on `<neighbour>` in Autumn 1901" |
| **Evidence** | The count with its n, and the episodes with phase links: "`<k>` of `<n>` games; `/replays/ereq_…?phase=1`". Say which part you counted and which you saw in the games you opened |
| **What we could exploit** | The gameplay consequence for us, or "nothing we can use" |
| **How to test it** | The experiment that would show the exploit pays: the change (in words is enough here; the diagnosis skill turns it into a setting or a code location), the power it should move, and the opponent set. Or "not worth a test" with the reason |

Three to six claims is a good profile. "It is aggressive" is not a claim;
"it attacks a neighbour's centre by Spring 1902 in `<k>` of `<n>` games as `<power>`"
is. Where the counts show no pattern, write that: "its `<power>` opening varies (`<k>`
order sets in `<n>` games); nothing to plan against" is a finding.

### 5. Write the report

The tool prints the path on its last line: `$L/reports/opponents/<slug>.md`
for the main league, where `<slug>` is the policy name in lower case without
the version (anything that is not a letter or a digit becomes `-`), and
`<slug>-gunboat.md` for a gunboat profile, so the two do not
overwrite each other. Create the folder if it is not there
(`mkdir -p $L/reports/opponents`). One file per opponent and league: when you
profile a new version, rewrite the file and keep the old findings that still
hold in a "Since the last profile" section.

**Refreshing a profile** (the same versions, more games; the IDE's "Ask the
agent to refresh" button asks for this): run every step again on the games now
on disk and rewrite the file.

- Save the new run under a new prefix (`--out $L/.runtime/opponent-<name>-$V-<HHMM>`)
  so the old run's files stay for the comparison. Compare the two `episodes`
  lists first and say in the report whether games were added (when the old
  JSON has no list, compare game counts and sources).
- Do not carry a claim over without re-checking its count on the new run.
  Re-run the old profile's instrument on the new episode list; a claim you
  could not re-check is dropped, and one the new count contradicts is dropped
  or replaced, and the report says so under "Changes". When the tool now
  marks seats it did not mark before (dead pods, stalled seats), split any old
  count that rests on another seat's orders by that mark.
- End the file with a short "Changes since the profile of <old date, run
  time, game count>" section: which counts moved, and which patterns were
  dropped, added or reversed. If nothing changed but the counts, say that.
- In `META.md`, edit the lines the old profile wrote; do not add second ones
  (step 6 says who makes the edit).

```markdown
---
title: How <opponent> plays
date: <YYYY-MM-DD>
policy: <our policy>:vN
opponent: <opponent>:vN
games: <n>
variant: classic-press
sources: <folder> (<n> games), league-press (<n> games)
---

# How <opponent> plays

One paragraph: what kind of player this is and the one thing to remember.

## Summary

| As | n | Opening | First target | Result vs field |
|---|---|---|---|---|

## Patterns

### 1. <the pattern, as one sentence>

- **Evidence:** <k> of <n> games as <power>. [Autumn 1901](/replays/ereq_…?phase=1), …
- **What we could exploit:** …
- **How to test it:** …

## Against us

What the Versus section shows, and what the games you opened add.

## What this profile does not show

Small cells, tainted seats, twin games, anything you looked for and could not
see in orders.

## How this was made

The command, the date, the versions, the games opened.
```

Front matter rules: `date` is today in Pacific Time; `opponent` names the
version or versions profiled (`name:v2`, or `name:v2, name:v3`); `policy` is
our policy when `--versus` was used, with every version the Versus header
lists (`ours:v1, ours:v6`), else leave it out; `games` is the game count from
the tool's header; `variant` is the variant id; `sources` is the header's
`sources` line, copied as it is (directories under `.runtime/artifacts/`).
Links to replays are written as `/replays/<episode id>?phase=N` so the IDE
makes them clickable. `N` is the phase number the tool printed for that game;
when you have only the year and season, write `?turn=T` (T is
2 × (year − 1901), plus 1 for Autumn), because a phase number counted by hand
is wrong in any game with a retreat phase. Never paste private press into the report: reports are
tracked files.

### 6. Update META.md

**Only the main agent edits `META.md`.** If you are a sub-agent (one profile
among several being written at the same time), do not open `META.md` for
writing: several writers of one file overwrite each other. End your reply with
a "META lines" block instead, holding the row cell and any weak-point line in
the wording below, each ready to paste, and say that you did not edit the
file. The main agent places the lines from every profile in one edit after
the sub-agents have finished.

In `$L/META.md`, set or add the opponent's row in "Who is in the field": the
"How it plays (and how we know)" cell gets **one sentence and a link**:
`<the one thing to remember> ([profile](reports/opponents/<slug>.md), <date>, <version>, <n> games)`.
The row's other cells ("Entrant or filler", "Seen in rounds") belong to
`meta-recon` and come from `tools/field.py press|gunboat`: fill them from its
output if you run it, otherwise leave what is there or write "not checked".
An exploitable pattern also gets one line under "Where the field looks weak",
again with the link. Do not copy the profile into `META.md`. Re-read the file
just before you edit it and change only this opponent's lines.

### 7. Tell the user

```sh
ide/ide show --kind report --title "Profile: <opponent>" \
  --body "<the one thing to remember, with n>" --link "/reports/opponents/<slug>"
```

Run it whether or not the IDE is open: the card is stored and shows when the
IDE next starts. If the `ide/ide` command is not installed, skip it; the file
is the record. Either way, give the user the file's path and the
one-paragraph summary in your reply.

## Pitfalls

- **Small n per power.** Seven powers split the games by seven. Eight games at
  a power is a handful; "3 of 4" is an observation. Give n with every count.
  On a `*` row (fewer than 16 seats) a count that is all or nothing ("8 of 8
  games open the same way") is a fair pattern; a mean or a rate (score vs par,
  "attacks Russia first in 5 of 8") is directional only, and the profile says so.
- **The same table every game.** Our eval batches often pin each policy to a
  power and replay that seating, so the opponent's Turkey always met the same
  Russia. `tables` in "Results by power" shows it. With one or two tables,
  "it attacks Russia first" may mean "it attacks that Russia first", and the
  standard errors are too small (the games are near copies). Say how many
  tables a pattern rests on, and prefer league games and balanced field evals.
- **A shared default is not a habit.** Bots built on the same search open the
  same way. If the field plays the opponent's opening too, there is nothing
  opponent-specific to counter; the finding is about the field. The same holds
  for any behaviour, not only openings. **Put the field's number
  beside every rate before it reaches the summary, the card or `META.md`**
  (`board_counts.py` and `holds.py` print it), and write the headline last.
- **Its best game may be its usual game beside weak or dead neighbours.** Open
  the best game as the contradicting case before writing "it varies", and look
  at `seat_rows.py`'s "other seats tainted" for it: a seat beside a dead pod
  collects free centres.
- **Version drift.** A profile describes the versions it names on the date it
  names. When `tools/field.py` or the header shows a new version, the profile
  is history until you re-run it. Check the date before you rely on one.
- **Paired and twin games distort behaviour.** With two of our seats, or two
  of its own, in one game, the opponent meets a different table from a league
  game. The header counts its twin games and the Versus header counts shared
  games with two of our seats. If they are most of the data, say so, and
  prefer games where each sat once.
- **LLM opponents vary game to game.** A scripted bot repeats itself; an LLM
  bot's opening can change with the press it received. Distinct order sets in
  Spring 1901 are the test. Do not plan a counter against a pattern that holds
  in 60% of games as if it held in all of them.
- **A hostile act is not always hostile, and an approach is not counted.**
  The tool counts a move into a province where another power has a unit or
  owns a centre. An arranged swap, a bounce at sea or a supported entry into a
  friend's centre counts; a fleet moving next to a neighbour's home centre
  (into an empty province that is not a centre) does not, though it is how
  most attacks begin. Open the game before calling a power its "first target"
  or saying who started it.
- **The last autumn's captures are missing.** The replay does not show who
  owned which centre after the final autumn, so "takes", "loses" and "home
  centre lost" stop a year early (a power can go from 3 centres to 0 in the
  year you cannot see). Final counts, scores and eliminations are right (they
  come from `results.json`).
- **"Failed" is a share of all orders**, holds included, not the share of
  moves that bounce. Quote it with that wording.
- **Orders show what, never why.** A profile says "it does X". "Because it
  believes Y" needs its press or its logs, and we have neither for a rival.
- **The field is in the numbers.** "Score vs par" compares it with the other
  policies in the same games. Against a different table it will differ.

## Handoffs

- **`meta-recon`** cites the profile from `META.md` and decides which
  opponents need one. Its Match / Counter / Sidestep choice starts from the
  "What we could exploit" lines.
- **[matchup-writeup](../matchup-writeup/SKILL.md)** reads the profile to
  explain why we win or lose against this opponent.
- A "How to test it" line becomes a hypothesis: take it to
  [diagnosis](../diagnosis/SKILL.md) and a `proposed` experiment record, after
  checking [closed_levers.md](../../closed_levers.md),
  [open_levers.md](../../open_levers.md) and the records in `experiments/`.
