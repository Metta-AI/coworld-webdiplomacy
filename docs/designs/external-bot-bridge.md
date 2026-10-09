# External bot HTTP bridge

## Purpose and scope

Let a bot on a user's machine play a claimed human lobby seat without uploading
its code or a policy. Reuse the platform's player WebSocket proxy and the game's
seat-authenticated tunnel. This does not give the bot a ranked policy identity.
No Metta networking changes or upstream webDiplomacy edits are required.

## Architecture and decisions

`bot -> loopback HTTP bridge -> authenticated WSS -> Tunnel -> upstream HTTP`

The bridge accepts a private file containing a player viewer URL, player WebSocket
URL, or the JSON response from the lobby launch API. It resolves the viewer's
`address` parameter (or derives `/player`), preserving proxy prefixes and seat
credentials. Remote transport requires WSS; plain WS is allowed only on loopback
for local testing. It explicitly selects browser mode for direct connections.

The tunnel adds `game/orders` (POST) and `game/togglevote` (GET), alongside its
existing context, press, vote and public-file routes. Game and country IDs in
both query and JSON body must match the authenticated seat; per-order country
IDs must also match. Upstream remains responsible for order legality and stale
turn checks. Browser signed-order saves and SSE remain unchanged. Hello advertises
`http-bot-api-v1`; the bridge refuses older servers rather than failing later
when the bot submits orders.

The bridge uses the existing `websockets.sync` client and stdlib `HTTPServer`.
The former supplies TLS, framing, ping/pong and receive deadlines. A receive
thread handles lifecycle messages even when the bot is idle; the HTTP server
serializes requests. Reconnect uses bounded backoff and checks seat identity.
No HTTP request is automatically replayed, including GET (upstream togglevote
mutates state). A lost or timed-out response is an uncertain outcome: return a
local error and require the bot to refetch before deciding what to do next.
Game-over is acknowledged and subsequent HTTP requests return 410. A
`seat_replaced` message stops reconnects in both browser and bridge; the bridge
then returns 409. This uses application data because proxies may discard close
codes. The bridge rejects bot-mode hello and malformed responses with 502.

Research: [websockets synchronous client](https://websockets.readthedocs.io/en/stable/reference/sync/client.html)
fits the repository's synchronous convention and is already installed. Adding
websocket-client would duplicate that dependency. FastAPI/uvicorn already exist
but would add another event loop for this small local utility. Python documents
[http.server](https://docs.python.org/3/library/http.server.html) as unsuitable for
public production serving; this bridge binds only to 127.0.0.1 and never serves
files. A generic TCP tunnel would still need our seat protocol and route controls.

## Local HTTP contract

- Bind only to IPv4 loopback, with a configurable port (0 chooses a free port).
- API calls require a fresh local Bearer key, unrelated to the hosted seat token.
  Public game JSON may be fetched without auth, matching existing bot clients.
- Reject browser Origin headers and unexpected Host values. No CORS support.
- Forward GET and POST paths/body through tunnel messages; do not forward client
  headers, cookies, or Authorization to upstream. The tunnel injects the real key.
- Preserve upstream status, body, Content-Type and X-JSON. Bound request bodies
  to 128 KiB and WebSocket responses to 16 MiB. SSE and arbitrary site endpoints
  are not exposed by the local bridge; polling is supported.
- Write shell-quoted WEBDIP_URL, WEBDIP_API_KEY, WEBDIP_GAME_ID,
  WEBDIP_COUNTRY_ID and WEBDIP_SEED to a newly created mode-0600 env file.
  Never print tokens, request paths, private payloads or exception messages.
- Return 503 while disconnected, 504 for a response deadline, and 410 after
  game-over. Reconnection never replays an in-flight request. Keep serving 410
  until the operator stops the bridge, so bot clients see a terminal condition.

## Validation and release

Unit and socket tests cover URL parsing, auth, bounds, HTTP fidelity, lifecycle,
reconnection and ambiguous-write handling. A Docker acceptance check runs an
ordinary WebDiplomacy client through the bridge and simulated platform proxy,
verifies saved orders and press, rejects other seats/games, and completes a game.
Existing browser checks protect signed-order and SSE behavior.

The hosted Coworld must be rebuilt and published before this works there. Local
implementation and acceptance do not establish hosted deployment. This task
keeps all changes and test images local.

## Implementation and local evidence

Implemented in `players/bridge.py`, `adapter/tunnel.py` and `adapter/routes.py`.
The external bot setup is in `docs/write-a-policy.md`; README and protocol
updates are embedded in the manifest. CI now runs the bridge socket tests and
Docker acceptance check.

Passed locally:

- `uv run ruff check adapter players tools` and `git diff --check`.
- Adapter unit suite (17 tests), existing player suite (7 tests), and bridge
  socket suite (11 tests). Manifest synchronization was checked again after the
  final documentation update.
- Image built with `docker build --platform linux/amd64 -f adapter/Dockerfile
  -t coworld-webdiplomacy-game:external-bridge .`.
- `uv run python -m tools.check_bridge coworld-webdiplomacy-game:external-bridge`:
  ordinary HTTP client through the bridge CLI and proxy query rewrite, order
  readback, native phase advance, stale-order error, press isolation, access
  boundaries, game-over and secret-free bridge/proxy logs.
- `uv run python -m tools.check_browser coworld-webdiplomacy-game:external-bridge`:
  both direct and proxied Chromium cases, retaining signed orders and SSE.

No hosted game was started and no image/Coworld was published. The upstream
submodule is unchanged. Release and a real hosted lobby smoke test remain the
steps required to make and verify this capability on hosted infrastructure.
