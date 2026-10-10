# AGENTS — webDiplomacy lab

Loaded whenever you work in this lab, on top of the root AGENTS.md. This is the
lab's operating manual: what is here, how to use it, and the mistakes that cost
earlier sessions the most. Game facts live in [docs/game.md](docs/game.md).

## The game in brief

Classic Diplomacy for seven seats on the real webDiplomacy server. Each seat
plays one of seven powers, assigned by a seeded shuffle per episode. All powers
order at once each phase; the server adjudicates. A game ends with a solo (18
supply centers), an agreed draw, or the variant's year cap. At the cap each
survivor scores **SC² / total SC²** over survivors, so the largest power gains
most; parity is 1/7 = 0.143. Two leagues: **webDiplomacy** (`classic-press`,
public and private press, ends 1908) and **webDiplomacy Gunboat**
(`classic-gunboat`, no press, ends 1910). Full rules: [docs/game.md](docs/game.md).

## What is in this lab

| Need | Go to |
|---|---|
| Rules, scoring, `results.json`, variants, leagues, timing | [docs/game.md](docs/game.md) |
| The bot contract: image, launcher, environment, HTTP API, LLM sidecar | [docs/protocol.md](docs/protocol.md) |
| Hosted specifics: XP requests, cost, artifacts, model quirks, credentials | [docs/platform.md](docs/platform.md) |
| How the game is won; measured field facts (2026-10) | [docs/strategy.md](docs/strategy.md) |
| The live field picture | [META.md](META.md) (maintained by meta-recon; dated) |
| Comparing versions | [skills/ab](skills/ab/SKILL.md) |
| Reading a batch | [skills/survey](skills/survey/SKILL.md) |
| Reading replays and our logs | [skills/replay-inspection](skills/replay-inspection/SKILL.md) |
| Designing a hosted eval | [skills/eval-design](skills/eval-design/SKILL.md) |
| Finding why we lose | [skills/diagnosis](skills/diagnosis/SKILL.md) |
| What already works, what is refuted | [best_practices.md](best_practices.md), [closed_levers.md](closed_levers.md) |
| Every binding and element, as a manifest | [MIXIN.md](MIXIN.md) |
| Current objective and open threads | [WORKING_CONTEXT.md](WORKING_CONTEXT.md) |

Write your own longer references in `docs/` when you need them (a verified map
reference, a press-protocol study). The coworld's own long docs are linked from
each doc at a pinned commit.

## The reference policy

`players/castlereagh/` (Python package `castlereagh`) is the starting point.

- **Core: Kissinger search.** Heuristic (DumbBot-style) seeds, alternatives
  for single units, pairs and convoys, improved against 16 sampled opponent
  plans with a fast adjudicator. Opponents are modeled one step smarter than
  the heuristic ("level 1"). Retreats and builds come from the heuristic. This
  search was the gunboat champion and, silent, beat most press bots in the
  2026-10 press field.
- **Optional press layer.** An LLM negotiates and steers the search through a
  policy (stances, trust, expected or required orders). The search's legal
  orders are saved first, so the LLM can never leave the seat without orders.
  As of 2026-10 press has **not** been shown to beat the same search without
  press; making it do so is an open goal.
- **Two modes**, set by the `CASTLEREAGH_POLICY` environment variable in the
  image: `search` (default, press off) and `press` (search plus press; without
  `COWORLD_LLM_ENDPOINT` it plays its search floor).
- **Build:** `tools/build.sh [--ref <game-ref>] [--tag <image-tag>] [--policy search|press]`.
  Default tag `webdip-castlereagh-<policy>:latest`. Needs Docker; it builds the
  coworld player base image from a pinned coworld-webdiplomacy commit on GitHub.
  Without Docker you can still edit, test and analyze, but not build or upload.
- **Logs:** one `decision` JSON line per phase (with `rejected`), `exception`
  events, and in press mode `llm_call` events with `usage.cost`.

## Tools

Standard-library Python in `tools/`, run from the optimizer root as
`python3 games/webdiplomacy/tools/<tool>.py`. They read the directories that the
optimizer's `fetch_artifacts.py` or a local `coworld run-episode` writes, so they
work the same for hosted and local runs. **Exact flags live in each tool's
docstring**; they may shift slightly from what is shown here.

| Tool | For | CLI |
|---|---|---|
| `webdip_episodes.py` | The one episode loader (results, replay, our seat logs; slot to power; bytes-literal logs). Import it in instruments | library |
| `wd.py metrics` | Per-power score vs same-batch field par, coverage, telemetry | `wd.py metrics DIR... [--policy NAME:vN] [--json]` |
| `wd.py seats` | One JSON line per seat with the center trajectory by year | `wd.py seats DIR...` |
| `wd.py costs` | LLM spend per seat and per phase | `wd.py costs DIR...` |
| `wd.py local` | Local episodes, one image in all seats (needs Docker and `coworld`) | `wd.py local ...` |
| `wd.py arena` | Local: one candidate against a local field (needs Docker and `coworld`) | `wd.py arena ...` |
| `wd.py slim` | Strip map PNGs from replays to save disk | `wd.py slim DIR...` |
| `paired.py` | Paired difference and z for two policies in the same games | `paired.py ...` |
| `compare.py` | A/B by power for separate arms | `compare.py BASE_DIR CAND_DIR --baseline NAME:vN --candidate NAME:vM` |
| `llm_sidecar_local.py` | Local stand-in for the hosted LLM sidecar (needs `OPENROUTER_API_KEY`) | `llm_sidecar_local.py ...` |

New analysis that you will run more than once goes in `instruments/`.

## How the loop runs here

| Loop step | In this game |
|---|---|
| Understand | [docs/game.md](docs/game.md), then [docs/strategy.md](docs/strategy.md); refresh `META.md` if stale. Recent league games show who is in the field; replays show every power's orders and public press |
| Evaluate | Hosted XP requests on the league's full variant against explicit field `policy_ref`s; paired seating by default; stream artifacts. See [eval-design](skills/eval-design/SKILL.md) |
| Read | Taint first, then score vs same-batch par **per power**; \|z\| < 2 is no result. See [ab](skills/ab/SKILL.md) and [survey](skills/survey/SKILL.md) |
| Hypothesize | Known failure modes and the procedure in [diagnosis](skills/diagnosis/SKILL.md); check [closed_levers.md](closed_levers.md) first |
| Build | `tools/build.sh`, one image tag per experiment; upload with `--use-llm --llm-model` for press |

## Mechanics ground truth

The source of truth is the **upstream webDiplomacy server pinned by
coworld-webdiplomacy** (see [MIXIN.md](MIXIN.md)), described with file and line
citations in that repo's
[docs/upstream-bot-api.md](https://github.com/Metta-AI/coworld-webdiplomacy/blob/b4aca7310d1de95fe3fc6f61606bfe7ac05335ab/docs/upstream-bot-api.md).
Verify mechanics claims there, never from memory. Cache verified facts here
with where they were verified:

- Invalid orders are dropped silently with HTTP 200; an unknown `terrID`
  returns 400 — upstream `api.php:1040-1078`, `:1008-1017` (via
  upstream-bot-api.md at `b4aca73`).
- Seats are `User` accounts in a `MemberVsBots` game, so votes count and a
  silent seat holds without delaying the phase — upstream-bot-api.md §11.
- 34 supply centers: 3 per power, 4 for Russia, 12 neutral — upstream
  `variants/Classic/install.php`.

## Gotchas

Each of these cost a previous session real time or a wrong conclusion.

- **HTTP 200 does not mean your orders were accepted.** Upstream silently drops
  invalid orders. Diff the saved orders every phase and log `rejected`; any
  nonzero count is a bug.
- **Scores are in slot order, not power order.** `results.countries[slot]` is
  that slot's power.
- **Final centers come from `results.json`** `members[].supplyCenterNo`
  (strings). The replay's `Finished` history entry shows ownership from before
  the last Autumn.
- **Hosted seat logs sometimes arrive as a Python `b'...'` bytes literal.** Use
  `webdip_episodes.py`, which decodes them.
- **Use a private `HOME` per session for Softmax credentials.** Other sessions
  running `coworld player use` switch the identity in the shared
  `~/.softmax/credentials.yaml`; private requests then return 404. Recipe in
  [docs/platform.md](docs/platform.md#setup).
- **One image tag per experiment.** Rebuilding a tag while games run switches
  later games to the new code.
- **Install the CLIs as uv tools:** `uv tool install coworld` and
  `uv tool install softmax-cli`. Keep them current; check versions when
  behavior looks wrong.
- **A failing LLM seat looks healthy.** It plays its search floor with no error.
  Check `llm_call` statuses per seat after any model or prompt change.
- **Never use `random` roster seats.** They can seat you against yourself.
- **The bot is killed at game end.** Log every phase; do not rely on an
  end-of-game summary.
