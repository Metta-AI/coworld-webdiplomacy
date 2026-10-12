---
name: webdiplomacy-ide
description: >
  Open and use the optimizer's local web IDE: a browser workbench where the
  user watches replays, marks where a game went wrong, reads the results
  dashboard and reports, and chats with this session. Use when the user says
  "open the IDE" (or asks to see a replay, a result or a report in the
  browser), when a hook hands you a message that starts with
  `[webDiplomacy IDE]`, when you have something
  worth showing (an idea, a replay to look at, a result), and before a
  diagnosis, to read the user's annotations.
---

# The IDE — webDiplomacy

The IDE is a local web page served from this machine. **You come first: you
start it, and it attaches to this session.** The user reads and types in the
browser; you read and answer with the `ide/ide` command. Run every command
from the optimizer root.

## Open it

```sh
ide/ide start --open     # starts the server in the background, prints the URL, opens the browser
```

**Tell the user the URL first**, before any note-taking or fetching
(`ide/ide url` prints it again). `ide/ide status` shows whether the server is
up and whether something is waiting for the user's messages. `ide/ide stop`
closes the IDE when the user is done. `start` on a running IDE only prints its
URL.

`start` chooses the port: the one this lab used last, else 8642, and when
another lab's IDE already holds that one, the next free port (it prints a
note). So a second lab on the same machine needs nothing from you, and a
restart comes back at the address the user's tab already has. `--port N`
forces a port.

The pages update themselves: new games, cards, reports and a finished audit
appear without a reload, and an open tab reconnects by itself after the server
restarts. Do not tell the user to refresh.

When the user says which policy is theirs ("my policy is X"), or you learn it
from an upload, record it so every page follows that policy:

```sh
ide/ide follow <policy name>     # no name: print the recorded one
```

Without it the pages follow what this lab uploaded last, and in a lab that has
uploaded nothing they guess. The newer choice wins: `follow` replaces a policy
the user picked in the browser earlier, and a pick they make in the browser
afterwards wins again. So run it when the user tells you, not at every start.

## How the user's messages reach you

You do not poll. A message typed in the browser is handed to you by this
session's hooks, as text that starts with `[webDiplomacy IDE]`, and each
message arrives once:

| You are | How it arrives |
|---|---|
| Idle at the prompt | A background hook wakes you with the message ("Stop hook feedback", or worded as a hook "blocking error": that is how the harness labels a delivery, not a fault) |
| Busy in a turn | The same, or it is added to your context after your next tool call |
| About to stop | The Stop hook holds the turn open and gives it to you |
| Interrupted (the user pressed Esc in the terminal) | The same background hook wakes you: the next message written to the chat file starts it again |

Only one Claude Code session in this folder gets the messages: the one that ran
`ide/ide start`, or the first to act once the IDE was open. `ide/ide status` names it.
If the user says their messages are going unanswered and another session is open in
this folder, run `ide/ide attach` in the session that should have the chat, as a
command of its own: it takes effect when the command returns, so check with
`ide/ide status` in the next command, not the same one.

Every time you receive one:

1. **Answer in the browser:** `ide/ide say "..."`. The user is not reading the
   terminal. Say what you will do before long work, and say when it is done.
2. Do the work. Post a card for anything the user should be able to find again.
3. **Everything meant for the user goes to the browser**: progress during a
   long job (one `say` each time the plan or the wait changes, for example
   "84 games to download, about three minutes"), the full answer, and above
   all any choice or question you have for them. A list of options that
   appears only in the terminal is a question nobody was asked. End the turn
   in the terminal with one line ("answered in the IDE").

`ide/ide inbox` prints anything unread on demand and marks it delivered
(`--peek` prints without marking); `ide/ide inbox --recent 5` prints the last
five messages again if you lost one. The background hook keeps waiting while
the IDE server is stopped, so you may stop and start the server freely.

**If the Stop hook says nothing is waiting** (the hooks are missing, or the
harness is not Claude Code), run the listener yourself as a background task
(Bash with `run_in_background: true`):

```sh
ide/ide listen           # waits; prints the user's next message and exits (--timeout S gives up after S seconds)
```

Its exit calls you with the message. It exits after every delivery, so start
it again each time.

A message can carry what the user was looking at (`looking at: episode …,
phase …`) and the annotations they attached. Use them: answer about that
game and that phase.

## Show things

```sh
ide/ide say "Fetched <n> games; <the finding in a line>. Card posted."
ide/ide show --kind replay --title "<what happened, with the power and the season>" \
  --body "<what we relied on, and what the phase shows>" \
  --link "/replays/<episode id>?turn=<t>"
ide/ide show --kind result --title "<vN> vs <vM>: <the verdict> (z = <z>, n = <n>)" --body-file notes.md \
  --link "/experiments/<id>"
```

- `say` is a chat line. `show` posts a **card** that stays in the Cards tab:
  use it for anything the user should be able to find again.
- Kinds: `idea` (a hypothesis or proposed change), `replay` (a game and phase
  worth watching), `result` (a measured outcome, with n and z), `report` (a
  write-up), `note`.
- The body is Markdown. Keep it short; lead with the finding.
- `--link` takes an IDE path (it must start with `/`) or a full `http(s)` URL:
  - `/replays/<episode id>?seat=<slot>&phase=<n>`: the viewer at one phase. `n`
    indexes the last replay frame's `history.phases`; `seat` is the roster slot
    to follow. The episode id is the episode directory's name.
  - `/replays/<episode id>?seat=<slot>&turn=<t>`: the same, at the movement
    phase of turn `t` (0 is Spring 1901, 1 is Autumn 1901; `t` is
    2 × (year − 1901), plus 1 for Autumn). Use it whenever you name a year and
    a season: a `phase=` number counted by hand is off by one as soon as the
    game has a retreat phase. Use `phase=` only with a number a tool printed
    for that game.
  - `/replays?policy=<name>&opponent=<name>&sort=score`: the game list, filtered.
  - `/dashboard`, or one view of it:
    `/dashboard?policy=<name>&variant=classic-press&alone=1`. Also `version=vN`,
    `source=league|xp|local` and `opponent=<name>`. `alone=1` keeps only the
    games with one seat of the policy, which leaves out paired A/B games.
  - `/reports/matchups/<slug>` and `/reports/opponents/<slug>`: the slug is the
    report's file name without `.md`.
  - `/experiments/<id>`: one experiment record (the id is the record's file
    name without `.md`), with the paired result of the games on disk beside it.
    `/experiments` is the list.
- Before a card or message calls a policy "ours", "yours" or "the earlier
  version", check it against `VERSION_LOG.md` and the followed policy. A house
  bot can carry a name like ours and is still an opponent (lab manual, "Whose
  policy is whose", says where to look).
- A card stays as posted. Leave out what you did not check, or mark it "not
  checked". A count from a tool that nobody read (press-audit flags) is given
  as "by the tool's count, not read". If a card turns out wrong, post a
  correcting card that names it.
- When the user asks how their policy is doing, say which games the number is
  from (alone runs or all, how many, how many dropped), and use the same cut
  as the card's link (`/dashboard?…&alone=1`).
- Link a card to what backs it. A `result` card for an experiment links to its
  record (`--link /experiments/<id>`), so the user reads the number beside the
  rule it was to be read against. An `idea` card links to its proposed
  experiment record; see the next section.

## An idea is a proposed experiment

When you have a change worth testing (from the user's notes, a report, a
diagnosis), **write it down as an experiment record with `status: proposed`
before you post the card**. Do not keep it only in `WORKING_CONTEXT.md` or in
the chat: the Experiments page is where the user looks for what could be run
next, and a proposed record costs nothing.

```sh
uv run skills/experiment/scripts/record.py new games/webdiplomacy <short-slug>   # prints the file; its name is the id
```

Fill the front matter now: `policy`, `baseline` (the current version),
`candidate: n/a`, `status: proposed`, the `hypothesis` in one sentence, the
`decision_rule` with the number of games ("+0.08 or more with z >= 2 over 28
balanced paired games"), and `cost:` in plain words (games, credits and time,
for example `28 press games, 62 credits by the platform's estimate, about 70 minutes`). Write the
Context (the evidence, with links, and that `closed_levers.md`,
`open_levers.md` and the earlier records in `experiments/` were checked, with
the nearest earlier test named)
and the two predictions. Build nothing and launch nothing. Then post the card:

```sh
ide/ide show --kind idea --title "<the one change, in a few words>" \
  --body "<the evidence, with its count and the tool that printed it>. How it scores alone: [the dashboard](/dashboard?policy=<name>&alone=1)." \
  --link "/experiments/<id>"
```

The Experiments page lists the record at once: its hypothesis, the rule, the
cost, and a "Run this" button. That button and the card's "Test this idea"
send you the same request: check `closed_levers.md`, `open_levers.md`, the
earlier experiment records and this record once more, say the cost, build the
one change (`tools/ship.py --experiment <id>`), write the candidate in the
record, run `tools/run_ab.py --record <id>` and a health game, and post a
`result` card that links to the record. An idea the user turns down stays as a
proposed record; do not delete it.

Two keys of the record are this lab's own (the seed's `record.py validate`
accepts them):

- `cost:` what a run would spend, shown while the record is proposed.
- `artifacts: [<folder>, …]` more folders to read the result from. A record's
  result is read from its own folder, `.runtime/artifacts/<record id>` (where
  `tools/run_ab.py` fetches; always read), plus any folders the front matter's
  `artifacts: [folder, …]` lists (names under `.runtime/artifacts`, with or
  without that prefix), listed ones first. `tools/run_ab.py` and the IDE's
  Experiments page use the same rule. Nothing in the record's body is read;
  games fetched by hand into another folder must be listed in `artifacts:`.
  Leave it empty for a normal record. Fill it when the decision rule pools
  this record's games with an earlier record's (a follow-on run that extends
  one): list the earlier record's id. `run_ab.py` then prints the pooled
  `paired.py` read, and the Experiments page shows the pooled number and how
  many games each folder gave.

## Annotations are input to the loop

In a replay the user marks phases: `blunder`, `missed-alliance`, `bad-trust`,
`good`, `suggestion`, `question`, `note`, with a phase and often a power and a
territory. They are stored in `games/webdiplomacy/annotations/<episode id>.json`.

```sh
ide/ide annotations                 # all of them, by episode (--json for the raw rows)
ide/ide annotations <episode id>
ide/ide annotate <episode id> --phase 9 --tag bad-trust --power TURKEY --territory BLA --text "…"   # your own
```

Treat them as evidence from an expert reader, not as orders:

- Read them **before** a diagnosis or a new experiment. A `blunder` or
  `bad-trust` mark names a phase to inspect with the replay-inspection skill.
- One annotated game is an anecdote. Check
  [closed_levers.md](../../closed_levers.md),
  [open_levers.md](../../open_levers.md) and the earlier records in
  `experiments/` (name the nearest earlier test), then turn a `suggestion` into a
  proposed experiment record and an idea card that links to it (see "An idea
  is a proposed experiment"), and measure it like any other change once the
  user says go. Tell the user what you did with it in the chat.
- Answer a `question` in the chat, with the phase link.

## What the user can ask for from a page

Some buttons send a ready-made request. It arrives like any other message,
with the page's context, and names the skill to use:

| Asked from | The request | Answer it with |
|---|---|---|
| A replay with no audit of the followed seat | A press audit of that game for the followed seat | [press-audit](../press-audit/SKILL.md); see the next section |
| The dashboard's opponent table | Why our policy wins or loses against one opponent | [matchup-writeup](../matchup-writeup/SKILL.md) |
| Reports, a policy with no profile | An opponent profile of that policy | [opponent-profile](../opponent-profile/SKILL.md) |
| Reports, when no write-up exists yet | A matchup write-up against the whole field | [matchup-writeup](../matchup-writeup/SKILL.md) |
| A report, in the list or open | Refresh it: run the report's skill again on the games now on disk and rewrite the file | The skill that wrote it: opponent-profile for `reports/opponents/`, matchup-writeup for `reports/matchups/` |
| A replay's notes | The user's notes on that game, each with a link to its phase | Read them as below; inspect the phases with [replay-inspection](../replay-inspection/SKILL.md) |
| An idea card ("Test this idea"), or a proposed record ("Run this") | Run that proposed experiment: say the cost, the one change as a new version, a paired A/B, a health game, a result card. For a card with no record: write the proposed record first | The seed's `experiment` skill for the record, then [ab](../ab/SKILL.md) (`tools/ship.py --experiment <id>`, `tools/run_ab.py --record <id>`) |
| An experiment that is running | Its result so far, read against the record's decision rule | The seed's `ab-compare` skill with the lab's [ab](../ab/SKILL.md) binding (`tools/paired.py` on `.runtime/artifacts/<id>` and any folders its `artifacts:` lists) |
| An experiment with no verdict yet | Close the record: Result, Verdict and status, and `closed_levers.md` if it is refuted, `open_levers.md` if it is inconclusive | The seed's `experiment` skill (step 6, then `record.py validate`) |
| An experiment whose games show a paired win | The candidate-alone check, with its pass mark written in the record first | `tools/run_ab.py --record <id> --alone`; see [ab](../ab/SKILL.md) |

The request buttons each start ten minutes of work, and a user can press three
in two minutes. Give the audit's annotation and a profile to sub-agents at
once, say in the chat what is queued and in what order, and keep answering
chat messages first.

Say in the chat that the work has started. When the file is written, post a
card that links to it (`--kind report --link /reports/…`, `--kind replay`
for an audit, or `--kind result --link /experiments/<id>` for an experiment).
The Reports page lists a report as soon as its file exists under
`games/webdiplomacy/reports/`, and the Experiments page a record as soon as its
file exists under `games/webdiplomacy/experiments/`. That page shows the user
each record's status, hypothesis and decision rule, a proposed record's cost,
how many of a running record's games are in, and `paired.py`'s number for
them, so keep the record's front matter current: `status: proposed` from the
idea on, `status: running` when the batches launch (`run_ab.py` sets it), and
close it when the verdict is read.

## Press audits run on demand

The replay page overlays the press audit (who lied, who was betrayed) when
`.runtime/press/<episode id>/audit.json` exists. It is not run for every game:
one audit costs a sub-agent about ten minutes. When the user asks from a replay
("audit this game"), follow the [press-audit skill](../press-audit/SKILL.md)
for that episode, say in the chat that it has started, and post a `replay` card
linking to the game when `audit.json` is written.

An audit belongs to one seat, but the folder is named after the episode, so a
game holds one audit at a time. When two of our seats sit in one game (a paired
run, or a table we own entirely), the replay page shows the audit only while its
seat is followed; on the other seat it says whose audit it is and links there,
and shows none of its counts or quotes. Auditing the second seat replaces the
first (`press_audit.py extract --slot N --force`), so say so before doing it,
and copy the first folder aside if the user wants both.

## Time

You have no clock. Before you say how long something took, how long the user
has waited or how much of their session is used, run `date`.

## Limits

- Local only: the server binds to 127.0.0.1 and has no login. The IDE shows
  private press; do not expose the port.
- The hooks need Claude Code 2.1.296 or newer (tested there). If the session
  ends, the chat stays on disk (`.runtime/ide/chat.jsonl`) and the next session
  is handed the unread messages.
- If Bash is not available, the same actions are MCP tools on the `webdip-ide`
  server: `say`, `show_card`, `inbox`, `annotations`, `annotate`, `status`
  (they work in a Claude Code session; with Bash, prefer `ide/ide`, which has
  more commands). An MCP tool cannot wake an idle session.
