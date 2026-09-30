# webDiplomacy Coworld

Packages the unmodified [webDiplomacy](https://github.com/kestasjk/webDiplomacy)
server for [Coworld](https://github.com/Metta-AI/coworld). Licensed under
AGPL-3.0; see [LICENSE](LICENSE).

The current implementation provides the container image, a preinstalled Classic
map and database, supervised services, health checks, and graceful shutdown.
Episode orchestration, bot launchers, and browser play are under development.
This revision is not ready for certification or hosted games.

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

Public stdout contains service status only. Daemon and application diagnostics
are private files under `/run/webdip/logs`; inspect them locally with `docker exec`.
They may contain sensitive information and must not be published. Access logs
are disabled. Email delivery is disabled through a local sendmail sink.

SIGTERM stops ingress and the gamemaster producer before PHP, MariaDB and Redis.
Unexpected daemon exits fail the container. A forced shutdown produces nonzero
exit status. Allow 45 seconds for a worst-case shutdown.

## Development status

The original prototype's scenario sources (`smoke.py`, `tactics.py`, `convoy.py`),
engine helper, protocol tests and player are retained while game control is
migrated. Their old `WEBDIP_MODE` image entrypoints are not yet wired to the new
architecture. Unit tests cover those retained helpers; they do not establish
that an episode runs in this image. The manifest and player image still describe
the prototype and will be replaced before certification.

Replay-only startup with `COGAME_LOAD_REPLAY_URI` retains the prototype viewer
and artifact handling and bypasses all database services. The replay format will
be expanded alongside episode orchestration.

Use project-local tools: `uv run coworld` (0.1.55) and `uv run softmax` (0.26.38).

## Source

Source: [Metta-AI/coworld-webdiplomacy](https://github.com/Metta-AI/coworld-webdiplomacy/tree/main).
The `webdiplomacy/` submodule pins the upstream revision in Git. An optional deterministic [source bundle](SOURCE_BUNDLE.md)
combines both repositories for distribution. The Git history preserves credit
to the original adapter prototype.
