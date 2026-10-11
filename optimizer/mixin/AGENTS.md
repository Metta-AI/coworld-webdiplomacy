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
| Who lied, who kept their word, where we were betrayed | [skills/press-audit](skills/press-audit/SKILL.md) |
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
  image: `press` (default: search plus press; in a no-press game, or without
  `COWORLD_LLM_ENDPOINT`, it plays its search floor) and `search` (press off).
  Upload a press build with an LLM model; `tools/ship.py` does that by default.
- **Build:** `tools/build.sh --tag <image-tag> [--ref <game-ref>] [--policy press|search] [--overrides "KEY=VAL,…"]`
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
| `paired.py` | Paired difference, its SD and z for two policies in the same games; `vs_par_by_power` compares the two at the same power | `paired.py ...` |
| `compare.py` | A/B by power for separate arms | `compare.py BASE_DIR CAND_DIR --baseline NAME:vN --candidate NAME:vM` |
| `session_env.sh` | Private credentials directory, Docker config and active player for this shell, in one step; `git` and `gh` keep using the real home. In an agent harness pin `WEBDIP_SESSION_HOME` and source it on every command line ([docs/platform.md](docs/platform.md#setup)) | `source games/webdiplomacy/tools/session_env.sh <player id>` |
| `check_clis.py` | Warns when the `coworld` or `softmax` uv tool is missing or older than PyPI's latest. With the Claude Code harness a SessionStart hook runs it; on other runtimes run it yourself at session start (`-v` also reports when both are current) | `check_clis.py [-v]` |
| `llm_sidecar_local.py` | Local stand-in for the hosted LLM sidecar (needs `OPENROUTER_API_KEY`) | `llm_sidecar_local.py ...` |
| `ab_stats.py` | The statistics behind `compare.py` (Welch t, Fisher exact, multiple-test correction) | library |

**Where code lives.** Everything this mixin ships is in `tools/` (linted and unit-tested
upstream). `instruments/` starts empty and is yours: analysis you write and will run more
than once goes there, importing `tools/webdip_episodes.py`.

### Campaign tools

Also in `tools/`, run the same way; flags are in each docstring.

| Tool | For |
|---|---|
| `field.py press\|gunboat` | Who is in a league's field (from its rounds), with version ids for rosters, and the seating of each round |
| `make_request.py` + `../field_sets.json` | Request bodies from a named opponent set; `--balanced` (powers pinned and rotated; a paired A/B gets both seat orders, 14 bodies), `--pin-a POWER` (our seat fixed to one power), `--no-maps`. `field_sets.json` ships with the format only: list the field with `field.py`, then write your own named, dated sets (a stale id fails at create time with "Policy version … was not found") |
| `seat_bias.py` | Whether one roster seat outscores another whoever sits there (reads `wd.py seats` on stdin); for same-code checks |
| `mine_variance.py` | Which measured behaviours go with a policy's own good and bad games (correlations: hypothesis fuel only) |
| `run_ab.py` | One paired A/B end to end from an experiment record: bodies, dry run, launch, ids into the record, fetch, compress, read. `--alone` runs the candidate-alone check (each version alone against a six-seat field), which every paired win needs before promotion; it fetches both arms at once |
| `sizing.py` | Games needed for an effect size, from the measured variance |
| `ship.py` | Build, upload, look up the version id and append the VERSION_LOG row in one step |
| `flag_episodes.py` | Episodes worth opening (reads `wd.py seats` on stdin) |
| `year_deltas.py` | Centre change per game year by policy (reads `wd.py seats` on stdin) |
| `gzip_replays.py` | Compress fetched replays in place, about 20x; the loader reads them |
| `press_audit.py extract\|verify\|report` | One press game from our seat: every message we saw, its claims (an agent lists them), each checked by code against the orders, and a local HTML page. Read the flagged claims' evidence before quoting its counts. See the press-audit skill |

## How the loop runs here

| Loop step | In this game |
|---|---|
| Understand | [docs/game.md](docs/game.md), then [docs/strategy.md](docs/strategy.md); refresh `META.md` if stale (`tools/field.py` lists who is in the field; the recipe is in [strategy.md](docs/strategy.md#rebuilding-the-field-picture)); replays show every power's orders and public press |
| Evaluate | Hosted XP requests on the league's full variant against explicit field `policy_ref`s; paired seating by default; stream artifacts. See [eval-design](skills/eval-design/SKILL.md) |
| Read | Taint first, then score vs same-batch par **per power**; \|z\| < 2 is no result. See [ab](skills/ab/SKILL.md) and [survey](skills/survey/SKILL.md) |
| Hypothesize | Known failure modes and the procedure in [diagnosis](skills/diagnosis/SKILL.md); check [closed_levers.md](closed_levers.md) first |
| Build | `tools/ship.py` (build, upload and VERSION_LOG row in one step; it calls `tools/build.sh`), one image tag per experiment; press builds are uploaded with an LLM model (default `z-ai/glm-5.3-flash`, `--llm-model` to change) |

## Run one A/B, start to finish

In the main league (`classic-press`), which is where to work unless you have a
reason to use Gunboat. From the optimizer root, with the private `HOME` from
[docs/platform.md](docs/platform.md#setup) and the right player active.
`L=games/webdiplomacy`, `R=skills/run-eval/scripts`. First fill
`field_sets.json` with a five-seat set from the current field
([how](docs/strategy.md#rebuilding-the-field-picture)).

```sh
skills/experiment/scripts/record.py new $L <slug>          # then fill hypothesis, predictions, rule
python3 $L/tools/ship.py --name <policy> --slug <slug> \
    --change "<the one change and its mechanism>" --overrides "KEY=VAL" --experiment <record id>
python3 $L/tools/make_request.py paired --a <policy>:vNEW --b <policy>:vBASE \
    --field-set <paired set> -n 2 --balanced --no-maps --note <record id> --out $L/.runtime/requests/<slug>.json
$R/eval_request.py create $L/.runtime/requests/<slug>-r0.json --dry-run
bash -c 'for f in '$L'/.runtime/requests/<slug>-r*.json; do '$R'/eval_request.py create $f; done'   # 14 batches; note each id
skills/fetch-artifacts/scripts/fetch_artifacts.py XREQ1 XREQ2 … --watch --out $L/.runtime/artifacts/<slug>
python3 $L/tools/gzip_replays.py $L/.runtime/artifacts/<slug>
python3 $L/tools/paired.py $L/.runtime/artifacts/<slug> --a <policy>:vNEW --b <policy>:vBASE
```

Everything from the third command on is one step with
`python3 $L/tools/run_ab.py --record <record id> --a <policy>:vNEW --b <policy>:vBASE --field-set <paired set> -n 2`
(it refuses a record that still has template text, and `--resume` picks up an
interrupted run). `ship.py` writes every row to `players/castlereagh/VERSION_LOG.md`,
whatever `--name` you upload under: the log follows the source directory, not the
uploaded policy name.

- `ship.py` builds the press mode and uploads it with an LLM model by default.
  For a press set, `make_request.py` gives each game an LLM budget (a cap of
  $14 split over the seven seats); with a zero budget every LLM seat would play
  its search floor and say nothing.
- `--balanced` writes 14 batches: every power and both seat positions equally
  for each version. `-n` is games per batch:

  | `-n` | Games | Credits (about 15 per press game) | Smallest effect at z = 2 |
  |---|---|---|---|
  | 1 | 14 | about 210 | 0.11 |
  | 2 | 28 | about 420 | 0.08 |
  | 6 | 84 | about 1,260 | 0.04 |

  The effect sizes come from `python3 $L/tools/sizing.py --games N`, and they
  rest on a paired SD for press of 0.20 (measured 0.19 and 0.21 on 2026-10-10,
  27 and 55 games, one opponent set). Check it against your first batch
  (`paired.py` prints `sd`) and re-size with `--sd`.
- **A press game takes 60 to 100 minutes.** Batches run in parallel (a prior
  lab ran 16 games at once in about an hour). On 2026-10-10, 28 games launched
  together finished in 67 minutes; 56 launched while 28 were running, with 56
  more added 40 minutes later (140 in flight), took 127 minutes. Past about 30
  games at once, expect the wall clock to stretch; how long 84 take together is
  still not measured. Launch, record the ids, and read the result later: `--resume`
  fetches and reads when the games are done.
- After every press upload or model change, run one health game on
  `classic-press-short` and confirm every `llm_call` in our seat logs succeeded
  (`make_request.py field … -n 1 --variant classic-press-short` builds it; see
  the eval-design binding). A failing LLM seat looks healthy. The pass line is
  the `telemetry` line of `wd.py metrics DIR --policy NAME:vN`: `rejected 0`,
  `exceptions 0`, `llm calls N (0 failed, …)`, and `press_sent` above zero in
  the trace. A seat's log cannot be read until its game ends (about 25 minutes
  for the short variant, measured 2026-10-10), so in a short session launch the
  health game and the first batch together and discard the batch if the health
  game fails. Write that choice into the experiment record.
- **A paired run gives a fair difference, not a fair level.** With two of our
  seats in one game the score level is not what one seat gets alone, and the
  gap can go either way: the same search scored 0.155 raw beside its twin and
  0.220 alone (hosted gunboat, 168 and 84 games), while the press build scored
  0.16 to 0.18 beside its twin and about 0.13 alone against the league's six
  (46 games), all on 2026-10-10. Read "how good is this version" from an alone
  run (`run_ab.py --alone`, or a field eval), never from a paired one.
- Put the batch ids and the artifact directory in the experiment record as
  soon as they exist.

**The Gunboat league** (`classic-gunboat`, no press) runs the same recipe with a
gunboat field set. Games take about 2.4 minutes and half a credit
(2026-10-10), so it is a fast way to test a change to the search core alone.
It says nothing about negotiation.

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
  `uv tool install softmax-cli`. Keep them current: `tools/check_clis.py`
  prints a fix when either is stale (a SessionStart hook runs it under the
  Claude Code harness). Act on it first.
- **A failing LLM seat looks healthy.** It plays its search floor with no error.
  Check `llm_call` statuses per seat after any model or prompt change.
- **Never use `random` roster seats.** They can seat you against yourself.
- **The bot is killed at game end.** Log every phase; do not rely on an
  end-of-game summary.
