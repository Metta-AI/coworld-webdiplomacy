# Castlereagh — the reference policy

Adapted from the personal_labs webdiplomacy_lab's Castlereagh (lab commit `1c2d81fa`).
One image, two modes, selected by `CASTLEREAGH_POLICY` (baked at build time with
`tools/build.sh --policy`):

| Mode | What it plays |
| --- | --- |
| `search` (default) | The **Default search** (the lab's "Kissinger"): DumbBot seeds, single/pair/convoy alternatives, coordinate ascent against 16 sampled opponent plans, level-1 opponents and the "competent opponent" belief. No press. |
| `press` | The same search core plus an optional LLM press layer that negotiates and steers the search through a *policy*. In NoPress games, and without `COWORLD_LLM_ENDPOINT`, it plays exactly like `search`. |

Any other value is an error. DumbBot is internal to the search (seeds, retreats, builds,
opponent samples); it is not a selectable mode. Local arenas use copies of `search` as the field.

**What the evidence says.** Castlereagh's measured strength is the search. In about 100
hosted press games the lab's press bot scored 0.124–0.126 per seat while silent Kissinger
(the same search, no LLM) scored 0.172–0.176 in the same field (parity 1/7 = 0.143). No
press change has a verdict yet. Treat the press layer as a **well-instrumented framework
for experiments, not a proven gain**: the first A/B to run is `press` vs `search`.

## Build, run, test

```sh
tools/build.sh --policy search            # prints webdip-castlereagh-search:latest
tools/build.sh --policy press --tag webdip-castlereagh-press:exp1
python3 -m unittest discover -s players/castlereagh/tests      # from the lab root; ~1 min (golden)
GOLDEN_EVERY=20 python3 -m unittest discover -s players/castlereagh/tests   # quick
uv run --no-project --python 3.12 --with "pydantic-ai-slim[openai]==2.54.0" \
  python -m unittest discover -s players/castlereagh/tests   # also runs the agent-wiring test
```

The tests need only the standard library (the agent-wiring test skips without pydantic-ai).
Building needs Docker; editing, analysis and tests do not.

A local episode (seven copies, from a coworld-webdiplomacy checkout with
`dist/coworld_manifest.json`). The `--run` tokens are required: without them the CLI keeps
its hold-bot command on six certification seats.

```sh
DOCKER_DEFAULT_PLATFORM=linux/amd64 uv run coworld run-episode dist/coworld_manifest.json \
  webdip-castlereagh-search:latest --variant classic-gunboat \
  --run /opt/.venv/bin/python --run=-m --run players.launcher \
  --run /opt/.venv/bin/python --run=-m --run castlereagh \
  --output-dir tmp/castlereagh-search --timeout-seconds 1800
```

Runtime environment: `WEBDIP_*` from the launcher (`WEBDIP_END_YEAR` and `WEBDIP_SCORING`
feed the press briefing; nothing is guessed when they are absent), `WEBDIP_SEARCH_BUDGET_S`
(search seconds per movement decision, default 20), `CASTLEREAGH_OVERRIDES="KEY=VAL,..."`
(any `config.py` knob, for local experiments), `COWORLD_LLM_ENDPOINT` / `COWORLD_LLM_MODEL`
(press only).

## Module map (`castlereagh/`)

| Module | Role |
| --- | --- |
| `bot.py` | Entry point and phase loop. Mode selection, config overrides, `play_phase` (choose, save with Ready, diff saved orders, one `decision` line), a `workspace` snapshot every phase. |
| `config.py` | Every knob, with Kissinger defaults, plus `MODEL_QUIRKS` (per-model sidecar settings). |
| `search.py` | `SearchBot`: decision state, phase dispatch, movement setup. `press=None` is gunboat play. |
| `search_moves.py` | DumbBot seeds, single/pair/convoy alternatives, coordinate ascent, press constraints. |
| `opponent_model.py` | Competent/random belief updates, opponent samples, level-1 best responses, press conditioning. |
| `evaluation.py` | Projected-centre scoring of an adjudicated outcome, risk aggregation, implicit diplomacy (off). |
| `fastadj.py` | Pure-Python DATC "guess and check" adjudicator (Hold/Move/Support). |
| `search_orders.py` | Order keys and webDip -> fastadj conversion with the convoy approximation. |
| `dumbbot.py` | DumbBot heuristic (seeds, opponent samples, retreats, builds). |
| `dipmap.py` | Static Classic-map abbreviations and standard notation. |
| `legal_orders.py`, `webdip_api.py` | Vendored from coworld-webdiplomacy at the build's pin (see their headers for why). |
| `golden.py` + `tests/golden.json` | The behaviour contract: 334 recorded lab decisions, reproduced bit for bit. |

### Press layer (`castlereagh/press/`): four replaceable parts

| Part | Module | Contract |
| --- | --- | --- |
| (a) Search service | `service.py` | `search` / `evaluate` / `predict` over a policy dict (stances, trust, expected/required/forbidden orders, centre values, risk). `search(None)` is gunboat play. |
| (b) Order floor | `floor.py` | `default_floor` orders are saved (not Ready) before the LLM runs, every phase; `save_orders` diffs what upstream kept. The LLM can never leave the seat without legal orders. |
| (c) Press driver | `driver.py` | One event-driven wake loop: a wake at phase start, then one per burst of new press (debounce `PRESS_DEBOUNCE_S` = 5 s, at most `PRESS_MAX_DEBOUNCE_S` = 15 s), up to `PRESS_MAX_WAKES` = 20, until the lock `PRESS_FINAL_MARGIN_S` = 12 s before the deadline, when the last committed orders are saved with Ready. It still hears press in the last ~25 s. |
| (d) Knowledge | `knowledge.py` | `notes(key, text)` / `read_notes()`; the raw press log (this season inline in the briefing, older seasons via `conversation(power)`); referee facts derived only from adjudicated orders (`facts(power)`). |

Glue: `player.py` (phase handling, briefing, commit/send), `llm.py` (pydantic-ai model on
the sidecar, per-model settings, logging hooks, `run_wake`), `tools.py` (the 13 agent
tools), `notation.py` (standard notation, board brief, the map connectivity list labelled
as *possible* moves). User-owned markdown: `HARNESS.md`, `souls/<name>/SOUL.md` (select with
`PRESS_SOUL`), `skills/<name>/SKILL.md` (listed in the system prompt, loaded with `read_skill`).

The LLM goes only through `COWORLD_LLM_ENDPOINT` (OpenAI-compatible, no streaming). Limits
start generous ("set all limits high, then tighten"): 30 model calls and 120 s per wake,
6000 max tokens per call. Model quirks the sidecar turns into silent floor play (it forces
`require_parameters`): gpt-6-luna and claude-haiku-5.5 reject temperature, gemini-3.5-flash-lite
rejects reasoning off, deepseek reasons past small caps. `MODEL_QUIRKS` handles these;
after any model change, run one health episode and check every `llm_call` status.

## Seat log schema (keep stable: the lab's tools parse it)

One JSON object per stdout line, each with `policy` (`castlereagh-search|press`), `event`
and `t`. Events: `start`; `decision` (one per phase: `turn`, `phase`, `country`, `units`,
`centers`, `compute_ms`, `trace`, `rejected`, `difference`; press adds `press_policy`,
`llm_cost_usd`, `drive`); `workspace` (snapshot every phase: beliefs, and in press notes and
LLM totals); `exception`, `http_error`, `finished`. Press adds `press_start`
(`system_prompt`, `config`, `model_settings`), `press_disabled`, `wake_start`, `wake`
(`status`, `calls`, `cost_usd`), `wake_error`, `llm_request`, `llm_call` (`status`, token
counts, `cost_usd` from `usage.cost`, `error`), `tool_call`, `press_in`, `press_out`,
`press_commit`, `aggression`, `press_summary`.

Taint checks: a nonzero `rejected`, any `exception`, and a press seat whose `llm_call`
statuses are not 200 (it silently played the floor).

## Tuning notes from the lab

More search over the same evaluation hurt every time it was tried (restarts, triples, 24
samples, rollouts, a learned evaluation that was exploited). The two measured search gains
are the level-1 opponents and the competent-opponent belief. Change one thing per version,
judge it by paired A/B against the current field, and treat |z| < 2 as no result.
