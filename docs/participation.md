# Conductor participation

This variant keeps one upstream webDiplomacy server resident for the trial. Seven external controllers use Platform's
seat protocol; no player container is needed. A human UI, remote bot or a trusted hosted controller can use the same seat.
The ordinary Coworld variant remains available, but its player-container bridge is not required by this host.

The Conductor adapter is in `adapter/conductor.py`; its private socket protocol lives in `adapter/participation`.
The native runner provides the attempt deadline and output directory. The host starts fresh MariaDB, nginx, PHP and the
upstream gamemaster, then exposes observations, orders and press on an attempt-private Unix socket. Game phase deadlines
come from upstream. Controller heartbeats cannot extend them.

## Build and qualify

Build the ordinary game image from `adapter/Dockerfile` using the repository's Coworld build workflow.
Compose it with a qualified Conductor runner using `adapter/Dockerfile.conductor`, setting build arguments
`GAME_IMAGE` and `RUNNER_IMAGE`. For the shared local workflow, tag it `universe-webdiplomacy-runner:local`.
Run `uv run python -m tools.check_participation universe-webdiplomacy-runner:local`.
The check owns its container and removes it on completion.

Start Conductor's local play stack and Platform as described in their development guides. In Universe, start a
Diplomacy trial, select a seat, and take control. Saving orders and sending press produce durable command receipts.
A seat token authorizes a remote client to that seat; it does not expose an upstream webDiplomacy API key.

## Failure boundaries

The private SQLite journal records uncertainty before an upstream mutation. A duplicate command returns its existing
receipt. A dropped response must not send the same message again. A phase change rejects stale commands. Upstream
order validation remains authoritative, including legal coasts, convoy rules, retreats and builds.

Cancellation and expiry destroy the entire resident container. Killing only the Python parent does not reliably stop
PHP-FPM's independent process group. A lost container fails the accepted attempt; automatic database checkpoint/restore
is not implemented. Never replace a missing accepted game with a fresh board under its existing trial identity.

Private observation history is bounded to recent public and authorized private messages. Truncation is explicit.
Public replay files contain adjudicated board states and public messages only. Never print a private response while
investigating a failure.


## Remote bot example

Run `uv run python -m tools.participate SEAT_ENDPOINT --journal /private/path/seat.json`, with the token from
Universe's Connect a bot view in `UNIVERSE_SEAT_TOKEN`. The default policy marks existing orders ready, preserving the
upstream default holds. `--once` submits one window. No native container is required on the bot's machine.

For a real policy use `--policy module:function`. The synchronous function receives the private observation and returns
`{"orders": [...], "ready": true}` using the upstream API's order fields. Adapt an existing decision function here;
do not forward an old bot's upstream API token. The heartbeat runs while the callback thinks, but cannot extend the
world's deadline. Clients that need press can submit the documented press command separately through the same protocol.

The journal is private and bound to one seat endpoint. It records a command before transmission and retains its ID
across lost responses. Restart with the same journal. An uncertain receipt or controller replacement stops the example
for inspection rather than taking the seat back or issuing a fresh action. Do not delete a journal to hide uncertainty.
