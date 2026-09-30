# Player lifecycle protocol

Connect to `/player?slot=N&token=TOKEN` with a Coworld seat's credentials. An
invalid slot or token is rejected before WebSocket acceptance (HTTP 403).
WebSocket ping/pong is supported. Tokens are seat capabilities; never publish
them or put them in game logs. The server does not log player access URLs.

The first message is:

```json
{
  "type": "hello",
  "protocol": "webdip-coworld/1",
  "slot": 0,
  "webdip": {
    "base_url": "http://game:8080",
    "api_key": "<seat token>",
    "game_id": 1,
    "country_id": 5,
    "country": "Austria"
  },
  "rules": {"seed": 0, "end_year": 1910},
  "source_url": "https://github.com/Metta-AI/coworld-webdiplomacy/tree/main"
}
```

`rules` contains all episode settings except tokens. Country assignment is a
seeded permutation; results are always in **slot order**, not country order.
The base URL preserves the connection's Host header, including its port.
With `mode=browser`, hello omits `api_key`; the token in the browser URL is still
its seat capability. The launcher explicitly adds `mode=bot`. Connections carrying
`protocol_version` also default to browser mode unless they explicitly select
`mode=bot`: a lobby proxy can replace the query, discarding custom mode flags
and substituting a runtime token. This keeps that runtime key out of browser hello.

The launcher sets `WEBDIP_URL`, `WEBDIP_API_KEY`, `WEBDIP_GAME_ID`, and
`WEBDIP_COUNTRY_ID` for its bot subprocess. Bots use upstream HTTP routes directly,
with `Authorization: Bearer <api_key>`. The adapter never submits their actions.
`game/setvote` returns plain text; context and order responses are JSON.
See the [upstream API reference](../webdiplomacy/api/README.md).

Lifecycle messages after hello:

- `{"type":"game_started"}`: upstream has left Pre-game. Reconnecting players
  receive this again when the game has already started.
- `{"type":"game_over","results":{...}}`: replay and results have been written.
  Reply with `{"type":"game_over_ack"}` when done. The server waits at most
  `completion_timeout_seconds` (default 20), ending sooner when all connected
  seats acknowledge. The launcher terminates its child and exits 0.

A reconnect replaces that seat's previous socket. Losing a connection or sending
an invalid/stale HTTP order does not fail the episode. The upstream API handles
order errors; a silent seat keeps the engine's default orders (holds, disbands,
or skipped builds). The next phase still waits for its native deadline unless
all required players are Ready. Phase lengths are whole minutes.

## Game lifecycle and output

The server creates seven ordinary User accounts and no extra API permissions.
The game is Unranked, bet zero, MemberVsBots. It starts when all seven launchers
are present or the connection deadline expires; the adapter only sets the initial
process time. Upstream applies Ready, deadlines, votes, wins, and elimination.

The year cap is the first observed state after the selected autumn and its
retreats, including autumn Builds or the following spring. Observation can miss
a phase boundary; the actual final turn is recorded. Finalization takes the
upstream gamemaster lock and preserves any outcome already completed. The time
budget also ends paused games. Cancellation erases the upstream game; results
record `cancelled` and preserve previously observed public replay frames.

Default non-solo scores are SC² / total surviving SC². `supply_centers` uses
SC / total surviving SCs; `draw_size` gives equal shares to survivors. A solo
winner receives 1 and everyone else 0. Cancellation gives each seat 1/7; the
zero-center fallback also gives equal shares. Results include the country map,
seed, members' final center counts, actual final state, observed transition
elapsed times, and completed gamemaster request timing summaries.

Replay is currently a JSON array of upstream **public** variant/game/status/
history/messages snapshots and public lifecycle state. Private player contexts,
private press, tokens, and pending secret orders are never recorded. Public files
are checked against their committed version identifiers before recording.
The final replay snapshot carries an `ending` outcome and reason. On cancellation,
that snapshot retains the last observed board; it does not invent an erased final
state. Cancelled results have no final game state. Full replay presentation is still
under development.

`/global` immediately sends the latest public snapshot, then updates it as it
changes. `/client/global` is a placeholder until browser spectating is implemented.

## Browser transport

`GET /client/player?slot=N&token=TOKEN&address=WEBSOCKET_URL` serves a wrapper.
`address` is optional; without it the wrapper derives `/player` from the current
prefix and origin. It requests browser mode and loads the unmodified React build
from static files beneath `/client/`. The build uses the pinned upstream npm
lockfile and `PUBLIC_URL=.`. No browser cookies or session authentication are used.

The shim replaces fetch, XMLHttpRequest and EventSource with WebSocket messages:

- `request`: `{type, id, method, path, body}`. `path` is an upstream absolute path
  including query parameters, never an origin. `body` is a string (JSON for API
  writes, form encoding for signed order saves), limited to 128 KiB.
- `response`: `{type, id, status, headers, body}`. Only upstream `content-type`
  and `x-json` headers are returned. HTTP errors remain errors. The signed-order
  `X-JSON` response is preserved, including validation failures.
- `subscribe`: `{type, id, path}`. Only `have` and `since` are used from the event
  query. The server obtains SSE auth and fixes all channels to this game/seat.
  It sends `event_open`, `event` (with upstream `data`), or `event_error`, carrying
  the same `id`. `unsubscribe` with that `id` closes the stream.

The adapter supplies Authorization server-side, strips cookies, refuses redirects,
and forwards only `game/playercontext`, `game/sendmessage`, `game/messagesseen`,
`game/setvote`, `game/markbackfromleft`, this game's four public JSON files, and
Classic's variant JSON. `ajax.php` is loopback-only and accepts only signed order
saves whose context matches the authenticated game, user and country. Upstream
still verifies the signature and orders. Client headers, destinations and SSE
channel choices cannot override the seat binding. Unsupported requests return 403;
upstream connection failures return 502. HTTP forwarding has a 15-second timeout.

The wrapper's meta CSP survives header-stripping proxies and blocks external
scripts, images, forms and fonts. The compiled board initializes Google Analytics,
so an expected CSP refusal appears in the browser console. The shim disables
sendBeacon, and the server refuses client telemetry routes because those payloads
can include credential-bearing page URLs. No ads or analytics HTML is included.
The shim implements the network interfaces used by this pinned board; it is not
a general-purpose browser networking polyfill.

Local validation: `tools/check_browser.py` drives Chromium, while
`tools/play_proxy.py` simulates a GET-only, five-second buffered play proxy with
no forwarded cookies or response headers except Content-Type. It includes the
lobby's player-query rewrite and iframe sandbox restrictions. The test also
checks rejection of other seats' signed contexts and off-game routes. It does
not prove behavior on a deployed platform or every browser.

## Configuration

[config-schema.json](../config-schema.json) is generated from
`adapter.config.EpisodeConfig` and is also included in the manifest template.
Key defaults: one-minute phases, one-minute retreats/builds, NoPress, anonymous
until Finished, year cap 1910, connection timeout 180 seconds, episode budget
5910 seconds, completion timeout 20 seconds. Phase lengths are limited to 1–59
minutes so upstream treats the game as live and does not auto-start a full lobby.
The 5910-second maximum reserves 90 seconds below the 100-minute episode ceiling.
`render_maps` is reserved for the replay phase and currently has no effect.

Private press archival and bot artifact upload are not implemented yet. The
launcher currently acknowledges game_over without fetching private press.
