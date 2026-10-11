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

## Scoring, structures and platform specifics

The optimizer's core skills look for these three topics in this file. They are
kept in the game docs so each fact has one home:

- **Scoring and what actually ranks:** [docs/game.md, "Scoring"](docs/game.md#scoring)
  and ["Leagues"](docs/game.md#leagues). Leagues rank by mean score, and a
  round is one game, so score per game is the number to move.
- **Structures and semantics** (slots and countries, `results.json`, replay
  frames): [docs/game.md](docs/game.md#slots-and-countries) and the
  [replay-inspection binding](skills/replay-inspection/SKILL.md).
- **Platform specifics** (requests, cost, timing, artifacts, identity):
  [docs/platform.md](docs/platform.md).

## What is in this lab

| Need | Go to |
|---|---|
| Rules, scoring, `results.json`, variants, leagues, timing | [docs/game.md](docs/game.md) |
| The bot contract: image, launcher, environment, HTTP API, LLM sidecar | [docs/protocol.md](docs/protocol.md) |
| Hosted specifics: XP requests, cost, artifacts, model quirks, credentials | [docs/platform.md](docs/platform.md) |
| How the game is won; lessons from a measured field; how to rebuild the field picture | [docs/strategy.md](docs/strategy.md) |
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
  the heuristic ("level 1"). Retreats and builds come from the heuristic.
- **Optional press layer.** An LLM negotiates and steers the search through a
  policy (stances, trust, expected or required orders). The search's legal
  orders are saved first, so the LLM can never leave the seat without orders.
  The press layer is a starting framework, not a finished player: making
  negotiation pay is the open problem in this game, and where most of the room
  to improve is.
- **Two modes**, set by the `CASTLEREAGH_POLICY` environment variable in the
  image: `search` (default, press off) and `press` (search plus press; without
  `COWORLD_LLM_ENDPOINT` it plays its search floor).
- **Build:** `tools/build.sh --tag <image-tag> [--ref <game-ref>] [--policy search|press] [--overrides "KEY=VAL,…"]`
  (`--overrides` bakes `CASTLEREAGH_OVERRIDES`, any `config.py` value, into the image, so a
  one-setting experiment needs no source edit). `--tag` is required and there is no default:
  one tag per experiment. `tools/ship.py` wraps build, upload and the version-log row. Needs Docker; it builds the
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
| `webdip_episodes.py` | The one episode loader (results, replay, our seat logs; slot to power; bytes-literal logs). Import it in your own instruments | library |
| `wd.py metrics` | Per-power score vs same-batch field par, coverage, telemetry | `wd.py metrics DIR... [--policy NAME:vN] [--json]` |
| `wd.py seats` | One JSON line per seat with the center trajectory by year | `wd.py seats DIR...` |
| `wd.py costs` | LLM spend per seat and per phase | `wd.py costs DIR...` |
| `wd.py local` | Local episodes, one image in all seats (needs Docker and `coworld`) | `wd.py local ...` |
| `wd.py arena` | Local: one candidate against a local field (needs Docker and `coworld`) | `wd.py arena ...` |
| `wd.py slim` | Strip map PNGs from replays to save disk | `wd.py slim DIR...` |
| `paired.py` | Paired difference and z for two policies in the same games | `paired.py ...` |
| `compare.py` | A/B by power for separate arms | `compare.py BASE_DIR CAND_DIR --baseline NAME:vN --candidate NAME:vM` |
| `session_env.sh` | Private credentials directory, Docker config and active player for this shell, in one step | `source games/webdiplomacy/tools/session_env.sh <player id>` |
| `check_clis.py` | Warns when the `coworld` or `softmax` uv tool is missing or older than PyPI's latest. The SessionStart hook runs it | `check_clis.py` |
| `llm_sidecar_local.py` | Local stand-in for the hosted LLM sidecar (needs `OPENROUTER_API_KEY`) | `llm_sidecar_local.py ...` |

**Where code lives.** Everything this mixin ships is in `tools/` (linted and unit-tested
upstream). `instruments/` starts empty and is yours: analysis you write and will run more
than once goes there, importing `tools/webdip_episodes.py`.

### Campaign tools

Also in `tools/`, run the same way; flags are in each docstring.

| Tool | For |
|---|---|
| `field.py gunboat\|press` | Who is in a league's field (from its rounds), with version ids for rosters |
| `make_request.py` + `../field_sets.json` | Request bodies from a named opponent set; `--balanced` (powers pinned and rotated; a paired A/B gets both seat orders, 14 bodies), `--pin-a POWER` (our seat fixed to one power), `--no-maps`. `field_sets.json` ships with the format only: list the field with `field.py`, then write your own named, dated sets (a stale id fails at create time with "Policy version … was not found") |
| `seat_bias.py` | Whether one roster seat outscores another whoever sits there (reads `wd.py seats` on stdin); for same-code checks |
| `mine_variance.py` | Which measured behaviours go with a policy's own good and bad games (correlations: hypothesis fuel only) |
| `run_ab.py` | One paired A/B end to end from an experiment record: bodies, dry run, launch, ids into the record, fetch, compress, read. `--alone` runs the candidate-alone check (each version alone against a six-seat field), which every paired win needs before promotion |
| `sizing.py` | Games needed for an effect size, from the measured variance |
| `ship.py` | Build, upload, look up the version id and append the VERSION_LOG row in one step |
| `flag_episodes.py` | Episodes worth opening (reads `wd.py seats` on stdin) |
| `year_deltas.py` | Centre change per game year by policy (reads `wd.py seats` on stdin) |
| `gzip_replays.py` | Compress fetched replays in place, about 20x; the loader reads them |

## How the loop runs here

| Loop step | In this game |
|---|---|
| Understand | [docs/game.md](docs/game.md), then [docs/strategy.md](docs/strategy.md); refresh `META.md` if stale (`tools/field.py` lists who is in the field; the recipe is in [strategy.md](docs/strategy.md#rebuilding-the-field-picture)); replays show every power's orders and public press |
| Evaluate | Hosted XP requests on the league's full variant against explicit field `policy_ref`s; paired seating by default; stream artifacts. See [eval-design](skills/eval-design/SKILL.md) |
| Read | Taint first, then score vs same-batch par **per power**; \|z\| < 2 is no result. See [ab](skills/ab/SKILL.md) and [survey](skills/survey/SKILL.md) |
| Hypothesize | Known failure modes and the procedure in [diagnosis](skills/diagnosis/SKILL.md); check [closed_levers.md](closed_levers.md) first |
| Build | `tools/ship.py` (build, upload and VERSION_LOG row in one step; it calls `tools/build.sh`), one image tag per experiment; `--llm-model` for press |

## Run one A/B (gunboat), start to finish

From the optimizer root, with the private `HOME` from [docs/platform.md](docs/platform.md#setup)
and the right player active. `L=games/webdiplomacy`, `R=skills/run-eval/scripts`.

```sh
skills/experiment/scripts/record.py new $L <slug>          # then fill hypothesis, predictions, rule
python3 $L/tools/ship.py --name <policy> --slug <slug> \
    --change "<the one change and its mechanism>" --overrides "KEY=VAL" --experiment <record id>
python3 $L/tools/make_request.py paired --a <policy>:vNEW --b <policy>:vBASE \
    --field-set <paired set> -n 6 --balanced --no-maps --note <record id> --out $L/.runtime/requests/<slug>.json
$R/eval_request.py create $L/.runtime/requests/<slug>-r0.json --dry-run
bash -c 'for f in '$L'/.runtime/requests/<slug>-r*.json; do '$R'/eval_request.py create $f; done'   # 14 batches; note each id
skills/fetch-artifacts/scripts/fetch_artifacts.py XREQ1 XREQ2 … --watch --out $L/.runtime/artifacts/<slug>
python3 $L/tools/gzip_replays.py $L/.runtime/artifacts/<slug>
python3 $L/tools/paired.py $L/.runtime/artifacts/<slug> --a <policy>:vNEW --b <policy>:vBASE
```

Everything from the third command on is one step with
`python3 $L/tools/run_ab.py --record <record id> --a <policy>:vNEW --b <policy>:vBASE --field-set <paired set> -n 6`
(it refuses a record that still has template text, and `--resume` picks up an
interrupted run).

- `--balanced` with `-n 6` is 14 batches x 6 = 84 games: every power and both
  seat positions equally for each version. 84 games see effects of about 0.075
  or more (`python3 $L/tools/sizing.py --games 84`).
- Cost and time (2026-10-10): about 0.5 credits and $0.03 per game; a game
  plays in about 2.4 minutes; 84 games drain in 8 to 15 minutes depending on
  the queue.
- Put the batch ids and the artifact directory in the experiment record as
  soon as they exist. Use a bash loop, not zsh (zsh does not split `$ids`).

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
  `uv tool install softmax-cli`. Keep them current: the SessionStart hook runs
  `tools/check_clis.py` and prints a fix when either is stale. Act on it first.
- **A failing LLM seat looks healthy.** It plays its search floor with no error.
  Check `llm_call` statuses per seat after any model or prompt change.
- **Never use `random` roster seats.** They can seat you against yourself.
- **The bot is killed at game end.** Log every phase; do not rely on an
  end-of-game summary.
