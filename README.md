# webDiplomacy Coworld

Packages the unmodified [webDiplomacy](https://github.com/kestasjk/webDiplomacy)
server for [Coworld](https://github.com/Metta-AI/coworld). Licensed under
AGPL-3.0; see [LICENSE](LICENSE).

The current implementation runs complete seven-seat episodes with API bots,
supervises the upstream services, records public replay snapshots and results,
and shuts down cleanly. Browser play, the random default bot, private press
artifacts, and complete replay presentation are under development. This revision
has not been certified or uploaded.

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
uv run coworld build --version 0.2.0
DOCKER_DEFAULT_PLATFORM=linux/amd64 uv run coworld run-episode \
  dist/coworld_manifest.json --output-dir tmp/episode --timeout-seconds 60
```

The current certification fixture selects seven hold bots, one-minute NoPress
phases, and the 1901 year cap. A successful run produces `results.json`, a public
`replay` JSON array, and separate game/player logs. This runs the fixture locally;
it is not a certification claim. The temporary default player is the hold bot;
the planned random legal bot will replace it.

The [player protocol](docs/protocol.md) explains hello, upstream HTTP play,
reconnection, deadlines, scoring and output. The launcher can run another bot:
`python -m players.launcher python -m your_bot`. It passes the upstream URL,
key, game ID and country ID through environment variables.

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

The old native observation/action protocol and direct engine-advance helper have
been removed. Replay-only startup with `COGAME_LOAD_REPLAY_URI` retains the
prototype viewer and bypasses database services. Full browser and replay UX
validation will follow in their implementation phases.

Use project-local tools: `uv run coworld` (0.1.55) and `uv run softmax` (0.26.38).

## Source

Source: [Metta-AI/coworld-webdiplomacy](https://github.com/Metta-AI/coworld-webdiplomacy/tree/main).
The `webdiplomacy/` submodule pins the upstream revision in Git. An optional deterministic [source bundle](SOURCE_BUNDLE.md)
combines both repositories for distribution. The Git history preserves credit
to the original adapter prototype.
