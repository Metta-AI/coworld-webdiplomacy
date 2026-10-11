# webDiplomacy optimizer (prototype)

Tooling to improve webDiplomacy policies with
[optimizer-seed](https://github.com/Metta-AI/optimizer-seed). This directory is
the **source**. Nobody runs it from here: `install.sh` copies it into a
standalone optimizer repository owned by the user.

**Status: prototype.** `install.sh` works and `mixin/` is filled. `ide/` and
`INSTALL.md` are planned and do not exist yet.

## What is here

- **`mixin/`**: the webDiplomacy game mixin for optimizer-seed. It follows the
  seed's `games/_template/` contract: `MIXIN.md`, the lab manual
  (`AGENTS.md`), the five required skill bindings (`ab`, `survey`,
  `replay-inspection`, `eval-design`, `diagnosis`), game docs, analysis and
  campaign tools in `tools/` (one-command build-upload-log and A/B runs, request
  builders, sizing), a `press-audit` skill that checks what was said in a press
  game against what was ordered, and the reference policy `players/castlereagh/`, built by
  `tools/build.sh`. The reference policy adapts a prior lab's Castlereagh:
  Kissinger search as the core, plus an LLM press layer
  (`CASTLEREAGH_POLICY=press|search`, default `press`).
- **`install.sh`** and **`seed.lock`**: the installer and the pinned
  optimizer-seed commit.
- **`ide/`** (planned): a local web IDE for humans, plus an MCP server for
  coding agents, as its own uv project. Both front ends would call one shared
  core: a FastAPI web UI that runs locally, and an `ide mcp` command that
  speaks stdio, so an agent can start it without a port, including in cloud
  sessions.

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

These also run in CI, which then runs `install.sh` and checks the result:

```sh
uv run ruff check optimizer
(cd optimizer/mixin && python3 -m unittest discover -s tools/tests)
(cd optimizer/mixin && uv run --no-project --python 3.12 --with "pydantic-ai-slim[openai]==2.54.0" \
  python -m unittest discover -s players/castlereagh/tests)
```

## Layout

Source, in this repository:

```
optimizer/
  README.md
  seed.lock      pinned optimizer-seed URL and commit
  install.sh     creates a complete optimizer directory
  mixin/         becomes games/webdiplomacy/ in the installed optimizer
  INSTALL.md     (planned) guide for a coding agent: install, login, harness setup
  ide/           (planned) becomes ide/ in the installed optimizer
```

Installed result, outside this repository (for example `~/coding/webdip-optimizer`):

```
webdip-optimizer/          its own git repository, cloned from seed.lock
  AGENTS.md, skills/, ...  optimizer-seed core
  games/webdiplomacy/      copy of mixin/, with provenance stamped in MIXIN.md
  .claude/                 seed harness wiring (hooks, skills)
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
  harness it adds a SessionStart hook running the lab's `tools/check_clis.py`
  and records the wiring under "Harness wiring" in `WORKING_CONTEXT.md`.
  Each edit anchors on the pinned seed's text and fails the install if that text
  moves, so bumping `seed.lock` surfaces them.
