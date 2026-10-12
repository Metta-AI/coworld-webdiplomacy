# webDiplomacy optimizer (prototype)

Tooling to improve webDiplomacy policies with
[optimizer-seed](https://github.com/Metta-AI/optimizer-seed). This directory is
the **source**. Nobody runs it from here: `install.sh` copies it into a
standalone optimizer repository owned by the user.

**Status: prototype.** `install.sh` works, `mixin/` is filled and `ide/` is a working
first version (2026-10-11). `INSTALL.md` is planned and does not exist yet.

## What is here

- **`mixin/`**: the webDiplomacy game mixin for optimizer-seed. It follows the
  seed's `games/_template/` contract: `MIXIN.md`, the lab manual
  (`AGENTS.md`), the five required skill bindings (`ab`, `survey`,
  `replay-inspection`, `eval-design`, `diagnosis`), game docs, analysis and
  campaign tools in `tools/` (one-command build-upload-log and A/B runs, request
  builders, sizing, `matchups.py` for score by power and opponent, `fetch_league.py`
  for league matches, `holds.py`, `board_counts.py`, `seat_rows.py` and `seat_log.py` for
  counting a claim over every game and reading one seat's log, `batches.py` for what a
  batch cost and how long it took), `closed_levers.md`, `open_levers.md` and `best_practices.md` (what was
  refuted, what was tested with no result yet, and graduated practice: each ships with its
  format and no entries), a `press-audit` skill that checks what was said in a press
  game against what was ordered, an `opponent-profile` skill and a `matchup-writeup`
  skill (how each opponent plays, and why we win or lose against it), the `ide`
  skill, and the reference policy `players/castlereagh/`, built by
  `tools/build.sh`. The reference policy is a search core plus an LLM press layer
  (`CASTLEREAGH_POLICY=press|search`, default `press`).

  Every tool and skill is listed once, with the skills that use each tool, under "Tool and
  skill index" in [mixin/AGENTS.md](mixin/AGENTS.md#tool-and-skill-index); `mixin/tools/tests/test_index.py`
  keeps that index complete. `mixin/CLAUDE.md` loads the lab manual in Claude Code, and
  `install.sh` writes a root `CLAUDE.md` that loads the seed's `AGENTS.md`, which it also
  points at the index.

  **The mixin ships methods, not field knowledge.** Rules, the bot contract, platform facts
  (dated, with the command that re-measures them), tools and skills belong in it. Anything
  true of one field of opponents, one lab's experiments or one night's data does not: no
  experiment results, no opponent behaviour, no named league policies, no "what worked for
  us". Someone who makes a copy next week would take it as current fact.
- **`install.sh`** and **`seed.lock`**: the installer and the pinned
  optimizer-seed commit.
- **`ide/`**: a local web IDE, as its own uv project ([ide/README.md](ide/README.md)).
  The coding agent comes first: it starts the IDE (`ide/ide start --open`), and what the
  user types in the browser reaches that running session through Claude Code hooks. The
  pages: a home page (where the followed policy stands and which games to open), replays
  with notes and the press audit laid over them, a dashboard of `matchups.py`, the
  experiment records (proposed ideas with their cost, and the paired result of the games of
  the ones that ran), and the reports the write-up skills produce. The agent answers and posts
  cards with `ide/ide say` and `ide/ide show`, or the same actions as tools on the
  `ide/ide mcp` stdio server.

The design of the mixin and the installer is
[docs/designs/webdiplomacy-mixin-2026-10-09.html](../docs/designs/webdiplomacy-mixin-2026-10-09.html).
It was written before the IDE and says nothing about it; the IDE's design record is
[ide/README.md](ide/README.md).

## Install

```sh
optimizer/install.sh ~/coding/webdip-optimizer             # wires Claude Code
optimizer/install.sh ~/coding/webdip-optimizer --harness none
```

The target must be empty or missing, and outside this repository.

Most users don't run `install.sh`. They create a private copy of the public
template [Metta-AI/webdip-optimizer](https://github.com/Metta-AI/webdip-optimizer),
which is `install.sh` output. That works in any coding environment that starts
from a GitHub clone, including cloud sessions.

To publish a new template version, commit and push the source first so the
provenance names a public commit, then regenerate and push:

```sh
optimizer/install.sh /tmp/webdip-optimizer
cd /tmp/webdip-optimizer
git remote add origin https://github.com/Metta-AI/webdip-optimizer.git
git push --force origin main     # the template is generated output
```

## Checks

These also run in CI, which also checks that `mixin/field_sets.json` ships placeholders
only (the lab's own tests must keep passing once a user fills that file, so the check is
in the workflow), then runs `install.sh` and checks the result (no unfilled placeholders, the files the skills
and the IDE name, the hook and MCP wiring, a record made from the template that the seed's
validator accepts, and the lab's tool tests in the installed copy):

```sh
uv run ruff check optimizer
(cd optimizer/mixin && python3 -m unittest discover -s tools/tests)
(cd optimizer/mixin && uv run --no-project --python 3.12 --with "pydantic-ai-slim[openai]==2.54.0" \
  python -m unittest discover -s players/castlereagh/tests)
(cd optimizer/ide && uv run python -m unittest discover -s tests)
```

## Known gaps

Found by two fresh-install test drives (2026-10-10 gunboat, 2026-10-10/11 press), the
IDE build (2026-10-11), a third drive of the published template and an overnight campaign
(2026-10-11), and not yet fixed. Each is a setup gap, not a fact about any field of opponents.

- **Press audit: "we broke our word" is still about half noise.** Measured 2026-10-11 on
  nine hosted games with every flag read against a rubric (by sub-agents, not people): flags
  fell from 279 (80% false) to 51 (27% false) after the verify rules changed; `betrayed` is
  25 real of 28, `we_broke_our_word` 12 real of 23. What is left is mostly a letter broken
  with nobody hurt, which code cannot decide.
- **Press audit: a changed plan is seen only when recorded.** `superseded` needs the
  annotator's `replaces` or a later claim naming the very order.
- **Press audit: "missed alliance" is not decided by code.** `doubted_wrongly` is strict
  and was not raised in the nine games; kept promises we had not relied on are
  `kept_despite_doubt`, with the attack orders listed.
- **Press audit: the annotator's file leaks one thing.** `annotate.json` has no orders or
  results, but the next turn's starting board shows where units ended.
- **Press audit: "this fall" written in a spring phase** may mean the current turn or the
  next one. The press-audit skill has the annotator check both turns; code cannot decide.
- **A node lost under a player pod kills that seat for the rest of the game** and the game
  still completes (about 2.5% of press seats on 2026-10-11). The loader taints the seat
  (`pod_deleted`); the cause is on the platform side.
- **IDE: one agent session has the chat, Claude Code only.** Delivery to the running session
  uses Claude Code hooks, tested on 2.1.296. A second session in the same folder is kept
  out by an owner rule (`ide/README.md`, "Which session gets the chat"), run once with two
  live sessions; its last fix has unit tests only. Other harnesses get the `ide/ide listen`
  background task or the MCP tools. The MCP tools were used in a live Claude Code session
  (2026-10-11); nothing was tried under another harness.
- **No hosted game is known to have run the press player's no-units fix.** (`run_ab.py
  --alone`'s two-arm fetch ran hosted on 2026-10-11: 14 games per arm.) `run_ab.py`'s
  `--health` and its estimate line ran hosted later that day in a fresh-install shakedown
  (one health game; the printed estimate matched the platform's quote). `--alone --resume`
  and `--health-games` have unit tests only.
- **Two taint rules have never fired on a hosted game** (about 890 of our seats in the
  second drive): `no_decisions`, and the launcher's nonzero `child_exit` line, which
  taints a seat as `exception`. They have unit tests only.
- **An installed lab has no ruff config.** This repository's `pyproject.toml` sets the
  rules; a user's `ruff check` in their copy uses ruff's defaults and reports other things.
- **Credits charged cannot be read back.** `tools/batches.py` prints the platform's estimate at
  create time (1.4 to 3.3 credits per press game over 2026-10-11 and the night after; it moves) and each episode's recorded
  `cost_usd` (about $0.5); `run_ab.py` prints the estimate when it launches. Neither is the
  bill, their relation is not known, and nobody has read a balance.
- **`run_ab.py --variant` (the short-game screen stage), `--max-credits` and `--add-set` have
  unit tests only**; none has been used on a hosted launch. The same goes for `--config` on
  `make_request.py` and `run_ab.py` (a shorter game through `end_year` and `phase_minutes`):
  the durations in `mixin/docs/platform.md`, "Shorter games", are computed from the phase lengths. `--dry-run`, `my_versions.py`,
  `press_behaviour.py`, `centre_losses.py` and `hold_reasons.py` were written and used in one
  lab's overnight run and have had no second user.
- **`wake_bench.py` has had two short checks with a real model** (40 and 8 recorded decisions,
  2026-10-12, the starter's default model). Its behaviour table moved the same way as the
  hosted games it was sampled from. The count of decisions cut off at a time or call limit has
  unit tests only. `llm_sidecar_local.py --upstream` has forwarded calls to OpenRouter's own
  address and relayed another provider's refusal; it has not completed a call with a second
  provider, and `--drop` is untested against one.
- **`matchups.py --ours`, `holds.py --ours`, `batches.py`'s "N of M in" and `press_audit.py
  extract --by-year`** are new (2026-10-12), each checked once against one lab's games. A
  half-fetched batch was shown only by a synthetic test.
- **`ship.py` and `build.sh` know one source tree, `players/castlereagh`.** Every upload is
  built from it and logged in its `VERSION_LOG.md`, whatever policy name it is uploaded under
  (the row's first cell carries the name, which is what the IDE reads). A second policy source
  tree under `players/` would need its own build and its own log; neither tool takes a
  source directory yet.
- **Press audit: a lie is flagged only when our log shows a stance that turn.** A broken
  promise in a turn with no logged stance lands in `false_no_stance` and is not in the
  headline count. The IDE's line above the
  board now adds "N more did not hold where we logged no stance"; `press_audit.py`'s own
  summary and `audit.html` do not.
- **IDE: the profile request for a gunboat opponent names the wrong page.** "Ask for a
  profile" sends `/reports/opponents/<policy>` as the page it came from, and a gunboat
  profile is written as `<policy>-gunboat.md`. The list finds the report by its `opponent`
  field, so only that hint is off.
- **`run_ab.py` does not read the health game.** `--health` launches it and notes its id;
  fetching it and reading `wd.py metrics` is the agent's step.
- **A dead pod in a field seat is not a taint.** The tools drop games where our own seat's
  pod died. A normal account cannot see a rival's (its log is 403); `tools/holds.py` lists
  seats that stopped moving.
- **`field.py` sees only what recent rounds seated**, which can be less than the roster.
  The roster ids are in `coworld leagues <id> --json`; the tool does not read them yet.
- **`session_env.sh` has no user mode.** Acting as the user (not a player) from a private
  `HOME` is set up by hand (`mixin/docs/platform.md`, "Setup").
- **`opponent_profile.py` lacks two counts**: failed moves
  ordered again unchanged, and the first home centre lost (to whom, when).

## Layout

Source, in this repository:

```
optimizer/
  README.md
  seed.lock      pinned optimizer-seed URL and commit
  install.sh     creates a complete optimizer directory
  mixin/         becomes games/webdiplomacy/ in the installed optimizer
  INSTALL.md     (planned) guide for a coding agent: install, login, harness setup
  ide/           becomes ide/ in the installed optimizer
```

Installed result, outside this repository (for example `~/coding/webdip-optimizer`):

```
webdip-optimizer/          its own git repository, cloned from seed.lock
  AGENTS.md, skills/, ...  optimizer-seed core
  games/webdiplomacy/      copy of mixin/, with provenance stamped in MIXIN.md
  ide/                     copy of ide/: the local web IDE (`ide/ide start --open`)
  .claude/                 seed harness wiring (hooks, skills), plus the IDE's hooks
  .mcp.json                the IDE's MCP server
```

## Why it is built this way

- **The seed is cloned at a pinned commit, not added as a submodule or vendored.**
  A planted seed is a personal, long-lived repository that collects
  experiments, memory and player versions. It is designed to drift from
  upstream. That state does not belong in this public game repository.
- **The installed optimizer is self-contained.** The skills, the lab and the
  workspace all live under one directory. Like the seed itself, the copied
  mixin may drift after installation. Provenance (source commit and date) is recorded so you can
  diff against newer source later.
- **The mixin cannot use the seed's `tools/add_game.sh` yet.** That script
  clones a repository root, and `mixin/` is a subdirectory. `install.sh` writes
  the same provenance block itself. A separate `webdiplomacy-mixin` repository
  can be published later.
- **The mixin's `tools/build.sh` builds against a pinned ref of this public
  repository**, the same way `sugarscape-mixin` does. Once installed, the lab
  no longer sits next to this checkout.
- **`install.sh` adapts a few seed files to a single-game optimizer.** It
  puts a webDiplomacy banner on the README, lists the lab under "Active games"
  in `WORKING_CONTEXT.md`, and creates the lab's `lessons_archive/`. It
  records the seed commit in `SEED.md`, because template copies squash history
  and drop the `seed` remote. It replaces the onboarding's "pick a game" beat in
  `docs/getting-started.md`, which would otherwise send the agent to
  `add_game.sh` for a game that is already installed. It names the lab's "Tool and skill
  index" in the root `AGENTS.md` and in the "Active games" entry. With the Claude Code
  harness it writes a root `CLAUDE.md` that loads `AGENTS.md` (the seed ships none, and
  Claude Code does not read `AGENTS.md` by itself), and adds a SessionStart hook running the lab's `tools/check_clis.py`,
  the IDE's hooks and `.mcp.json` entry, and links to the lab's own skills
  (`press-audit`, `opponent-profile`, `matchup-writeup`, `ide`) in `.claude/skills/`,
  where Claude Code discovers skills; it records the wiring under "Harness wiring"
  in `WORKING_CONTEXT.md`.
  Each edit anchors on the pinned seed's text and fails the install if that text
  moves, so bumping `seed.lock` surfaces them.
