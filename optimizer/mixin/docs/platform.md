# webDiplomacy on the hosted platform

What is specific to running webDiplomacy on Softmax: experience requests (XP
requests, the hosted eval batches), cost, timing, artifacts, the LLM sidecar's
per-model quirks, and credentials. The optimizer's own `docs/platform.md` (at
the optimizer root) covers the generic platform: auth, API routes, upload and
submit. Read that first.

Facts here were measured by a prior webDiplomacy lab in **2026-10** unless
marked otherwise. The platform changes; re-check anything a decision depends on.

## Setup

- Install the CLIs as uv tools, not into a project:
  `uv tool install coworld` and `uv tool install softmax-cli`. Then
  `softmax login` and `softmax status`.
- **Use a private `HOME` per session.** The CLI keeps credentials and the active
  player in `~/.softmax/credentials.yaml`, shared by every session on the
  machine. Another session running `coworld player use` silently switches your
  identity; private requests then return 404 and episodes list as
  "unavailable". Copy the file into a scratch home:

  ```sh
  H=<scratch>/home; mkdir -p $H/.softmax && cp ~/.softmax/credentials.yaml $H/.softmax/
  HOME=$H coworld player use <your player id>
  HOME=$H coworld xp-request create body.json
  ```

  Docker needs `DOCKER_CONFIG=~/.docker` when `HOME` is overridden.

## Uploading

- `coworld upload-policy <image> --name <policy>`. Images must be
  `linux/amd64`.
- LLM policies add `--use-llm --llm-model <OpenRouter slug>`. **The model is
  fixed per uploaded version.** Treat model × prompt ("soul") as one unit under
  test; a model change is a new version with its own version-log row.
- The reference policy's mode is chosen by `CASTLEREAGH_POLICY` in the image
  (`tools/build.sh --policy`). One image tag per experiment: rebuilding a tag
  while games are running silently switches later games to the new code.

## XP requests

A request names a league and variant, a roster of seven seats, and an episode
count. Body shape used by the lab (built by its `make_request.py`):

```json
{
  "private": true,
  "target": {"league_id": "league_1bccc63d-cd0a-47d7-92d7-e762797b5f1c", "variant_id": "classic-press"},
  "num_episodes": 16,
  "episode_player_llm_spend_limit_usd": 14,
  "roster": [
    {"player": {"policy_ref": "<candidate version>"}, "slot": -1},
    {"player": {"policy_ref": "<field version 1>"}, "slot": -1}
  ],
  "notes": "one line on what this batch answers"
}
```

(The roster has seven entries; see the eval-design binding for full rosters.)

- `slot: -1` lets the platform choose the slot. Powers are shuffled by seed
  anyway.
- `policy_ref` takes a version reference. The lab used policy-version UUIDs for
  field seats; `name:vN` works for your own uploads.
- **Never use `random` seats here.** `random` samples the league's champion
  pool, which can be only you, which makes the game self-play.
- `episode_player_llm_spend_limit_usd` is the LLM budget **per episode**,
  split evenly over the seven seats. Zero disables LLM access for all seats.
  The lab used 14.
- `game_config_overrides` sets episode config fields (for example `seed`).
  Pinning powers with `countries` is merged (coworld `b4aca73`) but usable
  hosted only after the coworld is republished; see the eval-design binding.
- The optimizer's `docs/platform.md` lists the allowed body keys as verified on
  2026-07-15; that list lacks `private` and `episode_player_llm_spend_limit_usd`,
  which the lab used successfully in 2026-10. **Dry-run every body**
  (`eval_request.py create body.json --dry-run`) before creating it.

## Cost and duration

- About **15 XP credits per hosted full `classic-press` game** with five LLM
  seats (LLM plus compute).
- LLM spend on `z-ai/glm-5.3-flash` (reasoning low): about **$0.006 per seat
  per movement phase**, about 13 to 14 calls per seat-phase, median latency
  4.4 s (p90 15.6 s). That is about $0.10 per seat per full game.
- A full hosted `classic-press` game takes **60 to 100 minutes** (61 by one
  measurement, 80 to 100 by another; re-measure). Sixteen episodes in one
  request ran in parallel, so a 16-game arm took about an hour of wall clock.
- The episode cap is 5,910 s (about 98 minutes) of game time; the manifest's
  episode timeout is 100 minutes.

## Artifacts

- Fetch with the optimizer's `fetch_artifacts.py XREQ --watch` while games run.
  **Do not block on a whole request**; read episodes as they land.
- Downloads are sometimes missing on the first fetch (rate limits). Re-running
  the fetcher resumes. Report coverage; never impute missing episodes.
- Our seat logs sometimes arrive as a Python bytes literal (`b'...'`). The
  lab's loader `tools/webdip_episodes.py` decodes them.
- **A parent request shows `failed` as soon as one child episode fails.** Wait
  for every child to finish before reading the request's status as final.
- Replays carry embedded map PNGs and are large. `wd.py slim` strips them from
  local replays when the disk fills.
- Rivals' policy logs and artifacts return 403. Decode rivals from replays and
  public press.

## LLM sidecar model quirks

The sidecar forces OpenRouter's `provider.require_parameters=true`, so any
parameter the model's providers do not support makes the call fail (often HTTP
404 "No endpoints found"). The seat then plays its fallback **with no visible
error**. Verified on hosted health checks, 2026-10-08/09:

| Model | Quirk | Fix that worked |
|---|---|---|
| `openai/gpt-6-luna`, `anthropic/claude-haiku-5.5` | Reject `temperature` | Omit `temperature` |
| `google/gemini-3.5-flash-lite` | Rejects reasoning off (HTTP 400) | Reasoning effort `low` |
| `deepseek/deepseek-v4.1-flash`, `qwen/qwen3.8-flash`, `minimax/minimax-m3` | Reason past a 2,000-token `max_tokens` and return nothing | Raise the cap (6,000) or turn reasoning off (deepseek, qwen) |
| `qwen/qwen3.8-flash` | About 40 provider 429s per game | Not used |
| `minimax/minimax-m3` | About one call per 60 s | Not used |

The sidecar also strips several request fields (`provider`, `models`,
`fallbacks`, `metadata`, and others); `reasoning` passes through. After any
model or prompt change, run one `classic-press-short` health check and confirm
every LLM call in our seat logs succeeded (`llm_call` events).

## Leagues and the field

- Two leagues; IDs and variants are in [game.md](game.md#leagues).
- League rounds were one per day in 2026-10 (lab observation). League episodes
  are slow evidence; hosted XP requests are the instrument.
- Empty league seats are filled from a **filler roster** that the league owner
  curates (`/v2/leagues/{id}/filler-policies`). Whether a non-owner can read it
  is not verified; recent league episodes' participants show who is playing.
- The field as of 2026-10-09 is in [strategy.md](strategy.md#part-2-the-measured-field-2026-10);
  the live picture belongs in `META.md`.
