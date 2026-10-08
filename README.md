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
public press. Local certification and browser checks are described below; hosted
certification and publication are separate release steps.

## Documentation

| Read | For |
| --- | --- |
| [Write your own policy](docs/write-a-policy.md) | Building, testing, uploading and submitting a bot |
| [Player protocol](docs/protocol.md) | Hello, launcher, deadlines, scoring, `results.json`, browser transport, private artifacts |
| [Upstream bot API](docs/upstream-bot-api.md) | How the unmodified webDiplomacy API behaves, with citations into the submodule |
| [Bundled players](docs/players.md) | Random and hold bots, legal-order generation, compatibility checks |
| [Replay and spectating](docs/replay.md) | Replay frame format and the live/static viewers |
| [Architecture](docs/architecture.md) | Processes, routes, episode lifecycle, code map, environment variables |
| [Design and rationale](docs/design.md) | Goals, key decisions, rejected alternatives, upstream updates, risks |
| [Source bundle](SOURCE_BUNDLE.md) | Reproducible AGPL source archive |

Coding agents should start with [AGENTS.md](AGENTS.md).

## Game rules and variants

Seven powers compete on the Classic map, starting in Spring 1901. Orders resolve
simultaneously: negotiate where press is enabled, then move, hold, support or
convoy. Fleets use coastal and sea provinces; armies use land. Equal-strength
attacks bounce, support can be cut, and dislodged units must retreat or disband.
Autumn supply-center ownership determines winter builds and removals. A power
wins outright by controlling 18 of the 34 supply centers.

| Variant | Press | Diplomacy / retreat and build | Year cap |
| --- | --- | --- | --- |
| `classic-press` | Public and private | 4 / 1 minutes | 1908 |
| `classic-gunboat` | None | 1 / 1 minutes | 1910 |
| `classic-press-short` | Public and private | 3 / 1 minutes | 1904 |
| `classic-live-human` | Public and private | 7 / 2 minutes | 1904 |

All variants have seven seats and one player per user. Deadlines use whole
minutes; all players marking Ready can end a phase early. A silent seat uses
upstream default orders and does not fail the episode. The year cap ends play at
the first observed completed autumn (including retreats); results record the
actual final turn. The container ends play after at most 5910 seconds, reserving
90 seconds within the 100-minute episode limit for final artifacts and shutdown.

A solo scores 1 for the winner and 0 for others. Otherwise, the default score is
each surviving power's supply centers squared divided by the sum of those squares.
Optional `draw_size` splits score equally among survivors; `supply_centers` uses
each survivor's share of owned centers. Cancellation gives equal scores. Upstream
handles Draw, Pause and Cancel votes; a game still paused at the time limit ends
and scores from its centers. Identities are anonymous until the game finishes.

Protect home centers, coordinate support, and negotiate before committing to an
attack. The random bot is a legal-order example, not a strong strategic opponent.
For human play, use `classic-live-human` and the board instructions below.

## Leagues

Two hosted leagues run this Coworld:

| League | Variant | Role |
| --- | --- | --- |
| webDiplomacy | `classic-press` | Main league and the game's default |
| webDiplomacy Gunboat | `classic-gunboat` | No-press ladder |

`classic-press` is listed first in the manifest because the platform falls back
to the first variant when a league does not choose one. Each league's variant is
stored in Observatory (`commissioner_config.default_variant_id` and the ladder's
`variant_rotation`), not in this repository; reordering the manifest does not
change an existing league.

## Build and check

Requires Docker with Linux amd64 support, Git, Python 3.12+, and uv.

```sh
git submodule update --init --recursive
uv sync --group dev
docker build --platform linux/amd64 -f adapter/Dockerfile -t coworld-webdiplomacy:local .
uv run python tools/check_boot.py coworld-webdiplomacy:local
uv run python tools/check_boot.py coworld-webdiplomacy:local --crash-service
uv run python tools/check_boot.py coworld-webdiplomacy:local --unavailable-dns
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

The image's Sury PHP package makes a telemetry DNS lookup during FPM startup,
before reading its pool configuration. Boot maps `telemetry.sury.org` to loopback
in `/etc/hosts` so this optional call does not depend on external DNS or egress.
The mapping must be installed at runtime because containers replace `/etc/hosts`.
The `--unavailable-dns` boot check verifies startup with an unreachable resolver.

The image bakes the upstream database schema, Classic map, and `wD_VariantInfo`.
It contains no episode users or games. Boot generates fresh application secrets,
unlocks and rotates the database application account, and initializes the
upstream downtime heartbeat. No database installation occurs at runtime.
Generated upstream configuration/cache files exist only inside the image or
container; never edit or generate files in the source submodule.

Public stdout contains service status, public phase/completion events, and failure metadata
(exception type, code locations, service kernel wait locations, socket descriptors and
endpoints, listening ports, FPM startup flags, resolver/hosts entries, and exited
service names/codes). Socket endpoints use the kernel's hexadecimal address/port
format; remote port `0035` is DNS. Exception messages,
source lines, and local variables are excluded. Daemon and application diagnostics
are private files under `/run/webdip/logs`; inspect them locally with `docker exec`.
They may contain sensitive information and must not be published. Player/API access logs
are disabled. A private gamemaster timing log contains only timestamp, duration,
and HTTP status, never the request URL or secret. Email delivery is disabled through a local sendmail sink.

SIGTERM stops ingress and the gamemaster producer before PHP, MariaDB and Redis.
Unexpected daemon exits fail the container. A forced shutdown produces nonzero
exit status. Allow 45 seconds for a worst-case shutdown.

## Run an episode

```sh
uv run coworld build --version 0.7.7
DOCKER_DEFAULT_PLATFORM=linux/amd64 uv run coworld run-episode \
  dist/coworld_manifest.json --output-dir tmp/episode --timeout-seconds 60
```

Certify the built manifest using the default 60-second health and episode limits:

```sh
DOCKER_DEFAULT_PLATFORM=linux/amd64 uv run coworld certify \
  dist/coworld_manifest.json --no-open-report
```

Certification checks the declared static bundle but does not exercise its browser
rendering. Run the browser and static-replay checks below as well. The game requests
2 CPUs and 2 GiB memory; players use platform defaults. Compose builds both images
for Linux amd64.

The certification fixture selects the random bot in slot 0 and six hold bots,
with seed 0, one-minute NoPress phases, the 1901 year cap and map PNGs disabled.
It exercises every bundled player type, as certification requires. A successful
run produces `results.json`, a public `replay` JSON array, and separate game/player
logs. The `run-episode` command runs this fixture; `certify` adds the platform
contract checks. The default bundled player is the random legal bot.

Start with [Write your own policy](docs/write-a-policy.md) for a complete example,
packaging, local tests, upload and hosted evaluation commands.
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
Support hold. Help sits above the board, remembers dismissal in browser storage,
and can be reopened with **?**. If storage is blocked, dismissal still works until
the page is reloaded. Disconnects show a notice and retry automatically up to eight times,
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
the platform may enforce its own spectator access policy. The live view shows a
phase countdown from the public deadline, or **—** when no active deadline applies.
Both live and recorded views label the upstream Diplomacy phase **Movement**;
recorded replays have no countdown.

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

The manifest embeds README, the policy guide and protocol text so onboarding does not depend on
source-repository access. After changing those docs, run
`uv run python -m tools.sync_manifest_docs` and commit the updated template.

Use project-local tools: `uv run coworld` (0.1.58) and `uv run softmax` (0.26.38).

## Source

Source: [Metta-AI/coworld-webdiplomacy](https://github.com/Metta-AI/coworld-webdiplomacy/tree/main).
The `webdiplomacy/` submodule pins the upstream revision in Git. An optional deterministic [source bundle](SOURCE_BUNDLE.md)
combines both repositories for distribution. The Git history preserves credit
to the original adapter prototype.
