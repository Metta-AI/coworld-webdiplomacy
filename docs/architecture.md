# Architecture

How the pieces fit together and where each one lives. For *why* it is built this
way, see [design](design.md). For wire contracts, see [protocol](protocol.md),
[replay](replay.md) and the [upstream bot API](upstream-bot-api.md).

```
 Player container (one per seat)              Game container (one per episode)
 ┌──────────────────────────────┐             ┌───────────────────────────────────────────┐
 │ players.launcher             │ WS /player  │ nginx :8080 (only public listener)        │
 │  ├─ hello, presence, ack ────┼────────────►│  ├─ /player /global /client/* → adapter   │
 │  ├─ bot subprocess ──────────┼─ HTTP ─────►│  ├─ /api.php /map.php /gamefile.php → FPM │
 │  │   (WEBDIP_* env)          │             │  ├─ /cache/games/…, variant.json → disk   │
 │  └─ press archive worker ────┼─ HTTP ─────►│  └─ /events → Node SSE (Unix socket)      │
 └──────────────────────────────┘             │ adapter (uvicorn 127.0.0.1:8082)          │
                                              │  boot + supervisor + Episode.tick loop    │
 Browser (human seat or spectator)            │ PHP-FPM :9000 (4 workers, upstream code)  │
   /client/player → WS tunnel ───────────────►│ Node SSE → gamemaster.php every ~1 s      │
   /client/global → WS /global ──────────────►│ MariaDB :3306, Redis :6379 (loopback)     │
                                              └───────────────────────────────────────────┘
```

## Images and build

| Image | Dockerfile | Contents | Entrypoint |
| --- | --- | --- | --- |
| Game (`coworld-webdiplomacy-game`) | `adapter/Dockerfile` | Upstream submodule at `/application`, Composer and npm deps, compiled React board, MariaDB, Redis, nginx, Node 22, the adapter at `/opt` | `python -m adapter.boot` |
| Player (`coworld-webdiplomacy-player`) | `adapter/Dockerfile.player` | Python 3.12, `players/` and `adapter/artifacts.py` | `python -m players.launcher` (default child: `players.random_bot`) |

`compose.yaml` names both images. `uv run coworld build --version X` runs
`docker compose build`, substitutes `{{GAME_IMAGE}}` and `{{PLAYER_IMAGE}}` in
`coworld_manifest_template.json` from the compose service names, runs the
`tools/build_replay_viewer.sh` hook (a filename the CLI looks for by convention),
and writes `dist/coworld_manifest.json` plus `dist/build/static-replay-viewer/`.

The game image runs `python -m adapter.boot --bake` during `docker build`. Baking
installs upstream's schema (`install/FullInstall/fullInstall.sql`), registers
Classic through `php/wdc_install.php`, renders the sample map
`/opt/adapter/client/smallmap.png`, and locks the database account. Runtime boot
never installs the database.

## Game container at runtime

`adapter/boot.py` `main()` runs in this order:

1. `prepare()` writes fresh secrets to `/run/webdip/settings.json`, generates
   `/application/config.php` from upstream's `config.sample.php` plus
   `config/webdip.php`, and writes the SSE server's `.env`.
2. Starts Redis and MariaDB; unlocks and re-passwords the database account; sets
   upstream's `LastProcessTime` so the gamemaster will run.
3. Reads `EpisodeConfig` from `COGAME_CONFIG_URI` and constructs `Episode`, which
   creates the upstream game immediately (`php/wdc_create_game.php`).
4. Starts the FastAPI app (uvicorn on `127.0.0.1:8082`), then PHP-FPM, nginx and
   the upstream Node SSE server, waiting for each to be ready. `/healthz` returns
   200 only after all of them are up.
5. Loops every 0.1 s: `Supervisor.check()` (any daemon exit fails the container),
   `Episode.tick()`, and exits once `Episode.completion_ready()` is true.
6. On exit or SIGTERM, stops services in reverse start order. Exit 0 on a clean
   episode, 1 on any failure.

With `WEBDIP_MODE=smoke|tactics|convoy` and no runner, boot writes its own
config, then runs `players.scenarios` against itself as a regression check.

| Process | Listens on | Config | Log under `/run/webdip/logs/` |
| --- | --- | --- | --- |
| nginx (single process) | `0.0.0.0:8080` | `config/nginx.conf` | `nginx.log`, `gamemaster-timing.log` |
| Adapter (FastAPI/uvicorn) | `127.0.0.1:8082` | `adapter/config.py` | stdout (public), `boot-error.log`, `lifecycle-error.log` |
| PHP-FPM, 4 static workers | `127.0.0.1:9000` | `config/php-fpm.conf` | `php-fpm.log` |
| Node SSE server + gamemaster loop | `/run/webdip/sse.sock` | generated `sse-server/.env` | `sse.log` |
| MariaDB | `127.0.0.1:3306` | `config/mariadb.cnf` | `mariadb.log` |
| Redis | `127.0.0.1:6379` | `config/redis.conf` | `redis.log` |

Container stdout is the public game log. It carries only service status, phase
transitions (`{"event":"phase",…}`), `game_over`, and failure metadata. Files under
`/run/webdip/logs` are private and may contain secrets.

### Public routes (nginx)

Everything not listed returns 404.

| Path | Served by | Purpose |
| --- | --- | --- |
| `/player`, `/global` | adapter (WebSocket) | Seat presence and browser tunnel; public spectator stream |
| `/client/player`, `/client/global` | adapter | Human board wrapper; read-only live viewer |
| `/client/board/`, `/client/static/` | disk (`/application/game/`) | Compiled upstream React board |
| `/client/shim.js`, `/client/viewer.js`, `/client/smallmap.png` | disk (`/opt/adapter/client/`) | Browser transport shim, shared renderer, base map |
| `/healthz` | adapter | Readiness |
| `/api.php` | PHP-FPM | Upstream bot API (Bearer auth) |
| `/map.php`, `/gamefile.php` | PHP-FPM | Upstream public map renderer and game-file fallback |
| `/events` | Node SSE | Upstream live updates |
| `/cache/games/<id/100>/<id>/{game,status,history,messages}.json`, `/variants/Classic/cache/variant.json` | disk | Upstream public game files |
| `/ajax.php`, `/gamemaster.php` | PHP-FPM, loopback only | Board order saves via the tunnel; the gamemaster tick |

## Episode lifecycle

`adapter/episode.py` owns one episode. Upstream advances every phase; the adapter
only touches the game at the start and the end, through small PHP scripts that
bootstrap upstream's own code (`php/wdc_bootstrap.php`).

| Script | Called by | Does |
| --- | --- | --- |
| `wdc_install.php` | bake | Registers Classic in `wD_VariantInfo` |
| `wdc_create_game.php` | `Episode.__init__` | One transaction: `processGame::create` (Unranked, `MemberVsBots`), seven `User` accounts `Seat1`–`Seat7`, one `wD_ApiKeys` row per seat token, memberships in seed-shuffled countries |
| `wdc_state.php` | every tick | Consistent snapshot of the game row, member rows and public file URLs/versions |
| `wdc_start.php` | tick, when 7 seats are connected or `player_connect_timeout_seconds` passes | Sets `processTime` to now so the gamemaster starts the game |
| `wdc_end.php` | tick, at the year cap or `episode_budget_seconds` | Takes upstream's `gamemaster` lock and calls `setDrawn()` |
| `wdc_map.php` | tick, once per new phase (`render_maps`) | Runs upstream `map.php` as a guest for a public PNG |

Each tick: read state; record a phase transition; read the public files from disk
and wait (up to 10 s) until their versions match the committed row; render the
map; append or replace the replay frame; start or end the game when due. When
upstream reports `Finished`, or the game row disappears (cancel), `finish()`
computes scores and writes the replay and results to `COGAME_SAVE_REPLAY_URI` and
`COGAME_RESULTS_URI`, then sends `game_over` to connected players and waits up to
`completion_timeout_seconds` for their `game_over_ack`.

`adapter/routes.py` serves the WebSockets. `/player` checks the slot and token
(constant-time), validates the Host header, sends `hello`, then `game_started`
and `game_over`. In browser mode it hands requests to `adapter/tunnel.py`, which
replays them to upstream on loopback with the seat's Bearer key and an allowlist
(see [protocol](protocol.md#browser-transport)). `/global` pushes the latest
public frame whenever it changes.

## Player side

| Module | Role |
| --- | --- |
| `players/launcher.py` | Connects to `COWORLD_PLAYER_WS_URL` with `mode=bot`, reconnects on drop, starts the bot once with `WEBDIP_*` env, runs the press archive worker, stops the bot's process group and acks `game_over` |
| `players/press.py` | Separate process: snapshots the seat's private messages every 2 s and writes the final archive to stdout and `COWORLD_PLAYER_ARTIFACT_UPLOAD_URL` |
| `players/api.py` | Synchronous upstream API client, order helpers, `verify_orders` |
| `players/bridge.py` | Loopback HTTP API for an external bot controlling a human seat through the existing WebSocket tunnel |
| `players/legal_orders.py` | Classic legal-order generator from `variant.json` and `game.json` |
| `players/random_bot.py`, `players/hold_bot.py` | The two bundled policies |
| `players/examples/herald_bot.py` | Stdlib-only third-party example built from the docs |
| `players/scenarios.py` | Scripted API players for `WEBDIP_MODE` regression runs and stock comparison |

## Browser clients

| File | Role |
| --- | --- |
| `adapter/client/player.html` | Wrapper with help row and a same-origin iframe of the upstream board |
| `adapter/client/shim.js` | Replaces fetch, XMLHttpRequest and EventSource in the board with tunnel messages; reconnect policy |
| `adapter/viewer.html`, `adapter/client/viewer.js` | Shared renderer for the live `/client/global` view and the static replay bundle |

## Tools

All under `tools/`; see the README for which to run when.

| Tool | Checks |
| --- | --- |
| `check_boot.py` | Image boots with all capabilities dropped; crash and DNS failure handling |
| `check_episode.py` | Lifecycle edge cases: bad tokens, reconnects, stale orders, votes, deadlines |
| `check_browser.py`, `check_browser_scenarios.py`, `check_browser_boundaries.py`, `play_proxy.py` | Real Chromium play, directly and through a simulated play proxy; tunnel authorization |
| `check_random.py`, `check_legal_corners.py` | Generated orders round-trip through upstream unchanged |
| `check_press.py` | Private press stays private in logs, ZIPs and replay |
| `check_compatibility.py`, `stock_stack.py`, `stock_prepare.php` | Same API scenarios against stock upstream compose |
| `check_herald.py` | The documented Herald episode's press, holds and draw |
| `check_bridge.py` | External HTTP client through the local bridge and simulated lobby proxy, including saved orders, press privacy and completion |
| `check_replay.py` | Static replay bundle in Chromium, with no game container |
| `player_fixture.py` | Shared fixture: fresh hardened game containers for player checks |
| `sync_manifest_docs.py` | Copies README and docs into the manifest template |
| `build_replay_viewer.sh` | `coworld build` hook for the static replay bundle |

CI (`.github/workflows/adapter-tests.yml`) runs unit tests, ruff, the Herald
episode and most of these checks on each push and pull request; the workflow file
is the exact list.

## Environment variables

| Variable | Set by | Read by |
| --- | --- | --- |
| `COGAME_CONFIG_URI`, `COGAME_RESULTS_URI`, `COGAME_SAVE_REPLAY_URI` | Coworld runner | `adapter/boot.py`, `adapter/episode.py` |
| `COGAME_RESULTS_METHOD`, `COGAME_SAVE_REPLAY_METHOD` | Coworld runner (optional, `PUT` default) | `adapter/artifacts.py` |
| `WEBDIP_MODE` | You, for regression runs | `adapter/boot.py` |
| `COWORLD_PLAYER_WS_URL` | Coworld runner | `players/launcher.py` |
| `COWORLD_PLAYER_ARTIFACT_UPLOAD_URL`, `COWORLD_PLAYER_ARTIFACT_UPLOAD_METHOD` | Coworld runner (optional) | `players/press.py` |
| `WEBDIP_URL`, `WEBDIP_API_KEY`, `WEBDIP_GAME_ID`, `WEBDIP_COUNTRY_ID`, `WEBDIP_SEED` | Launcher | The bot |
| `WEBDIP_STOCK_SUBNET` | You (optional) | `tools/stock_stack.py` (compatibility check) |
