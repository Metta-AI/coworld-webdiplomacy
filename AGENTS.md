# Agent guide

This repository packages the **unmodified** upstream webDiplomacy server
(`webdiplomacy/` submodule) as a Softmax Coworld: one game container per
seven-seat episode, one player container per seat. Players are ordinary
webDiplomacy API bots; the Coworld layer only creates, starts, ends and records
the game.

## Where to look

| Question | Start at |
| --- | --- |
| What runs where, which file does what | [docs/architecture.md](docs/architecture.md) |
| Why it is built this way | [docs/design.md](docs/design.md) |
| Player WebSocket, `results.json`, browser tunnel, config | [docs/protocol.md](docs/protocol.md) |
| Upstream API behavior (routes, orders, votes, SSE) | [docs/upstream-bot-api.md](docs/upstream-bot-api.md) |
| Upstream public file schemas (`game.json` etc.) | `webdiplomacy/doc/gamedata/02-spec.md` |
| Replay frames and viewers | [docs/replay.md](docs/replay.md) |
| Bundled bots and legal orders | [docs/players.md](docs/players.md), `players/` |
| Writing a new bot | [docs/write-a-policy.md](docs/write-a-policy.md), `players/examples/herald_bot.py` |
| Build, run, test commands | [README.md](README.md) |
| Episode config fields and defaults | `adapter/config.py` (generates `config-schema.json`) |
| Variants, certification roster, resources | `coworld_manifest_template.json` |
| Optimizer mixin, IDE, template generator | [optimizer/README.md](optimizer/README.md) |

## Rules

- **Never edit, generate files in, or commit changes inside `webdiplomacy/`.**
  Bump the submodule only as a deliberate upstream update (see
  [design](docs/design.md#updating-upstream)). Generated upstream files exist only
  inside the image.
- **The adapter never advances phases or applies votes.** Upstream's gamemaster
  loop does that. The adapter only uses `php/wdc_*.php` at game start and end.
- **Replay, spectator stream and game stdout carry public data only.** Never
  record player contexts, private press, tokens or draft orders there. Private
  press goes only to each seat's player log and artifact.
- **Seat tokens are credentials** (they are also the upstream API keys). Do not
  log them, and do not publish `tmp/` evidence or `/run/webdip/logs` contents.
- Keep the code synchronous unless a framework requires otherwise; the async
  code is confined to the FastAPI WebSocket handlers and the browser tunnel.

## Keeping docs in sync

- `README.md`, `docs/protocol.md`, `docs/replay.md` and `docs/write-a-policy.md`
  are embedded in `coworld_manifest_template.json`. After editing any of them,
  run `uv run python -m tools.sync_manifest_docs` and commit the template too.
  `adapter/test_manifest.py` checks this.
- If you change `adapter/config.py`, update both `config-schema.json` and the
  manifest template's `config_schema` to `EpisodeConfig.model_json_schema()`;
  there is no generator script, and `adapter/test_manifest.py` fails until they match.
- [docs/upstream-bot-api.md](docs/upstream-bot-api.md) cites upstream file:line
  locations at the pinned submodule commit; recheck them when the submodule moves.

## Commands

```sh
git submodule update --init --recursive
uv sync --group dev
uv run python -m unittest discover -s adapter -p 'test_*.py' -v   # adapter unit tests
uv run python -m unittest players.test_players -v                 # player unit tests
uv run ruff check adapter players tools
uv run coworld build --version 0.7.8                              # images + dist/ manifest
DOCKER_DEFAULT_PLATFORM=linux/amd64 uv run coworld run-episode \
  dist/coworld_manifest.json --output-dir tmp/episode --timeout-seconds 60
```

Docker-based checks (`tools/check_*.py`) need the images built first; the README
lists them and `.github/workflows/adapter-tests.yml` runs them in CI. Use the
project-local `uv run coworld` and `uv run softmax`, never global installs.

## Gotchas

- Images are `linux/amd64`; on Apple Silicon set `DOCKER_DEFAULT_PLATFORM`.
- Upstream's raw movement phase is `Diplomacy`; viewers label it **Movement**.
  Turns start at 0 (Spring 1901).
- Results and scores are in **slot order**; `results.countries[slot]` gives the
  upstream country ID.
- Upstream returns 200 when it silently drops invalid orders, and an empty 200
  for an unknown API key. Verify saved orders (`players.api.verify_orders`).
- Hosted game containers run with every Linux capability dropped; processes
  stay root and nginx runs single-process. `tools/check_boot.py` reproduces this.
