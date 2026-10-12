# The starter policy (`castlereagh`)

A working webDiplomacy player to start from. It has two parts:

- A **search core** that reads the board, samples what the other powers may do, and
  chooses legal orders. It plays every phase of every game on its own.
- A **press harness**: a basic LLM agent that negotiates through press and steers the
  search through a *policy* (who it treats as an ally, which orders it expects, which of
  its own orders are fixed). The search still writes the orders.

The package and directory are named `castlereagh`; that is only a name. The policy ships
**no persona, no negotiation doctrine and no tuned strategy**. See
[What it deliberately leaves out](#what-it-deliberately-leaves-out).
[`docs/strategy.md`](../../docs/strategy.md) describes how it decides, in plain words.

## Modes

One image, two modes, set by `CASTLEREAGH_POLICY` (baked at build time with
`tools/build.sh --policy`):

| Mode | What it plays |
| --- | --- |
| `press` (default) | The search core plus the press harness. In a NoPress game, or without `COWORLD_LLM_ENDPOINT`, it plays exactly what `search` plays. |
| `search` | The **Default search** alone: no LLM, no press. |

Any other value is an error. DumbBot (the heuristic inside the search) is not a mode.

## Data flow

```
bot.py  phase loop: read context -> choose -> save orders -> diff what upstream kept -> one `decision` log line
 |
 |- search mode, and every retreat/build phase and NoPress game in press mode:
 |    SearchBot.choose(slots)
 |      movement:  opponent_model.sample  ->  search_moves (seeds, alternatives, ascent)  ->  evaluation (fastadj)
 |      retreats, builds:  DumbBot
 |
 `- press mode, movement phase of a press game (press/player.py):
      1. floor.py     save the Default search's orders, not Ready
      2. driver.py    wake the agent at phase start and after each burst of new press
           each wake: briefing (board, saved orders, notes, referee facts, this season's press)
                      -> the agent calls tools (tools.py) -> service.py runs the search under its policy
                      -> commit_orders saves the new orders; send_press sends messages
      3. at the lock  save the last committed orders with Ready and diff them
```

## Module map (`castlereagh/`)

| Module | Role |
| --- | --- |
| `bot.py` | Entry point and phase loop. Mode selection, config overrides, `play_phase` (choose, save with Ready, diff saved orders, one `decision` line), a `workspace` snapshot every phase. |
| `config.py` | Every setting with its default, plus `MODEL_QUIRKS` (per-model request settings). |
| `search.py` | `SearchBot`: decision state, phase dispatch, movement setup. `press=None` is play with no policy. |
| `search_moves.py` | DumbBot seeds, single/pair/convoy alternatives, coordinate ascent, policy constraints. |
| `opponent_model.py` | Competent-or-random belief per power, opponent samples, level-1 best responses, policy conditioning. |
| `evaluation.py` | Scores an adjudicated outcome: projected centres, position value, dislodged units; averages over the samples with the risk setting. |
| `fastadj.py` | Pure-Python adjudicator (Hold, Move, Support) used inside the search. |
| `search_orders.py` | Order keys and webDip -> fastadj conversion with the convoy approximation. |
| `dumbbot.py` | The DumbBot heuristic: province values, seed plans, opponent samples, retreats, builds. |
| `dipmap.py` | Classic-map abbreviations and standard notation. |
| `legal_orders.py`, `webdip_api.py` | Vendored from coworld-webdiplomacy at the build's pin (their headers say why). |
| `golden.py` + `tests/golden.json` | The search's behaviour contract: 334 recorded decisions, reproduced bit for bit. |

### Press harness (`castlereagh/press/`)

| Part | Module | Contract |
| --- | --- | --- |
| Search service | `service.py` | `search` / `evaluate` / `predict` over a policy dict (stances, trust, expected/required orders, forbidden provinces, centre values, risk). `search(None)` is the Default search. |
| Order floor | `floor.py` | `default_floor` orders are saved (not Ready) before the LLM runs, every phase; `save_orders` diffs what upstream kept. The LLM can never leave the seat without legal orders. |
| Press driver | `driver.py` | One event-driven wake loop: a wake at phase start, then one per burst of new press (debounce `PRESS_DEBOUNCE_S`, at most `PRESS_MAX_DEBOUNCE_S`), up to `PRESS_MAX_WAKES`, until the lock `PRESS_FINAL_MARGIN_S` before the deadline, when the last committed orders are saved with Ready. |
| Knowledge | `knowledge.py` | `Notes` (free-form, written by the agent), `PressLog` (every message, verbatim), `RefereeFacts` (moves and supports into another power's units or centres, from adjudicated orders only). |
| Tools | `tools.py` | The 13 functions the agent can call. Type hints and docstrings are the schema the model sees. |
| Glue | `player.py`, `llm.py`, `notation.py` | Phase handling, briefing, commit and send; the model on the sidecar, per-call logging, `run_wake`; standard notation, board summary, map connectivity. |

The system prompt is three markdown parts, joined by `llm.system_prompt`:

1. `press/souls/<PRESS_SOUL>/SOUL.md`: the agent's role. The shipped `default` soul states
   the objective and nothing about style or strategy.
2. `press/HARNESS.md`: how wakes, policies, tools, notes, notation and the map work.
3. A list of `press/skills/<name>/SKILL.md` (name and description). The agent loads a
   skill's text with `read_skill(name)`. Two ship as reference material: `agreements`
   (how a DMZ, support or convoy agreement maps onto policy fields; how to read
   `assess_deal`) and `game-end` (the end year and the scoring rules).

## Changing it

| To change | Do this |
| --- | --- |
| The agent's role, voice or strategy | Write `press/souls/<name>/SOUL.md` and set `PRESS_SOUL=<name>` (in `config.py`, or `CASTLEREAGH_OVERRIDES="PRESS_SOUL=<name>"`). |
| What the agent can look up | Add `press/skills/<name>/SKILL.md` with `name:` and `description:` in its front matter. It is listed in the prompt automatically. |
| The rules the agent is told | Edit `press/HARNESS.md`. Keep it true to the code. |
| A setting, for one experiment | `tools/build.sh --overrides "KEY=VAL,KEY=VAL"` bakes `CASTLEREAGH_OVERRIDES` into the image; no source edit. A value converts to the setting's current type; an on/off setting takes `1`, `true`, `0` or `false`. An unknown key fails at startup with an `exception` log line. |
| A setting, for good | Edit its default in `config.py`. A change to a search default changes the search's orders: re-record the golden corpus (below) and log it in `VERSION_LOG.md`. |
| A tool | Add a method to `Toolbox` in `press/tools.py` that returns text through `self._guard(...)` (which enforces the wake's time limit and logs a `tool_call` event), give it type hints and a one-line docstring, add it to `Toolbox.all()`, and describe it in `HARNESS.md`. `tests/test_agent_wiring.py` shows how to drive tools with a scripted model. |
| A policy field | Add its type to `check_policy_shape` (a wrong shape from the model must come back as a `ValueError` it can read, not end the wake), parse it in `SearchService.resolve` (`press/service.py`), use it in the search (`search_moves.py`, `opponent_model.py` or `evaluation.py`, where `bot.press` is read), and document it in `HARNESS.md` and the `search` tool's docstring. With no policy, the search must stay unchanged. |
| The order floor | Replace `default_floor` in `press/floor.py` with a function of the same shape. |
| When the agent is woken | `press/driver.py` (scheduling only; the clock is injectable for tests). |
| What the search values | `evaluation.py` (`score_fast`) and the weights in `config.py`. |
| How opponents are modelled | `opponent_model.py`. |
| The LLM model | `tools/ship.py --llm-model` at upload; the model is fixed per uploaded version. `PRESS_MODEL` is only the local default. If a model rejects a request parameter, add a `MODEL_QUIRKS` entry. |

Two things to keep when you change the press harness: the floor is saved before the LLM
runs, and saved orders are diffed against what was sent (upstream answers 200 while
dropping invalid orders).

## Build, run, test

From the lab root (`games/webdiplomacy/` in an optimizer):

```sh
tools/build.sh --tag webdip-castlereagh:exp1                          # press mode; --tag is required; prints the tag
tools/build.sh --policy search --tag webdip-castlereagh-search:exp1   # the search core alone
tools/build.sh --tag webdip-castlereagh:exp2 --overrides "SEARCH_SEEDS=4"   # a one-setting experiment
python3 -m unittest discover -s players/castlereagh/tests      # about a minute (the golden test)
GOLDEN_EVERY=20 python3 -m unittest discover -s players/castlereagh/tests   # quick
uv run --no-project --python 3.12 --with "pydantic-ai-slim[openai]==2.54.0" \
  python -m unittest discover -s players/castlereagh/tests   # also runs the agent-wiring test
```

The tests need only the standard library (the agent-wiring test skips without pydantic-ai).
Building needs Docker; editing, analysis and tests do not.

The golden test fails when any search decision changes. After a deliberate change to the
search, re-record the corpus (`python -m castlereagh.golden record REPLAY_ROOT tests/golden.json`,
see `golden.py`) and say so in `VERSION_LOG.md`.

A local episode (seven copies, from a coworld-webdiplomacy checkout with
`dist/coworld_manifest.json`). The `--run` tokens are required: without them the CLI keeps
its hold-bot command on six certification seats.

```sh
DOCKER_DEFAULT_PLATFORM=linux/amd64 uv run coworld run-episode dist/coworld_manifest.json \
  webdip-castlereagh:exp1 --variant classic-press \
  --run /opt/.venv/bin/python --run=-m --run players.launcher \
  --run /opt/.venv/bin/python --run=-m --run castlereagh \
  --output-dir tmp/castlereagh --timeout-seconds 6000
```

## Runtime environment

| Variable | Use |
| --- | --- |
| `WEBDIP_URL`, `WEBDIP_API_KEY`, `WEBDIP_GAME_ID`, `WEBDIP_COUNTRY_ID`, `WEBDIP_SEED` | Set by the launcher. |
| `WEBDIP_END_YEAR`, `WEBDIP_SCORING` | Set by the launcher; they feed the press briefing. Nothing is guessed when they are absent. The search does not read them. |
| `WEBDIP_SEARCH_BUDGET_S` | Search seconds per movement decision (default 20). |
| `CASTLEREAGH_POLICY` | `press` or `search`. |
| `CASTLEREAGH_OVERRIDES` | `KEY=VAL,...` for any `config.py` setting. |
| `COWORLD_LLM_ENDPOINT`, `COWORLD_LLM_MODEL` | The LLM sidecar (press only). It is the only LLM path: OpenAI-compatible, no streaming. |

The press limits in `config.py` are generous on purpose (30 model calls and 120 s per wake,
6000 tokens per call, 20 wakes per phase); tighten them once your logs show what a wake
uses. The sidecar rejects a request that carries a parameter the model does not support,
and then every call fails and the seat plays its floor without any other sign.
`MODEL_QUIRKS` holds the per-model settings that avoid this. After any model change, run
one health game and check every `llm_call` status.

## Seat log schema (keep stable: the lab's tools parse it)

One JSON object per stdout line, each with `policy` (`castlereagh-search|press`; plain
`castlereagh` on a fatal startup `exception`), `event` and `t`. Events: `start`; `decision` (one per phase: `turn`, `phase`, `country`, `units`,
`centers`, `compute_ms`, `trace`, `rejected`, `difference`; press adds `press_policy`,
`llm_cost_usd`, `drive`); `workspace` (snapshot every phase: beliefs, and in press notes and
LLM totals); `exception`, `http_error`, `finished`. Press adds `press_start`
(`system_prompt`, `config`, `model_settings`), `press_disabled`, `wake_start`, `wake`
(`status`, `calls`, `cost_usd`), `wake_error`, `llm_request`, `llm_call` (`status`, token
counts, `cost_usd` from `usage.cost`, `error`), `tool_call`, `press_in`, `press_out`,
`press_commit`, `aggression`, `facts_error`, `press_summary`.

Taint checks: a nonzero `rejected`, any `exception`, and a press seat whose `llm_call`
statuses are mostly not 200 (it silently played the floor; the tools flag it at half).

## What it deliberately leaves out

The starter is a structure, not a finished player. These are open ground, and yours:

- **No persona and no doctrine.** The default soul gives the objective only. It does not
  say whom to trust, when to break a promise, how many fronts to fight on or how to write.
- **No negotiation strategy.** The two skills explain mechanisms. There are no openings,
  no trust thresholds and no playbook.
- **No record of agreements.** The harness stores messages and adjudicated orders. It does
  not decide whether a promise was kept; the agent's notes are free-form.
- **No guard on what the agent commits.** Any legal policy is accepted, including one that
  fixes every unit's order.
- **No planning past the current phase** in the search, and no knowledge of the end year
  or the scoring rule there ([strategy.md](../../docs/strategy.md#structural-limits)).
- **No results.** Nothing here says how strong the policy is in your field, or whether the
  press harness helps the search. Measure it against the opponents you will meet.
