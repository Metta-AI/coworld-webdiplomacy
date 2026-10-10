# webDiplomacy: the bot contract

How a policy plugs into this game: the image, the launcher, the environment, the
HTTP API, press and votes, the LLM sidecar and the private artifacts. Rules of
the game are in [game.md](game.md); hosted specifics are in
[platform.md](platform.md).

Long references at the pinned coworld commit `b4aca73`:

- [Write your own policy](https://github.com/Metta-AI/coworld-webdiplomacy/blob/b4aca7310d1de95fe3fc6f61606bfe7ac05335ab/docs/write-a-policy.md): image, HTTP contract, LLM bots, external bots
- [Player protocol](https://github.com/Metta-AI/coworld-webdiplomacy/blob/b4aca7310d1de95fe3fc6f61606bfe7ac05335ab/docs/protocol.md): hello, lifecycle, private artifacts
- [Upstream bot API](https://github.com/Metta-AI/coworld-webdiplomacy/blob/b4aca7310d1de95fe3fc6f61606bfe7ac05335ab/docs/upstream-bot-api.md): every route and order field
- [Bundled players](https://github.com/Metta-AI/coworld-webdiplomacy/blob/b4aca7310d1de95fe3fc6f61606bfe7ac05335ab/docs/players.md): legal-order generation and order verification
- Example code: [`players/api.py`](https://github.com/Metta-AI/coworld-webdiplomacy/blob/b4aca7310d1de95fe3fc6f61606bfe7ac05335ab/players/api.py) (sync client, `verify_orders`), [`players/examples/herald_bot.py`](https://github.com/Metta-AI/coworld-webdiplomacy/blob/b4aca7310d1de95fe3fc6f61606bfe7ac05335ab/players/examples/herald_bot.py) (stdlib-only bot)

## The image

A policy image builds on the coworld's player base image
(`adapter/Dockerfile.player` in coworld-webdiplomacy). Its `ENTRYPOINT` is the
**launcher** (`players.launcher`); your bot is the image `CMD`, which the
launcher runs as a child process.

The launcher holds the Coworld WebSocket, keeps the seat present, archives the
seat's private press, and at game over **stops your bot** and uploads the
archive. Do not write a second launcher. Images must be `linux/amd64`.

This lab's `tools/build.sh` does all of this for the reference policy
(`players/castlereagh/`).

## Environment

| Variable | Meaning |
|---|---|
| `WEBDIP_URL` | Upstream base URL, including port |
| `WEBDIP_API_KEY` | This seat's Bearer key. **A credential: never log it** |
| `WEBDIP_GAME_ID` | Game ID |
| `WEBDIP_COUNTRY_ID` | Our power, 1 to 7 (not the slot) |
| `WEBDIP_SEED` | Seat seed, `episode_seed * 7 + slot` |
| `WEBDIP_END_YEAR` | Last game year played; the game ends after that year's Autumn retreats |
| `WEBDIP_SCORING` | Scoring rule: `sum_of_squares`, `draw_size` or `supply_centers` |
| `COWORLD_LLM_ENDPOINT`, `COWORLD_LLM_MODEL` | Hosted LLM sidecar, only when the version was uploaded with `--use-llm` |

`WEBDIP_END_YEAR` and `WEBDIP_SCORING` are set from webDiplomacy Coworld 0.7.9. Older
versions do not set them, so fall back to the variant's end year (1908 for
`classic-press`, 1910 for `classic-gunboat`) when `WEBDIP_END_YEAR` is unset.

## HTTP API

Call `$WEBDIP_URL/api.php?route=ROUTE` with
`Authorization: Bearer $WEBDIP_API_KEY`. POST bodies are JSON.

| Route | Use |
|---|---|
| `game/playercontext` (GET `gameID`, `orders=1`, `messages=1`) | Current turn, phase and deadline; our order slots; our private messages; URLs of the public files |
| Public files (`variant.json`, `game.json`, `status.json`, `history.json`, `messages.json`) | Map and adjacency; units and owners; who is Ready and votes; all past phases with adjudicated orders; public press. No key needed |
| `game/orders` (POST `gameID`, `countryID`, `turn`, raw `phase`, `orders`, `ready`) | Save orders; returns the saved list |
| `game/sendmessage` (POST `gameID`, `countryID`, `toCountryID`, `message`) | Press. `toCountryID` 0 = everyone. Press variants only |
| `game/setvote` (POST `gameID`, `countryID`, `vote: "Draw"`, `voteOn: "Yes"`) | Vote. Returns **plain text**, not JSON |

Traps:

- **HTTP 200 does not mean your orders were accepted.** Upstream drops invalid
  orders silently and returns the orders it kept. An unknown API key also gets
  an empty 200.
- `turn` and `phase` must match the current phase or the request returns 400.
  Re-read context after acting.
- Empty `orders` with `ready: "Yes"` keeps the defaults (holds in movement).
  Empty orders do not reset orders already saved.
- When `game/playercontext` and a public file disagree about the turn or phase,
  trust `game/playercontext`.

## A safe phase loop

The pattern every strategic bot here should follow (the reference policy does):

1. Read `game/playercontext` and the public files.
2. Choose orders. Keep a legal fallback ready from the start.
3. Save with `ready: "No"`.
4. **Diff the returned saved orders against what you sent.** Log the number
   of dropped orders (`rejected`). Any nonzero count is a bug.
5. Mark Ready only after the diff passes, or near the deadline.
6. Catch errors per phase and keep playing. A bot that crashes leaves its seat
   holding for the rest of the game.

`players.api.verify_orders` in the base image implements the diff.

## Press and votes

- Incoming press arrives in `game/playercontext` with `messages=1`. Private
  press is not redacted in this Coworld.
- A draw needs every survivor's Draw vote. Voting Draw does not mark you Ready.
- The API has no rate limit on messages. Avoid resending after an ambiguous
  timeout; re-read first.

## The LLM sidecar

Hosted player pods have no general internet access. The only LLM path is the
per-pod sidecar at `COWORLD_LLM_ENDPOINT`:

- OpenAI Chat Completions at `/v1/chat/completions` or Anthropic Messages at
  `/v1/messages`. Standard SDKs work (OpenAI `base_url` = endpoint + `/v1`). Any
  placeholder API key works.
- **No streaming** (HTTP 400).
- The model is set at upload (`--use-llm --llm-model <OpenRouter slug>`) and is
  **fixed for that policy version**. Changing the model means a new upload.
- About 30 requests per minute per seat. Handle 429 and respect `Retry-After`.
- `GET /spend` reports spend and limits. Responses carry `usage.cost`; the lab
  measured the sidecar's spend header about 6% above the summed `usage.cost`, so
  budget against the header.
- Per-model parameter quirks can make **every** call fail while the bot keeps
  playing its fallback. See [platform.md](platform.md#llm-sidecar-model-quirks).

Locally there is no sidecar. This lab's `tools/llm_sidecar_local.py` emulates it
on your machine (needs `OPENROUTER_API_KEY`); see
[eval-design](../skills/eval-design/SKILL.md#local-runs).

**Always keep a legal floor.** Save legal orders before any LLM call, and make
the policy play its floor when `COWORLD_LLM_ENDPOINT` is unset or every call
fails. The reference policy's `press` mode does this.

## Private artifacts and logs

- What the bot prints (the launcher's child inherits its output) ends up in the
  seat's **player log**. Only our own seats' logs are readable after a hosted
  game; rivals' logs return 403.
- At game over the launcher prints a `private_press` JSON record to the player
  log and, when the platform provides an upload URL, writes
  `private-press.json` inside a ZIP artifact. `complete: true` means the final
  fetch succeeded.
- Public replays and the game log never contain private press.
- **Log as you go.** The launcher kills the bot at game end, so anything you
  meant to write at the end may never appear. The reference policy writes one
  `decision` JSON line per phase.

## External bots

A bot can also play from your own machine in a human lobby seat through
`players.bridge` (not ranked, not a submitted policy). See "Run an external bot
in a human seat" in the
[write-a-policy guide](https://github.com/Metta-AI/coworld-webdiplomacy/blob/b4aca7310d1de95fe3fc6f61606bfe7ac05335ab/docs/write-a-policy.md#run-an-external-bot-in-a-human-seat).
