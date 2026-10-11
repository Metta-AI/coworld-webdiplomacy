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
  for league matches), a `press-audit` skill that checks what was said in a press
  game against what was ordered, an `opponent-profile` skill and a `matchup-writeup`
  skill (how each opponent plays, and why we win or lose against it), the `ide`
  skill, and the reference policy `players/castlereagh/`, built by
  `tools/build.sh`. The reference policy adapts a prior lab's Castlereagh:
  Kissinger search as the core, plus an LLM press layer
  (`CASTLEREAGH_POLICY=press|search`, default `press`).
- **`install.sh`** and **`seed.lock`**: the installer and the pinned
  optimizer-seed commit.
- **`ide/`**: a local web IDE, as its own uv project ([ide/README.md](ide/README.md)).
  The coding agent comes first: it starts the IDE (`ide/ide start --open`), and what the
  user types in the browser reaches that running session through Claude Code hooks. The
  pages: replays with notes and the press audit laid over them, a dashboard of
  `matchups.py`, and the reports the write-up skills produce. The agent answers and posts
  cards with `ide/ide say` and `ide/ide show`, or the same actions as tools on the
  `ide/ide mcp` stdio server.

The design is
[docs/designs/webdiplomacy-mixin-2026-10-09.html](../docs/designs/webdiplomacy-mixin-2026-10-09.html).

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
in the workflow), then runs `install.sh` and checks the result:

```sh
uv run ruff check optimizer
(cd optimizer/mixin && python3 -m unittest discover -s tools/tests)
(cd optimizer/mixin && uv run --no-project --python 3.12 --with "pydantic-ai-slim[openai]==2.54.0" \
  python -m unittest discover -s players/castlereagh/tests)
(cd optimizer/ide && uv run python -m unittest discover -s tests)
```

## Known gaps

Found by two fresh-install test drives (2026-10-10 gunboat, 2026-10-10/11 press) and the
IDE build (2026-10-11), and not yet fixed. Each is a setup gap, not a fact about any field of opponents.

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
- **Bots write "this fall" in a spring phase** in about a quarter of such messages and mean
  the current turn (ours and opponents'). The press-audit skill checks both turns; the
  policy's prompt is worth its own look.
- **A node lost under a player pod kills that seat for the rest of the game** and the game
  still completes (about 2.5% of press seats on 2026-10-11). The loader taints the seat
  (`pod_deleted`); the cause is on the platform side.
- **IDE: one agent session per lab, Claude Code only.** Delivery to the running session
  uses Claude Code hooks, tested on 2.1.296. Other harnesses get the `ide/ide listen`
  background task or the MCP tools, which were not tested inside a live session.
- **No hosted game has run** the press player's no-units fix or `run_ab.py --alone`'s
  two-arm fetch.
- **`child_exit` and `no_decisions` taints have never fired on a hosted game** (about
  890 of our seats in the second drive); they have unit tests only.
- **An installed lab has no ruff config.** This repository's `pyproject.toml` sets the
  rules; a user's `ruff check` in their copy uses ruff's defaults and reports other things.
- **Credits spent cannot be read back.** The lab quotes per-game estimates; nothing shows
  a batch's real cost after it ran.
- **`ship.py` writes every version-log row to `players/castlereagh/VERSION_LOG.md`**,
  whatever policy name is uploaded.
- **Hooks were not observed firing** in the second drive (its session was rooted outside
  the install).

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
  `add_game.sh` for a game that is already installed. With the Claude Code
  harness it adds a SessionStart hook running the lab's `tools/check_clis.py`,
  the IDE's hooks and `.mcp.json` entry, and links to the lab's own skills
  (`press-audit`, `opponent-profile`, `matchup-writeup`, `ide`) in `.claude/skills/`,
  where Claude Code discovers skills; it records the wiring under "Harness wiring"
  in `WORKING_CONTEXT.md`.
  Each edit anchors on the pinned seed's text and fails the install if that text
  moves, so bumping `seed.lock` surfaces them.
