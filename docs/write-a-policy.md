# Write your own policy

Your bot plays the real webDiplomacy HTTP API. The bundled launcher handles the
Coworld WebSocket handshake, presence, shutdown and private press archive. Run
your bot as its subprocess; do not implement a second launcher.

## Build and run the example

Install Git, Docker with Linux amd64 support, Python 3.12+ and uv. From a fresh
clone of this public repository:

```sh
git submodule update --init --recursive
uv sync --group dev
docker compose build player
docker build --platform linux/amd64 -t herald:local players/examples
uv run coworld build --version 0.7.8
DOCKER_DEFAULT_PLATFORM=linux/amd64 uv run coworld run-episode \
  dist/coworld_manifest.json herald:local \
  --run /opt/.venv/bin/python --run=-m --run players.launcher \
  --run /opt/.venv/bin/python --run /opt/herald_bot.py \
  --variant classic-press-short --output-dir tmp/herald --timeout-seconds 120
```

This runs seven copies of [Herald](../players/examples/herald_bot.py), a complete
stdlib-only bot. It holds, sends one public greeting per movement phase where
press is enabled, marks Ready, and votes Draw from Spring 1903. It makes at most
one message attempt per phase to avoid duplicate press after an ambiguous timeout.
Check the replay and player logs under `tmp/herald` for greetings and the draw.

Each `--run` is **one argv token**. The local CLI otherwise retains the explicit
hold-bot command on six certification seats, even when you override their image.
The override above includes the launcher because the runner replaces the image's
entrypoint when given an explicit command. Without `--variant`, this manifest
uses its short, NoPress certification fixture, ending in 1901.

To package your own bot, copy it beside this Dockerfile:

```dockerfile
FROM coworld-webdiplomacy-player:latest
COPY your_bot.py /opt/your_bot.py
CMD ["/opt/.venv/bin/python", "/opt/your_bot.py"]
```

Build the base with `docker compose build player` first. Its `ENTRYPOINT` already
runs the launcher; `CMD` supplies the child command. Add dependencies inside the
image's `/opt/.venv` only when your bot needs them. The published bundled image
is also publicly pullable (verified for 0.7.6), and `coworld download` retrieves
published images. Building from this repo avoids depending on a registry address
or a particular published version. No Softmax account is needed for these local
builds and tests.

## HTTP contract

The launcher supplies these environment variables:

| Variable | Meaning |
| --- | --- |
| `WEBDIP_URL` | Upstream base URL, including port |
| `WEBDIP_API_KEY` | This seat's Bearer credential; never log it |
| `WEBDIP_GAME_ID` | Game ID |
| `WEBDIP_COUNTRY_ID` | Country ID; country assignment differs from slot order |
| `WEBDIP_SEED` | Reproducible seat seed, `episode_seed * 7 + slot` |

Call `$WEBDIP_URL/api.php?route=ROUTE` with
`Authorization: Bearer $WEBDIP_API_KEY`. POST bodies are JSON with
`Content-Type: application/json`. Herald's `call()` function is a small runnable
example; [players/api.py](../players/api.py) also provides a synchronous client.
The [upstream bot API reference](upstream-bot-api.md) covers every route, order
field and server behavior in detail, with citations into the pinned upstream code.

| Route | Request and response |
| --- | --- |
| `game/playercontext` | GET with `gameID`, `orders=1`, `messages=1`; JSON includes current game/member, private orders/messages and references to public files |
| `game/orders` | POST `gameID`, `countryID`, current `turn`, raw `phase`, `orders`, `ready: "Yes"` or `"No"`; returns saved orders |
| `game/sendmessage` | POST `gameID`, `countryID`, `toCountryID` (`0` for public), `message`; returns JSON; requires press-enabled play |
| `game/setvote` | POST `gameID`, `countryID`, `vote: "Draw"`, `voteOn: "Yes"` (or `"No"` to withdraw); returns plain text, not JSON |

Submit `orders: []` with `ready: "Yes"` to keep default holds in Movement. Empty
orders preserve already saved orders; they do not reset them. In Retreats and
Builds, default orders disband, remove or skip builds as upstream requires.
The raw movement phase is `"Diplomacy"`; use that value in API requests even
though viewers label it **Movement**. Turns start at zero: year is
`1901 + turn // 2`.

**An HTTP 200 does not prove every order was accepted.** Upstream can silently
drop or rewrite invalid inputs. For a strategic bot, save with `ready: "No"`,
diff the returned saved orders against the requested meaningful fields and
multiplicity, then mark Ready only after the comparison passes. See
`players.api.verify_orders` and [player validation](players.md). Refetch context
if the phase changed during the request; otherwise surface the rejection.
Herald sends no new orders, so it only accepts the engine's defaults.

Phases can end before their deadline when everyone is Ready. Re-read context
after acting; a stale turn/phase request may return 400. Draws require unanimous
votes from the remaining players. Voting Draw does not replace Ready. A finished
game or a cancellation (404 after upstream deletes the game) ends play; the
launcher collects artifacts and acknowledges completion. See the
[full lifecycle protocol](protocol.md) for reconnects and private artifacts.

## Upload, evaluate, then submit

Local tests above create no hosted resources. The commands below upload a policy,
run hosted episodes, and finally enter a league. Sign in and inspect your identity:

```sh
uv run softmax login
uv run softmax status
uv run coworld upload-policy herald:local --name your-unique-herald
uv run coworld leagues
```

Use a distinctive policy name. Upload prints a reference such as
`your-unique-herald:v1`, not the policy-version UUID. Use the exact returned version
in requests. If you need the UUID, the supported client lookup reads your saved
login without printing its token:

```sh
uv run python - <<'PY'
from coworld.api_client import CoworldApiClient

with CoworldApiClient.from_login(server_url="https://softmax.com/api") as client:
    version = client.lookup_policy_version(name="your-unique-herald", version=1)
    if version is None:
        raise SystemExit("No matching policy version owned by the active identity")
    print(version.id)
PY
```

This uses `GET /stats/policy-versions` with `mine=true`, `name_exact` and `version`.
The returned `entries[].id` is the policy-version ID, not the policy ID.

Two leagues run webDiplomacy: **webDiplomacy**, the main full-press league
(`classic-press`), and **webDiplomacy Gunboat** (`classic-gunboat`, no press).
Herald negotiates, so it belongs in the main league. Find it in `coworld leagues`,
inspect it with `coworld leagues LEAGUE_ID`, then replace `LEAGUE_ID` and policy
refs in this `experience-request.json`. The example uses the shorter
`classic-press-short` variant for a quick smoke test. Seven explicit refs allow a reproducible self-play
smoke test; replace six with opponent policy refs for a meaningful evaluation.

```json
{
  "private": true,
  "target": {"league_id": "LEAGUE_ID", "variant_id": "classic-press-short"},
  "roster": [
    {"player": {"policy_ref": "your-unique-herald:v1"}, "slot": 0},
    {"player": {"policy_ref": "your-unique-herald:v1"}, "slot": 1},
    {"player": {"policy_ref": "your-unique-herald:v1"}, "slot": 2},
    {"player": {"policy_ref": "your-unique-herald:v1"}, "slot": 3},
    {"player": {"policy_ref": "your-unique-herald:v1"}, "slot": 4},
    {"player": {"policy_ref": "your-unique-herald:v1"}, "slot": 5},
    {"player": {"policy_ref": "your-unique-herald:v1"}, "slot": 6}
  ],
  "num_episodes": 1,
  "episode_player_llm_spend_limit_usd": 0,
  "notes": "Herald self-play: public press, Ready and unanimous Draw"
}
```

```sh
uv run coworld xp-request create experience-request.json
uv run coworld xp-request watch REQUEST_ID --checkpoint tmp/herald-watch.json
uv run coworld xp-request episodes REQUEST_ID --view results --jsonl
uv run coworld submit your-unique-herald:v1 --league LEAGUE_ID --no-open-browser
```

Replace `REQUEST_ID` with the returned experience-request ID. Uploading alone does
not enter a league. See the public [upload and evaluation guide](https://softmax.com/docs/coworld/build-a-player/upload-and-evaluate)
for hosted logs, results and evaluation workflows.

## LLM bots

Herald needs no model. For your model-backed policy, enable the hosted sidecar
at upload (choose a canonical OpenRouter model allowed by the league):

```sh
uv run coworld upload-policy your-bot:local --name your-unique-bot \
  --use-llm --llm-model anthropic/claude-haiku-4.5
```

Read `COWORLD_LLM_ENDPOINT` at runtime and send every hosted model call there.
Read the model from `COWORLD_LLM_MODEL`. The sidecar accepts OpenAI Chat Completions
at `/v1/chat/completions` and Anthropic Messages at `/v1/messages`. Standard SDKs
work: OpenAI's `base_url` is `endpoint + "/v1"`; Anthropic's is the endpoint
unchanged. A placeholder API key suffices; never bake provider keys into an image.
Streaming is not supported.

The default chat ceiling is 30 requests/minute per slot. Handle HTTP 429 and
provider failures with bounded timeouts/retries, respect `Retry-After-Ms` or
`Retry-After`, and fall back to legal orders before the phase deadline.
`GET /spend` reports current limits and spend. For an LLM experience request,
replace the zero cap above with your budget: `episode_player_llm_spend_limit_usd`
is the combined player budget **per episode**, divided evenly across seven seats;
a lower league cap still applies. Zero disables player LLM access.

Local episodes have no hosted sidecar. `run-episode --use-llm` forwards your
`COWORLD_LLM_ENDPOINT` or `OPENROUTER_API_KEY`; any endpoint must be reachable
from inside Docker. Use `--secret-env COWORLD_LLM_MODEL=...` for the local model.
Follow the [hosted model guide](https://softmax.com/docs/coworld/build-a-player/hosted-llm)
and [runtime contract](https://github.com/Metta-AI/coworld/blob/main/src/coworld/docs/HOSTED_LLM.md)
for SDK setup, local credentials and current limits.

## Run an external bot in a human seat

Use this when the bot should run on your laptop or server while the game runs on
Softmax infrastructure. Your bot occupies a **human lobby seat**, not a submitted
policy or ranked player. The bridge needs the updated Coworld image advertising
`http-bot-api-v1`; if it reports that capability missing, the game owner must
publish the updated Coworld and start a new lobby. Existing games cannot acquire
new routes from a local checkout update.

1. Sign in as a Softmax **user**, then create a league lobby or claim an open
   human seat before the host starts it. Lobby creation assigns seat 0 to the
   host. The claim API is `POST /v2/lobbies/{lobby_id}/seats/{position}/claim`.
2. After startup, call `POST /v2/lobbies/{lobby_id}/launch` as that same user.
   Wait while it returns `kind: pending`. Save the `kind: player` JSON response,
   or its `viewer_url` alone, to a private file such as `tmp/seat.json`. A spectator
   URL cannot control a seat. A direct player WebSocket URL also works.
3. From this repository, install the bridge dependencies and run it:

   ```sh
   uv sync --no-dev
   chmod 600 tmp/seat.json
   uv run --no-dev python -m players.bridge \
     --seat-url-file tmp/seat.json --env-file tmp/bot.env
   ```

   The bridge chooses a free loopback port; use `--port 8765` if your bot needs
   a fixed port. The env file must not already exist. It is created with mode
   0600 and contains a newly generated **local** API key, plus the game's IDs
   and seat seed. The hosted token is never forwarded to the bot.
4. In a second shell, run the bot itself, without `players.launcher`:

   ```sh
   source tmp/bot.env
   python /path/to/your_bot.py
   ```

   An ordinary webDip bot can use `WEBDIP_URL` as its base URL and
   `WEBDIP_API_KEY` as its Bearer key. If it expects the full API endpoint,
   configure `$WEBDIP_URL/api.php`. The existing `players.api.WebDiplomacy`
   client works unchanged. Keep the bridge running for the game; stop it with
   Ctrl-C when finished, then remove the private seat and env files. A new
   bridge process gets a new local key, so restart/reconfigure the bot too.

Only one controller should connect for a seat: a browser and bridge connected
simultaneously transfers control to the newest connection. The displaced browser
stops reconnecting; a displaced bridge returns HTTP 409 until restarted. Seat URLs confer control of that
seat; never put them in command-line arguments, shared logs, or version control.

Supported API routes are `game/playercontext`, `game/orders`, `game/sendmessage`,
`game/messagesseen`, `game/setvote`, `game/togglevote` and `game/markbackfromleft`,
using their upstream methods and JSON bodies. Public game/status/history/messages
JSON and Classic variant JSON can be fetched without the local key, matching the
normal webDip file API. Other routes, sandbox games, HTTP SSE and access to other
seats/games are unavailable. Use polling; private context and API writes require
the local Bearer key. The bridge accepts at most 128 KiB request bodies and 16 MiB
WebSocket responses. It listens only on 127.0.0.1, rejects browser Origin headers,
and is intended for bots on the same machine, not public HTTP hosting.

Upstream statuses and response bodies are preserved. Continue checking saved
orders: an upstream 200 can still silently drop invalid orders. Bridge-specific
errors are 401 for a missing/wrong local key, 409 when another controller takes
the seat, 502 for a malformed tunnel response or invalid reconnect
handshake or changed seat identity, 503 for a disconnected tunnel,
504 for a response deadline, and 410 after game-over. Treat 410 as normal
completion. On 503/504, **a write may already have taken effect**. Refetch context
before deciding whether to send another order/message/vote; the bridge never
replays a request, including the mutating GET `game/togglevote`.

The receiver handles lifecycle messages while the bot is idle. It retries a
lost connection up to eight times with 0.5–5 second backoff, checking the seat's
identity after reconnect. After retries are exhausted, check the lobby status: the game may have ended
while disconnected, in which case no game-over message can arrive. If the game
is still running, restart the bridge with a fresh env-file path. It acknowledges game-over and continues returning 410
until stopped. It does not create a hosted player artifact or private-press
archive; the external bot owns any local history it needs to keep.
