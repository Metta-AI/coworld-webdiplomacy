# Bundled players and compatibility checks

The first bundled player, `random`, runs `players.random_bot` through
`players.launcher`. `hold` explicitly overrides the launcher command. The
certification roster uses `random` in slot 0 and `hold` in the other six seats,
exercising both bundled player types. Another synchronous bot can be run with
`python -m players.launcher <command> <arguments>`.

To run seven random players through the 1910 cap locally:

```sh
DOCKER_DEFAULT_PLATFORM=linux/amd64 uv run coworld run-episode \
  dist/coworld_manifest.json coworld-webdiplomacy-player:latest \
  --run /opt/.venv/bin/python --run=-m --run players.launcher \
  --variant classic-gunboat --output-dir tmp/random-episode --timeout-seconds 120
```

The CLI otherwise retains the explicit hold command for the six hold seats in
the certification roster even when their image is overridden. Each `--run` supplies one argv token.

## Legal inputs

`players.legal_orders` reads the pinned upstream `variant.json` and current
`game.json`. It follows the native PHP order validators for adjacency, split
coasts, supports, simple convoy paths through fleets at sea, retreat exclusions,
owned empty home-center builds, removals, and skipped builds. Untouched neutral
provinces may be absent from the public territory-status list. They are empty,
unowned and have no standoff; missing entries do not forbid retreats.

The launcher derives each seat seed as `episode_seed * 7 + slot`. Selection is
deterministic for that seat seed, country, turn and phase. Omitted episode seeds
are newly randomized; replay and results preserve the chosen value.
Independent random orders are not coordinated strategy: a legal convoy or support
can fail because another unit chose a different order. This player does not
adjudicate, choose tactical winners, or guarantee survival.

The saved-order response must match the requested meaningful order fields and
multiplicity. One Wait represents all remaining build slots. A changed phase
causes a refetch; a current-phase silent drop or rewrite raises an error.
A cancelled game returns 404 and ends the bot while its launcher finishes
presence and press collection. An empty HTTP 200 is not valid JSON and does not
count as successful authentication.

The existing [Python Diplomacy engine](https://diplomacy.readthedocs.io/en/stable/api/diplomacy.engine.game.html)
and its [webDiplomacy integration](https://diplomacy.readthedocs.io/en/stable/api/diplomacy.integration.webdiplomacy_net.api.html) were
considered. They would add a second engine and map/API conversion to this small
player. The upstream React generator is coupled to its board state and Classic
TypeScript types. Using this pinned map with the native API as the input validator
keeps the requested Python bot small without a new production dependency.

## Validation

Build the images first, then run:

```sh
uv run python -m unittest players.test_players -v
uv run python -m tools.check_random coworld-webdiplomacy-game:latest
uv run python -m tools.check_legal_corners coworld-webdiplomacy-game:latest
uv run python -m tools.check_press coworld-webdiplomacy-game:latest
uv run python -m tools.check_compatibility coworld-webdiplomacy-game:latest
```

The seeded check uses seeds 0, 17 and 42 through spring 1911, covering the 1910
season and its adjustments. The corner check enumerates generated candidates on
scripted support/dislodgement/retreat, convoy, and split-coast build boards.
Every candidate set is saved without Ready and compared to the upstream response;
only then does the scenario Ready the seats and let the upstream loop process.
The checks assert zero rejected input differences and report order counts.

The press check runs seven real launchers through draw and cancellation. Only the
sender and recipient may contain the private sentinel; game logs and public replay
must not. Unit/integration tests cover reconnect, more than 40 seconds of presence,
early child failure, invalid API responses, upload failure, stubborn child cleanup
and the archive worker's hard deadline. Archive semantics are in the
[player protocol](protocol.md#private-player-artifacts).

## Stock upstream comparison

The compatibility check derives its stack from the pinned submodule's
`docker compose --profile core` configuration. It uses the original services,
entrypoint, sample application config and gamemaster. It creates ordinary User
accounts and matching game settings, then runs the same smoke, tactics and convoy
API scenarios against both stacks. It compares complete context and public-file
snapshots, saved orders, messages, vote responses, phase outcomes and distinct SSE
event payloads. Only generated identities, timestamps, file versions and derived
authentication signatures are normalized. Public state and order semantics are
not normalized away. SSE delivery may coalesce file notifications, so distinct
changed-file names are compared rather than transport timing or duplicate count.

Infrastructure adaptations isolate the test: dynamic localhost ports, an owned
network, linux/amd64, a smaller database buffer pool, read-only config mounts, and
a named source volume populated with `git archive`. Dependencies and generated
configuration/cache files are installed **inside containers**. Fixture helpers
live outside `/application`; the host submodule is never writable. Stock nginx
is restarted after the services exist because it can start before the SSE DNS
name is registered. Game processing still comes exclusively from stock SSE.
The stack and its volume are removed at the end, including on failure.

If Docker's default address pools are exhausted, choose an unused subnet and set
`WEBDIP_STOCK_SUBNET` for this command. It does not prune unrelated networks.
Evidence and service diagnostics stay under ignored `tmp/`; these contain local
credentials and private test messages and must not be published. This check is
against the pinned source revision, not a claim about the live webDiplomacy site.
