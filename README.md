# webDiplomacy Coworld

Packages the unmodified [webDiplomacy](https://github.com/kestasjk/webDiplomacy)
server for [Coworld](https://github.com/Metta-AI/coworld). Licensed under
AGPL-3.0; see [LICENSE](LICENSE).

The current implementation runs complete seven-seat episodes with API bots,
supervises the upstream services, records public replay snapshots and results,
and shuts down cleanly. Humans can use the upstream React board through a
seat-authenticated WebSocket tunnel. The bundled default bot selects random legal orders, and launchers save private press
to player logs and optional ZIP artifacts. A read-only live viewer and a standalone
static replay viewer show public positions, adjudicated orders, season maps and
public press. This revision has not been certified or uploaded.

## Build and check

Requires Docker with Linux amd64 support, Git, Python 3.12+, and uv.

```sh
git submodule update --init --recursive
uv sync --group dev
docker build --platform linux/amd64 -f adapter/Dockerfile -t coworld-webdiplomacy:local .
uv run python tools/check_boot.py coworld-webdiplomacy:local
uv run python tools/check_boot.py coworld-webdiplomacy:local --crash-service
uv run python -m unittest discover -s adapter -p 'test_*.py' -v
```

The boot check starts a fresh container with all Linux capabilities dropped and
privilege escalation forbidden. It requires health within 10 seconds of container start, checks
nginx/API/SSE responses, verifies every process remains root without capabilities,
checks the upstream gamemaster heartbeat, and requires exit 0 after SIGTERM. The crash check kills SSE and requires exit 1.

To inspect a running instance:

```sh
docker run --name webdip-local --platform linux/amd64 --cap-drop=ALL \
  --security-opt no-new-privileges -p 127.0.0.1:8080:8080 coworld-webdiplomacy:local
# From another terminal:
curl http://127.0.0.1:8080/healthz
curl -i http://127.0.0.1:8080/api.php
docker stop --time 45 webdip-local
docker rm webdip-local
```

The API deliberately returns HTTP 400, `No route provided.`, when called without
a route. `/healthz` returns HTTP 200 with `{"status":"ok"}` only after dependencies
are ready. Everything outside the explicit nginx route list returns 404.

## Runtime

`adapter/boot.py` supervises Redis, MariaDB, PHP-FPM, nginx, and the upstream Node
SSE server. `config/` holds their configuration. Only nginx listens publicly on
8080; MariaDB, Redis, FPM, and the health server listen on loopback. SSE uses a
private Unix socket. The SSE server calls the loopback-only `gamemaster.php`;
the adapter does not advance games.

All processes retain root identity, with no capabilities or runtime ownership
changes. Nginx uses single-process mode to avoid its root worker's `initgroups`
call. This limits nginx to one worker and precludes graceful worker replacement;
restart the container to change configuration. PHP has four workers.

The image bakes the upstream database schema, Classic map, and `wD_VariantInfo`.
It contains no episode users or games. Boot generates fresh application secrets,
unlocks and rotates the database application account, and initializes the
upstream downtime heartbeat. No database installation occurs at runtime.
Generated upstream configuration/cache files exist only inside the image or
container; never edit or generate files in the source submodule.

Public stdout contains service status and public phase/completion events. Daemon and application diagnostics
are private files under `/run/webdip/logs`; inspect them locally with `docker exec`.
They may contain sensitive information and must not be published. Player/API access logs
are disabled. A private gamemaster timing log contains only timestamp, duration,
and HTTP status, never the request URL or secret. Email delivery is disabled through a local sendmail sink.

SIGTERM stops ingress and the gamemaster producer before PHP, MariaDB and Redis.
Unexpected daemon exits fail the container. A forced shutdown produces nonzero
exit status. Allow 45 seconds for a worst-case shutdown.

## Run an episode

```sh
uv run coworld build --version 0.5.0
DOCKER_DEFAULT_PLATFORM=linux/amd64 uv run coworld run-episode \
  dist/coworld_manifest.json --output-dir tmp/episode --timeout-seconds 60
```

The current certification fixture selects seven hold bots, one-minute NoPress
phases, and the 1901 year cap. A successful run produces `results.json`, a public
`replay` JSON array, and separate game/player logs. This runs the fixture locally;
it is not a certification claim. The default bundled player is the random legal bot;
the certification roster explicitly selects the hold bot.

The [player protocol](docs/protocol.md) explains hello, upstream HTTP play,
reconnection, deadlines, scoring and output. The launcher can run another bot:
`python -m players.launcher python -m your_bot`. It passes the upstream URL,
key, game ID, country ID and a distinct seed derived from episode seed and slot
through environment variables. Omitted episode seeds are randomly chosen and
recorded in results and replay; explicit seeds remain reproducible.
The random player checks saved orders against its requests and fails visibly on
a current-phase rejection. Legal orders may still bounce or lose support.
See [player validation](docs/players.md) for the generator, private archives and
stock-upstream compatibility checks.

## Browser play

Open `/client/player?slot=N&token=TOKEN` on a running episode. The page also
accepts `address`, the complete player WebSocket URL supplied by a play proxy.
Treat these URLs as credentials. The upstream board is built from the pinned
submodule without modifying its source or compiled bundles.

Select a unit, choose an order, and select its destination. For Support hold,
select Support and click the supported province **twice**. Orders auto-save;
Ready allows the phase to finish when all seats are ready. The board receives
phase updates live, then offers a **New phase** arrow to move from the completed
turn to the current board. No page reload is needed. Press `P` to open chat;
choose ALL for public press or a country for private press, then press Enter to
send. Chat requires a press-enabled episode.

Sandbox/practice games, legacy-board links, site navigation, advertisements and
telemetry are unavailable. Unsupported navigation and sandbox controls show a
notice. A dismissible help panel explains Ready, phase navigation, press and
Support hold. Disconnects show a notice and retry automatically up to eight times,
with delays from 0.5 to 5 seconds. Reconnection refreshes state and subscriptions;
interrupted commands are not replayed. After exhausted retries, reload the seat link.

Run the real-browser checks with [Playwright](https://playwright.dev/python/docs/library):

```sh
uv run playwright install chromium --only-shell
uv run python -m tools.check_browser coworld-webdiplomacy-game:latest
uv run python -m tools.check_browser_scenarios coworld-webdiplomacy-game:latest
```

On Linux, install browser system dependencies with Playwright's documented
`install --with-deps` option if needed. The checks create fresh restricted
containers, use mouse/keyboard actions for the human seat, verify saved orders
and press privacy, and save screenshots under `tmp/p3-shots/` and `tmp/p5-*`.
The scenario checks cover army builds, retreats, convoy orders, Draw votes and
public spectating. They test direct
access and a GET-only buffered proxy with separate viewer/runtime tokens, a
non-root prefix, and a cross-origin sandboxed iframe. Evidence JSON and local
credentials live in ignored `tmp/p3-*` directories; do not publish those folders.
These checks simulate proxy behavior; they are not hosted acceptance tests.

## Regression checks

```sh
uv run python -m tools.check_episode coworld-webdiplomacy-game:latest
for mode in smoke tactics convoy; do
  docker run --rm --platform linux/amd64 --cap-drop=ALL \
    --security-opt no-new-privileges -e WEBDIP_MODE="$mode" coworld-webdiplomacy-game:latest
done
```

The lifecycle checks exercise invalid tokens, ping/pong, immediate global state,
reconnection, stale orders, concurrent finalization, draw/cancel/pause votes, and
a missing seat's natural one-minute deadline. Each regression mode starts real
API players and lets the upstream loop adjudicate; it never calls `process()` or
applies votes itself. Scenario diagnostics remain in the container's private
`/run/webdip/logs/scenario.log`; omit `--rm` when investigating a failure.

## Spectate and replay

Open `/client/global` on a running episode for a read-only public view. The page
supports the proxy's `address` parameter. No seat token is needed by the game;
the platform may enforce its own spectator access policy.

`coworld build` generates a self-contained bundle under `build/static-replay-viewer`.
The static viewer opens `index.html#replay=<encoded URL>` (legacy `?replay=` also
works), without a game container. Both views use the same renderer. Replay controls
provide autoplay, pause, phase selection, speed and optional looping. Public history
includes completed orders; a separate expandable PNG shows the upstream season
adjudication. Current positions and season adjudications are labeled separately.

```sh
tools/build_replay_viewer.sh "$PWD/build/static-replay-viewer"
uv run python -m tools.check_replay tmp/episode/replay
```

The hook recreates the bundle directory and includes all assets locally. The browser
check serves only static files, checks compressed and uncompressed replay data,
readiness, playback and visible errors. See [replay format and limitations](docs/replay.md).
The legacy game-container replay server has been removed.

Use project-local tools: `uv run coworld` (0.1.55) and `uv run softmax` (0.26.38).

## Source

Source: [Metta-AI/coworld-webdiplomacy](https://github.com/Metta-AI/coworld-webdiplomacy/tree/main).
The `webdiplomacy/` submodule pins the upstream revision in Git. An optional deterministic [source bundle](SOURCE_BUNDLE.md)
combines both repositories for distribution. The Git history preserves credit
to the original adapter prototype.
