# webDiplomacy optimizer (prototype)

**Status: prototype.** `install.sh` works, and `mixin/` is filled: the lab
manual (`mixin/AGENTS.md`), game docs, the five skill bindings, analysis tools
(`mixin/tools/`), and the reference policy `mixin/players/castlereagh/`, built by
`mixin/tools/build.sh`. `ide/` and `INSTALL.md` do not exist yet.

The design is
[docs/designs/webdiplomacy-mixin-2026-10-09.html](../docs/designs/webdiplomacy-mixin-2026-10-09.html).
The reference policy adapts the personal_labs webdiplomacy_lab's Castlereagh:
Kissinger search as the core, plus an optional press layer
(`CASTLEREAGH_POLICY=search|press`, default `search`).

Checks for the mixin (also run in CI):

```sh
uv run ruff check optimizer
(cd optimizer/mixin && python3 -m unittest discover -s tools/tests)
```

```sh
optimizer/install.sh ~/coding/webdip-optimizer             # wires Claude Code
optimizer/install.sh ~/coding/webdip-optimizer --harness none
```

The target must be empty or missing, and outside this repository.

## Template repository

Most users don't run `install.sh`. They create a private copy of the public
template [Metta-AI/webdip-optimizer](https://github.com/Metta-AI/webdip-optimizer),
which is `install.sh` output. That works in any coding environment that starts
from a GitHub clone, including cloud sessions. The web UI is local-only; the
MCP tools will run over stdio wherever the agent runs.

To publish a new template version, commit and push the source first so the
provenance names a public commit, then regenerate and push:

```sh
optimizer/install.sh /tmp/webdip-optimizer
cd /tmp/webdip-optimizer
git remote add origin https://github.com/Metta-AI/webdip-optimizer.git
git push --force origin main     # the template is generated output
```

Tooling to improve webDiplomacy policies with
[optimizer-seed](https://github.com/Metta-AI/optimizer-seed). This directory is
the **source** of two components. Nobody runs them from here: an installer
copies them into a standalone optimizer directory owned by the user.

- **`mixin/`**: the webDiplomacy game mixin for optimizer-seed. It follows the
  seed's `games/_template/` contract: `MIXIN.md`, the five required skill
  bindings (`ab`, `survey`, `replay-inspection`, `eval-design`, `diagnosis`),
  game docs, a reference policy and `tools/build.sh`.
- **`ide/`**: a local web IDE for humans, plus an MCP server for coding agents.
  It is its own uv project. Both front ends call one shared core: a FastAPI
  web UI that runs locally, and an `ide mcp` command (official `mcp` SDK) that
  speaks stdio. The agent starts that command itself, so it needs no port and
  works in cloud sessions.

## Planned layout

Source, in this repository:

```
optimizer/
  README.md
  seed.lock      pinned optimizer-seed URL and commit
  install.sh     creates a complete optimizer directory (mechanics only)
  INSTALL.md     guide for a coding agent: runs install.sh, then login and harness setup
  mixin/         becomes games/webdiplomacy/ in the installed optimizer
  ide/           becomes ide/ in the installed optimizer
```

Installed result, outside this repository (for example `~/coding/webdip-optimizer`):

```
webdip-optimizer/          its own git repository, cloned from seed.lock
  AGENTS.md, skills/, ...  optimizer-seed core
  games/webdiplomacy/      copy of mixin/, with provenance stamped in MIXIN.md
  ide/                     copy of ide/
  .claude/                 seed harness wiring (hooks, skills)
```

## Why it is built this way

- **The seed is cloned at a pinned commit, not added as a submodule or vendored.**
  A planted seed is a personal, long-lived repository that collects
  experiments, memory and player versions. It is designed to drift from
  upstream. That state does not belong in this public game repository.
- **The installed optimizer is self-contained.** The IDE, the skills and the
  workspace all live under one directory, so the IDE never searches other
  paths. Like the seed itself, the copied mixin and IDE may drift after
  installation. Provenance (source commit and date) is recorded so you can
  diff against newer source later.
- **The mixin cannot use the seed's `tools/add_game.sh` yet.** That script
  clones a repository root, and `mixin/` is a subdirectory. `install.sh` writes
  the same provenance block itself. A separate `webdiplomacy-mixin` repository
  can be published later.
- **The mixin's `tools/build.sh` builds against a pinned ref of this public
  repository**, the same way `sugarscape-mixin` does. Once installed, the lab
  no longer sits next to this checkout.
- **`install.sh` adapts a few seed files to a single-game optimizer.** It
  records the seed commit in `SEED.md`, because template copies squash history
  and drop the `seed` remote. It replaces the onboarding's "pick a game" beat in
  `docs/getting-started.md`, which would otherwise send the agent to
  `add_game.sh` for a game that is already installed. With the Claude Code
  harness it adds a SessionStart hook running the lab's `tools/check_clis.py`
  and records the wiring under "Harness wiring" in `WORKING_CONTEXT.md`.
  Each edit anchors on the pinned seed's text and fails the install if that text
  moves, so bumping `seed.lock` surfaces them.
