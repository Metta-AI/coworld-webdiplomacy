# webDiplomacy Coworld private prototype

This adapter runs the actual webDiplomacy PHP adjudicator with a private MariaDB database and Redis inside one game container. Seven container players connect by WebSocket. The upstream source remains unmodified.

## Build and verify

Fetch the pinned upstream checkout before building:

```sh
git clone https://github.com/kestasjk/webDiplomacy.git upstream
git -C upstream checkout "$(cat UPSTREAM_COMMIT)"
docker compose build
uvx --from 'coworld[auth] @ git+https://github.com/Metta-AI/coworld.git@main' coworld build --version 0.1.1
uvx --from 'coworld[auth] @ git+https://github.com/Metta-AI/coworld.git@main' coworld certify dist/coworld_manifest.json --timeout-seconds 240 --no-open-report
docker tag coworld-webdiplomacy-game:latest coworld-webdiplomacy-local:latest
docker tag coworld-webdiplomacy-player:latest coworld-webdiplomacy-player-local:latest
./adapter/local_episode.sh
```

The script prints the local replay viewer URL, artifacts directory and replay container name. The game exits after writing artifacts; standalone replay remains available. Containers and their dedicated network remain available for inspection. Stop only the resources named for that run when finished.

The starter holds units, disbands retreats and waives builds. It votes for a draw after three turns. It is a readable protocol example, not a competitive policy. A configured phase cap draws remaining players using the upstream draw adjudication; scores split one point among surviving drawn members. A solo winner receives one point. Defeated members receive zero.

Each game owns an empty database. Its PHP API and database listen only on loopback; player containers use a separate network namespace. Accounts are ordinary game members so upstream draw voting includes them. Upstream `Bot` accounts cannot vote and mixed games automatically end when only bots remain.

## Protocol

`/player?slot=N&token=TOKEN` authenticates one of seven seats. Seat 0 is country 1, through seat 6/country 7. Duplicate connections are rejected, including simultaneous connection attempts.

The server sends `{"type":"observation","context":...,"public":...}` once per phase. `context` contains that member's orders and private messages. `public` contains upstream versioned game, history, map, status and global-message data. It never contains private messages. API keys and upstream SSE credentials are not passed to players.

Reply with `turn`, `phase`, `orders`, optional `messages` and optional Boolean `draw`. Order fields match `upstream/api/README.md`. Messages use `toCountryID` (0 means public) and `message`. Each active seat submits exactly one action per observed phase. Stale, duplicate, malformed, oversized or rejected input ends the episode with a typed, atomically published failure for that seat. Connection, socket-send and action deadlines are bounded; sends and actions share the phase deadline. Known eliminated seats cannot abort remaining players. Upstream validates ownership and legality of orders. Draw reflects a desired vote state, not a toggle. The server sends `{"type":"finished","scores":[...]}` before closing players.

The adapter uses the September 20 API: `game/playercontext`, public versioned JSON, `game/orders`, `game/sendmessage` and `game/togglevote`. Removed routes such as `game/status` are not used.

`/healthz`, `/global`, `/client/global`, `/replay` and `/client/replay` expose readiness and public state. The current viewer prints structured public state, with automatic replay advancement and looping. It is an engineering viewer, not the upstream map interface. Private messages never enter public replay or game stdout.

## Validation and remaining work

`WEBDIP_MODE=tactics` tests movement, builds, supported attack and retreat against the real engine. `WEBDIP_MODE=smoke` runs `adapter/smoke.py` inside a fresh game image, testing seven API seats, four phase cycles, unanimous draw and private-message visibility. `adapter/local_episode.sh` exercises the game and seven separate container players and retains results, replay and all logs.

The unit suite covers player faults and artifact paths; GitHub Actions runs it on pushes and pull requests. Engine integration and Coworld certification are separate local checks.

Local Coworld certification passes all 10 `coworld-executable` steps, including the seven-player episode, results, public WebSocket Ping/Pong, player-client route and replay loading. The author retains the local transcript and episode artifacts.

This remains a private prototype. Remaining work:

- Convoy, elimination, solo-win and malformed/missing-order fixtures. The current tactical test covers movement, two builds, supported dislodgement and a successful retreat.
- A map-based viewer and browser verification of the raw JSON human player client.
- Reconnect support; current active-seat disconnections are terminal player failures.
- Bounded press exchanges within a phase; this first protocol exchanges messages alongside submitted orders.
- Hosted stack validation. The game and player images build for `linux/amd64`; artifact inputs and outputs support `file://` and HTTP(S).
- Dependency/image pinning and startup measurements against hosted limits.
- CICERO adaptation and negotiation compatibility.

Keep the upstream AGPL license with any distribution. This private prototype requires review before any external rollout.
