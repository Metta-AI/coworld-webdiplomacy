# webDiplomacy on the hosted platform

What is specific to running webDiplomacy on Softmax: experience requests (XP
requests, the hosted eval batches), cost, timing, artifacts, the LLM sidecar's
per-model quirks, and credentials. The optimizer's own `docs/platform.md` (at
the optimizer root) covers the generic platform: auth, API routes, upload and
submit. Read that first.

Facts here were read from the platform in **2026-10** and carry their date. The
platform changes; re-check anything a decision depends on.

## Setup

- Install the CLIs as uv tools, not into a project:
  `uv tool install coworld` and `uv tool install softmax-cli`. Then
  `softmax login` and `softmax status`. `python3 games/webdiplomacy/tools/check_clis.py`
  (a SessionStart hook under the Claude Code harness) reports a missing or outdated tool with the fix;
  `uv tool install --force <package>` updates one, including a stale install
  from a local checkout. Neither CLI has a `--version` option: `uv tool list` prints the
  installed versions.
- **Check for game and template changes at session start:**
  `python3 games/webdiplomacy/tools/check_coworld.py -v` (also a SessionStart hook under
  Claude Code). It lists changelog entries this lab has not applied and reports the hosted
  Coworld version; the lab manual's "Keep the lab current" says what to do with them.
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

  Docker needs `DOCKER_CONFIG=~/.docker` when `HOME` is overridden (without it a
  build fails with "content digest … not found").

  `source games/webdiplomacy/tools/session_env.sh <player id>` does all of this
  in one step and prints the identity commands will act as. It also wraps `git`
  and `gh` to run with the real `HOME`, so `git push` keeps working (without
  that it fails with "could not read Username": the credential helper and, on
  macOS, the keychain are found through `HOME`).

  **In a coding-agent harness** shell state does not persist between commands.
  Pin the directory and source the script at the start of every command line:

  ```sh
  export WEBDIP_SESSION_HOME=<one scratch directory for this session>
  source games/webdiplomacy/tools/session_env.sh    # give the player id the first time only
  ```

  Without a pinned `WEBDIP_SESSION_HOME` every command gets a fresh copy of the
  shared credentials and acts as whichever player the shared file names.

- **Know who you are acting as, and say it.** One login holds a user account and one or
  more players. `coworld player list` shows the players and which is active; "No active
  player; commands act as your main user" means every command acts as the user, and
  requests a player created will be missing. `softmax status` prints `subject_type`
  (`user` or `player`). Uploads, requests and league entries belong to the **player** that
  made them, so act as the player for the whole loop
  (`source games/webdiplomacy/tools/session_env.sh <player id>`), and name the acting
  identity to the user before the first upload or launch.
- **What a player can and cannot do** (checked as a player that is not a Softmax team
  member, 2026-10-11):

  | Works as a player | Needs the league owner or a Softmax team account |
  |---|---|
  | `coworld upload-policy`, `coworld submit`, creating, listing and fetching its own XP requests | Starting a league round (`POST /v2/leagues/{id}/trigger-round`): there is no CLI command, and nothing a player can do makes a round run sooner |
  | `coworld leagues <league_id> --json`: the league's settings and its filler roster ids | Other entrants' memberships (`/v2/league-policy-memberships` returns only your own rows to a player) |
  | `coworld rounds`, `coworld episodes -r`, `coworld results`, `coworld memberships`, `coworld submissions --mine` | `/v2/leagues/{id}/filler-policies` (403 for a player, 2026-10-10) |
  | League episodes' results and replays, and the logs of its own seats | Any other policy's seat log (403) |

  A team member acts as the **user**, with elevated privileges asked for explicitly
  (`--elevated` on the CLI, the header `X-Use-Elevated-Privileges: true` on the API).
  `session_env.sh` has no user mode: for a user call, copy the credentials into a second
  scratch `HOME` and run `coworld player unset` there. Keep it apart from the player's
  `HOME`, so the two identities never share a file.
- **Shell.** The default shell on macOS is zsh: quote `--include='*.py'`, do not write
  `echo ===`, and pass several ids as separate words (zsh does not split `$IDS`).

## Uploading

- `coworld upload-policy <image> --name <policy>`. Images must be
  `linux/amd64`.
- LLM policies add `--use-llm --llm-model <OpenRouter slug>`. **The model is
  fixed per uploaded version.** Treat model × prompt ("soul") as one unit under
  test; a model change is a new version with its own version-log row.
- The reference policy's mode is chosen by `CASTLEREAGH_POLICY` in the image
  (`tools/build.sh --policy`, default `press`). `tools/ship.py` uploads a press
  build with `--use-llm` and a default model.
- `tools/build.sh --tag` is required (`ship.py` derives the tag from `--slug`).
  Use one image tag per experiment: rebuilding a tag while games are running
  silently switches later games to the new code.

## XP requests

A request names a league and variant, a roster of seven seats, and an episode
count. Body shape (`tools/make_request.py` writes these from a named opponent
set; see the eval-design binding):

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

- `slot: -1` lets the platform choose the slot, and powers are then shuffled
  by seed. An A/B uses fixed slots with pinned, rotated powers instead
  (`tools/make_request.py --balanced`).
- **Identity.** A request belongs to the identity that created it, and a
  private request is visible only to that identity. The CLI acts as the active
  player (`coworld player use`); the optimizer's scripts do too since
  2026-10-10 and print `[auth] acting as …`. A batch that "vanished" from
  `coworld xp-request list --mine` was probably created as the other identity.
- In an episode row, `participant_scores` is by seat position. `scores` is
  keyed by policy version and merges a policy seated twice; do not use it.
- `policy_ref` takes a version reference. Use policy-version UUIDs for
  field seats; `name:vN` works for your own uploads.
- **Never use `random` seats here.** `random` samples the league's champion
  pool. When you are most of that pool, the game becomes self-play.
- `episode_player_llm_spend_limit_usd` is the LLM budget **per episode**,
  split evenly over the seven seats. Zero disables LLM access for all seats.
  `make_request.py`'s default for a press set is 14.
- `game_config_overrides` sets episode config fields on top of the variant's
  own. The platform checks them against the game's config schema (the
  `config_schema` in the manifest), so any field in it can be set and an
  unknown key or a value out of range is refused.
  Pinning powers with `countries` works from webDiplomacy Coworld 0.7.9
  (verified hosted 2026-10-10); see the eval-design binding and
  `tools/make_request.py --balanced`. To make a game shorter, see
  [Shorter games](#shorter-games).
- The allowed body keys are in the optimizer's `docs/platform.md`; `private`
  and `episode_player_llm_spend_limit_usd` are accepted. **Dry-run every body**
  (`eval_request.py create body.json --dry-run`) before creating it. The dry run
  checks the body's shape and prints no cost; the estimate comes with the real
  create (below). `tools/run_ab.py ... --dry-run` gives the nearest thing to a price
  ahead of time: the platform's estimate for the last request of the same kind this
  lab created (same variant, seats, LLM budget and games per request), from the saved
  create responses, or the range between the nearest sizes when that size was never
  quoted.
- **Keep the ids; the listing will not give them back.** `coworld xp-request list
  --mine --json` returns rows under `entries` with a `next_cursor` (follow it: 1,000 rows
  came back with more behind them on 2026-10-11), and a row has no roster, no notes and
  `title: null`. `coworld xp-request episodes <xreq> --json` returns sealed rows
  (`"evidence_state": "sealed"`, `participants: null`), even to the owner. What does
  identify a request is `coworld xp-request get <xreq> --json`: `requested.notes` is
  the note `make_request.py` wrote (what it compares, the field set, the experiment
  id). Its `cost_preview` came back `null` for requests read on 2026-10-12: the
  estimate is in the create response and nowhere else, so keep
  `.runtime/requests/responses/`. So write every batch id into the
  experiment record when it is created (`run_ab.py` does), and use the seed's
  `fetch_artifacts.py` to read a batch, not the CLI listing.
- **The platform may run an episode again.** The league settings carry
  `fulfillment.retry_times: 2`, and a restarted game finishes about a game's length
  after the others (seen 2026-10-11). The watcher shows only "still waiting". A
  straggler is not a reason to stop the fetch or to read the batch without it.

## Shorter games

Three episode settings decide how long a game takes. Set them in
`game_config_overrides`: `tools/make_request.py --config KEY=VALUE` writes them,
and `tools/run_ab.py --variant VARIANT --config KEY=VALUE` passes them to a
screen stage.

| Setting | What it is | Allowed | `classic-press` | `classic-press-short` | `classic-gunboat` |
|---|---|---|---|---|---|
| `end_year` | Last game year played | 1901 to 2000 | 1908 | 1904 | 1910 |
| `phase_minutes` | Length of a movement phase, whole minutes | 1 to 59 | 3 (4 before Coworld 0.7.10) | 3 | 1 |
| `retreat_build_minutes` | Length of a retreat or build phase, whole minutes | 1 to 59 | 1 | 1 | 1 |

```json
"game_config_overrides": {"end_year": 1903, "phase_minutes": 2}
```

- **How long:** a press game lasts about **2 × `phase_minutes` for each year
  played**, plus its retreat and build phases, because LLM seats rarely all mark
  Ready and a movement phase then runs its full length. That gave 64 minutes for
  `classic-press` while its phases were 4 minutes and gives 24 for `classic-press-short`,
  against the measured 61 and 23 to 27 below. With 3-minute phases (Coworld 0.7.10)
  `classic-press` comes to 48 minutes; that figure is computed. One hosted `classic-press` game with `end_year` 1902 and
  `phase_minutes` 2 (2026-10-12, seven LLM seats) played for 8.1 minutes, as the
  rule gives, ended with `reason: end_year`, and its row recorded a `cost_usd` of
  $0.09. By the same rule `end_year` 1903 with `phase_minutes` 2 is about 12
  minutes; that figure is computed. Take your own games' durations from
  `tools/batches.py`. A phase ends early only when every seat is Ready, which is
  why a gunboat game takes two minutes.
- **Cut `end_year` first.** The years that are played stay the same game: same
  time to negotiate, same openings. Only the late game is gone, and with it the
  final score (the game is scored at the cap, and bots are told the cap in
  `WEBDIP_END_YEAR`).
- **Cutting `phase_minutes` changes how every seat plays**, the field's seats
  too. An LLM seat needs time for its model calls: the reference policy allows
  55 seconds for one call and saves its final orders 12 seconds before the
  deadline (`PRESS_CALL_TIMEOUT_S`, `PRESS_FINAL_MARGIN_S`), so at one minute it
  has under 50 seconds a phase, less than one full call. Use a
  short phase to check that a build connects, orders and exits, or for a change
  that does not depend on negotiation. Do not read press behaviour from it.
- **A game with changed settings is not the league's game.** Read it for health
  and behaviour, never for score, and never pool it with games on the league's
  variant. `tools/run_ab.py` allows `--config` only on a screen stage for that
  reason, and `make_request.py` writes the settings into the request notes.
- **The platform's price estimate has not followed game length** (the table
  below: a short health game was quoted the same credits as a full one). A
  shorter game saves time and LLM spend; do not count on it saving credits.
- That one game is the only hosted check of these settings (the request was
  written by hand; `countries` and `render_maps` are the overrides this lab's
  tools have run hosted). Run one shortened game and read its `reason` and
  length before you plan a batch around it.

## Cost and duration

As the platform reported it from 2026-10-10 to the early hours of 2026-10-12. Re-measure on your own batches with
`python3 games/webdiplomacy/tools/batches.py <artifact dirs> [--responses DIR]`.

`classic-press` had 4-minute movement phases until Coworld 0.7.10 (2026-10-12) and has 3-minute phases since. The full-game figures here were measured at 4 minutes; at 3 minutes a full game is about 48 minutes of play by the rule in [platform.md, "Shorter games"](#shorter-games). Measure your own with `tools/batches.py`. Expect the LLM part of `cost_usd` to fall with the shorter phases.

| Game | Platform's estimate at create (`cost_preview.estimated_cost_credits`) | Episode row's `cost_usd` | Minutes of play |
|---|---|---|---|
| Full `classic-press`, 4-minute phases | 1.37 to 3.34 credits | $0.51 to $0.61 | median 61, longest 75 |
| `classic-press-short` (health game) | 1.4 to 3.34 credits | $0.11 to $0.28 | 23 to 27 |
| `classic-gunboat` | 0.50 credits | $0.026 | median 2.4 |

- The estimate moves between launches of the same design, and why is not known. Over one
  night the quotes per press game were 2.232 (about 21:30 Pacific, requests of one to three
  games), 2.821 (about 23:50, requests of ten games) and 3.24 to 3.34 (about 02:00, requests
  of one and three games), short and full games alike. So the estimate does not follow the
  game's length, and it may depend on the hour, the games per request, or both.
- No route prices a request without creating it, and `coworld xp-request get` returned no
  `cost_preview` for requests made that night; the create response is the only place the
  figure appears, and `eval_request.py create` saves it. Before a launch, quote the figure
  the create step prints, not this table. Under a credit limit, launch in sets and read
  each set's estimate before the next.
- **Not established:** the credits actually charged, and how `cost_usd` relates to
  credits. Nobody has read a balance. Quote the platform's estimate as an estimate.
- LLM spend depends on the model and the policy's prompts: `wd.py costs` prints it per
  seat and per phase from the `llm_call` events.
- A game usually starts within 3 minutes of the request. What you wait for is the
  slowest game: about 60 press games launched together were all in after 70 minutes,
  and a batch with a restarted or late game took 100 to 130.
- Requests share one queue: a large gunboat batch created just after many press games
  waited about an hour before its games ran.
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
- Replays are large: about 10 MB of **uncompressed** JSON per gunboat game even
  with `game_config_overrides.render_maps: false`, because every frame repeats
  the cumulative history and the map (measured 2026-10-10). `wd.py slim`
  strips map PNGs; `tools/gzip_replays.py` compresses in place about 20x
  and the loader reads the result.
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
| `qwen/qwen3.8-flash` | About 40 provider 429s per game | None found |
| `minimax/minimax-m3` | About one call per 60 s | None found |

The sidecar also strips several request fields (`provider`, `models`,
`fallbacks`, `metadata`, and others); `reasoning` passes through. After any
model or prompt change, run one `classic-press-short` health check and confirm
every LLM call in our seat logs succeeded (`llm_call` events).

## Leagues and the field

- Two leagues; IDs and variants are in [game.md](game.md#leagues).
- A league round is three games per seven entrants, about every 72 minutes in the
  press league (interval 72 minutes; a round waits for the one before it) and daily in gunboat ([game.md](game.md#leagues)), so league episodes are slow
  evidence; hosted XP requests are the instrument.
- Empty league seats are filled from a **filler roster** that the league owner
  curates. The route `/v2/leagues/{id}/filler-policies` returns 403 for player
  credentials (verified 2026-10-10), but **`coworld leagues <league_id> --json` lists
  the roster's version ids in `filler_policy_version_ids`, and a player can read it**
  (verified 2026-10-11). That is the whole roster. `tools/field.py` shows only what
  recent rounds seated, with names, so it can miss part of the roster. Use the roster for the ids and
  `field.py` for names and seatings; an id `field.py` has not seen can be named with
  `GET /stats/policy-versions/<id>` (worked for a player on 2026-10-11, for ids that
  the same account owned; not tried on a stranger's policy).
- **Entering a league:** `coworld submit <policy>:vN --league <league_id> --player
  <player id> --no-open-browser`; check it with `coworld memberships` (the entry
  reads `competing / active` once it is in). The optimizer's `submit` skill sets the preconditions and the go-ahead; read
  [game.md](game.md#leagues) on what an entry does and does not get you.
- This lab ships no picture of the current field. Build it into `META.md`: the
  roster and `tools/field.py` for who is in it, then the
  [opponent-profile](../skills/opponent-profile/SKILL.md) skill for how each plays.
