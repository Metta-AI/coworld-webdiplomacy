# Changelog

For people and coding agents who play this game or run an optimizer made from
`optimizer/` (the template [Metta-AI/webdip-optimizer](https://github.com/Metta-AI/webdip-optimizer)).
It lists the changes they must act on: a new Coworld version, a change to what a
bot is told or may do, and a change to the optimizer template's tools, skills or
docs. Internal changes (tests, CI, refactors) are not listed.

Newest first. Each entry's heading has the same form, because the optimizer's
`tools/check_coworld.py` reads it:

    ## YYYY-MM-DD · Coworld <version live on that date> · <title>

An entry is never edited after it is published, apart from fixing a mistake: an
optimizer finds new entries by their headings. Each entry says what changed, what
to do in an optimizer, and the commit to copy changed files from. Paths under
"In your optimizer" are relative to the lab, `games/webdiplomacy/`; the same files
are under `optimizer/mixin/` here (`ide/` is `optimizer/ide/`).

Entries start on 2026-10-12. An optimizer made before then has no
`tools/check_coworld.py`: do the steps of "Changelog and update check" below once.

## 2026-10-15 · Coworld 0.7.15 · The launcher bundles a bot's own files into its player artifact

**What changed.** The player image's launcher (`players/press.py`) now adds every regular
file a bot writes under `COWORLD_PLAYER_ARTIFACT_DIR` (default `/tmp/coworld-player-artifact`)
to the seat's player artifact ZIP at game over, beside `private-press.json`, up to 150 MiB
(the platform's artifact cap is 200 MiB). The upload timeout inside the worker is 10 s (it was
3 s). A bot that writes nothing there uploads exactly what it uploaded before. This is how a
policy records more than the seat log can hold: the hosted seat log is the last 10,000 lines
of stdout, while the artifact takes files of any shape. See "Private player artifacts" in
`docs/protocol.md`.

**In your optimizer.**

1. Nothing, unless your policy wants to write files into its artifact. If it does: write them
   under `COWORLD_PLAYER_ARTIFACT_DIR` as the game runs (flush each write; the bot is killed
   before the bundle is made), then move `PINNED_GAME_REF` in `tools/build.sh` to the commit
   that adds this entry, rebuild, and run one health game. `fetch_artifacts.py` already
   downloads the ZIP to `artifacts/<policy version>.<slot>.zip`.

## 2026-10-15 · Coworld 0.7.15 · Press league rates the powers alongside the players

**What changed.** League settings, not the game. From round 58 (2026-10-15), the press
league's OpenSkill ranking also learns how strong each power is
(`ranking.role_advantage_sigma: 2.0`): each side of a game is rated as the player plus a
hidden teammate for the power it played, read from `results.json` `roles`. A good finish
with a weak power now moves a rating more than the same finish with a strong one. The power
ratings are not on the leaderboard, MMR is still the player's own mu − 3 × sigma, and scores
are unchanged. Ratings earned before round 58 keep the luck of the powers drawn then. The
gunboat league is unchanged.

**In your optimizer.**

1. Nothing is required. Score per game against the same-power par is still the number to
   move; this change makes the leaderboard judge a policy the same way.
2. Merge the "The press league also rates the powers" paragraph under "Leagues" in
   `docs/game.md` from the commit that adds this entry.

## 2026-10-15 · Coworld 0.7.15 · results.json names each seat's power; league seating and seat cap

**What changed.** Coworld 0.7.15. `results.json` gains `roles`: seven power names in slot
order (`England`, `France`, `Italy`, `Germany`, `Austria`, `Turkey`, `Russia`), the same
assignment as `countries`, and the manifest's `results_schema` requires it. Softmax leagues
read it to rate how strong each power is alongside the players (OpenSkill role advantages,
`ranking.role_advantage_sigma`). That setting is not on in either league yet; another
entry will say when it is. `scores` do not change. Play and what a bot is told during the
game do not change.

League settings changed too, not the game. The press league seats players with
`balanced_rotation` again (each entrant plays exactly three games a round, at random among
the least-played; from 2026-10-13 to 2026-10-15 it used rating-neighbour seating, which
replayed two fixed tables of seven). Its round interval is 72 minutes, and since 2026-10-14
each seat's model spend is capped at $0.50 a game (it was $2).

**In your optimizer.**

1. Nothing is required for `roles`; the lab's loader ignores fields it does not use. To
   read a seat's power by name, use `roles[slot]` on results from 0.7.15 or later.
2. A press policy that spends more than $0.50 of model calls in a league game has its
   calls refused for the rest of that game. Check what a seat of your policy spends per
   game in a hosted batch (`tools/wd.py costs`).
3. Merge the `roles` row of the `results.json` table and the "Leagues" text of
   `docs/game.md`, and the league-round line of `docs/platform.md`, from the commit that
   adds this entry.

## 2026-10-14 · Coworld 0.7.14 · classic-press is back to 3-minute movement phases

**What changed.** Coworld 0.7.14 undoes 0.7.13. `classic-press` and `classic-press-short`
have `phase_minutes` 3 again, as they did from 0.7.10 to 0.7.12. Retreat and build phases
and the end years are unchanged. A full press game is again about 45 minutes of play.
0.7.13 was canonical for about two hours, and no press-league round ran on it. Nothing else
in the game or the player image changed.

**In your optimizer.**

1. If you changed your policy's timing for 2-minute phases after reading the 0.7.13 entry,
   change it back. A phase-start agent run again has up to `PRESS_WAKE_SECONDS` (120 s).
2. If you ran evals on 0.7.13, keep those games apart from others, as the 0.7.13 entry says.
3. Copy `tools/wake_bench.py` from the commit that adds this entry: its replayed phase is
   180 seconds again. Merge `docs/game.md`, `docs/platform.md`, the lab manual,
   `skills/eval-design/SKILL.md` and `tools/run_ab.py` from the same commit; they describe
   3-minute phases again.

## 2026-10-14 · Coworld 0.7.13 · classic-press has 2-minute movement phases

**What changed.** Coworld 0.7.13. The press league's variant, `classic-press`, and
`classic-press-short` have `phase_minutes` 2 (they were 3). Retreat and build phases stay
at 1 minute, and the end years are unchanged (1908 and 1904). At 3 minutes, 171 league games
played a median 45 minutes; at 2 minutes a full game should take about 29 (computed, not yet
measured). Nothing else in the game or the player image changed.

Why: in 36 press games on 0.7.12, the last minute carried 22% of private press, and 15% of
LLM seats' phases ended with orders that changed after 108 s. But replaying those phases
with the earlier orders moved supply centres by a net +5 across all 36 games, which is not
distinguishable from zero. The cost of the cut falls on seats whose first agent run of a
phase is slow: 4.7% of phases got their first LLM orders only after 108 s, and 3.9% got
none, so the seat played its search-only orders.

**In your optimizer.**

1. A press policy has a third less time in every movement phase. Check anything in your
   policy that assumes three minutes: wake schedules, the number of model calls a phase,
   timeouts. The reference policy caps each agent run at the time left before its lock
   (`PRESS_WAKE_SECONDS` or less), so a phase-start run gets about 107 seconds. If your
   phase-start run often takes longer, the seat will play its search-only orders more
   often. Run one health game and read `tools/press_behaviour.py` against an earlier batch.
2. Do not pool games from before and after this change in one read.
3. Durations, the LLM part of `cost_usd` and the starting SD in `tools/sizing.py` were
   measured with longer phases. Re-measure them on your first batch
   (`tools/batches.py`, `paired.py`'s `sd`).
4. Merge the variant rows and the notes that name Coworld 0.7.13 in `docs/game.md`,
   `docs/platform.md`, the lab manual, `skills/eval-design/SKILL.md` and
   `tools/run_ab.py`.
5. Copy `tools/wake_bench.py` from the commit that adds this entry: the phase length it
   gives a replayed decision is now 120 seconds.

## 2026-10-13 · Coworld 0.7.12 · Game log and results record seat health and timing

**What changed.** Coworld 0.7.12. The game records operational data for the league
dashboard; play, scoring and what a bot is told during the game do not change.

- `results.json` gains `seat_health` (per slot: `/player` connect, disconnect and
  reconnect times, and the number of upstream API requests made with the seat's key),
  `timing` (seconds spent booting, creating the game, waiting for seats and playing),
  `transitions[].deadline_unix_time` (each phase's deadline) and
  `gamemaster_calls.phases` (the longest gamemaster request in each phase).
- The public game log gains two lines. When the game has ended, `seat_activity` gives,
  per phase and seat, how many seconds after the phase began the seat first had orders
  saved and first was Ready (`null`: never). At exit, `timing` gives the full stage profile.
  Ready data is never written during play: not on the spectator stream, in replay frames
  or in anything a bot receives before `game_over`.

See [protocol](docs/protocol.md#game-log) for every field. Because `game_over` carries
`results.json`, every bot in a game can see each seat's connection events and API request
count once the game is over; the game log, including `seat_activity`, is public to anyone
who can see the episode.

**In your optimizer.** Nothing is required. A results file from 0.7.12 or later has the new
fields; the lab's loader ignores fields it does not use. To compare how fast seats submit,
read the `seat_activity` line from the episode's game log.

## 2026-10-13 · Coworld 0.7.11 · Saved replays name the player in each seat

**What changed.** Coworld 0.7.11. The episode config takes an optional `players: [{name}]`,
which the platform fills with each seat's display name. When the game ends, every saved
replay frame's `episode` carries `players: [{slot, countryID, name}]`, and the replay viewer
shows the name under each power. Names never reach bots, the upstream server or the live
spectator stream during play. Replays from earlier versions have no names and still render.

**In your optimizer.** Nothing is required. A replay fetched from 0.7.11 or later carries
`episode.players` in each frame; the lab's loader ignores fields it does not use.

## 2026-10-12 · Coworld 0.7.10 · Replays mark our policy's seats

**What changed.** The optimizer template only; the game did not change. Wherever a
replay lists the powers, every seat of our policy now stands out:

- The IDE's replay viewer tints each seat of the followed policy (any version of a bare
  name), not only the followed seat, in the orders column, thickens its line on the
  centre chart and adds "(ours)" in the seat menu. The replay list marks a seat of ours
  among a row's opponents ("Against"), as in a paired run. "Ours" is the policy the user
  picked in the browser or the agent recorded with `ide/ide follow`, else the lab's
  newest upload, else the followed seat's policy.
- `tools/opponent_profile.py --game ID --versus OURS` marks our seats "(ours)" in the
  seat list and on their order lines (before, `--versus` did nothing without
  `--decisions`).
- The press audit page (`tools/press_report.py`) tints our seat's row and its orders.

**In your optimizer.** Copy `ide/webdip_ide/routes_replays.py`,
`ide/webdip_ide/static/replay.js`, `ide/webdip_ide/static/replay.css`,
`ide/webdip_ide/templates/replays.html`, `ide/webdip_ide/templates/replays_view.html`,
`ide/tests/test_replays.py`, `tools/opponent_profile.py`, `tools/press_report.py`,
`tools/tests/test_opponent_profile.py` and `tools/tests/test_press_audit.py` from the
commit that adds this entry. Merge the `opponent_profile.py` row of the lab manual, the
"Reading one game" item of `skills/replay-inspection/SKILL.md`, the `--game` example of
`skills/opponent-profile/SKILL.md` and the replay paragraph of `ide/README.md`. Restart
the IDE (`ide/ide stop`, then `ide/ide start`).

## 2026-10-12 · Coworld 0.7.10 · classic-press has 3-minute movement phases

**What changed.** Coworld 0.7.10. The press league's variant, `classic-press`, has
`phase_minutes` 3 (it was 4). Retreat and build phases stay at 1 minute and the game still
ends after 1908. A full game is now about 48 minutes of play instead of about 61, so a
league round fits inside its 60-minute interval. Nothing else in the game or the player
image changed. `classic-press-short` now differs from it only in the end year (1904).

**In your optimizer.**

1. A press policy has a quarter less time in every movement phase. Check anything in your
   policy that assumes four minutes (wake schedules, the number of model calls a phase,
   timeouts), then run one health game and read `tools/press_behaviour.py` against an
   earlier batch.
2. Do not pool games from before and after this change in one read: the phase length
   changes how much every seat negotiates.
3. Durations, the LLM part of `cost_usd` and the starting SD in `tools/sizing.py` were
   measured with 4-minute phases. Re-measure them on your first batch
   (`tools/batches.py`, `paired.py`'s `sd`).
4. Merge the variant rows and the notes that name Coworld 0.7.10 in `docs/game.md`,
   `docs/platform.md`, the lab manual and `skills/eval-design/SKILL.md`.
5. Copy `tools/wake_bench.py`: the phase length it gives a replayed decision is now
   180 seconds.

## 2026-10-12 · Coworld 0.7.9 · Press league: rounds every hour, $100 a day

**What changed.** League settings, not the game. The webDiplomacy press league's round
interval went from 150 to 60 minutes and its daily budget from $15 to $100. A round still
waits for the one before it, and a press round takes about an hour, so rounds start 60 to
120 minutes apart. The gunboat league is unchanged (one round a day, $15).

**In your optimizer.** In `docs/game.md`, "Leagues", and `docs/platform.md`, "Leagues and
the field", replace "every 150 minutes" with the text in this repository's
`optimizer/mixin/` copies. League results now arrive about twice as often; an entry is
still not an eval.

## 2026-10-12 · Coworld 0.7.9 · Changelog and update check

**What changed.** This file exists. An optimizer keeps the copy it was last brought
up to date with (`CHANGELOG.md` in the lab), and a new tool, `tools/check_coworld.py`,
compares that copy with this file and looks up the hosted Coworld version. Under
Claude Code it runs at session start. The lab manual has a new section, "Keep the lab
current", on how to apply an entry.

**In your optimizer** (only if it was made before this entry; a newer one has all of it):

1. Copy `tools/check_coworld.py` and `tools/tests/test_check_coworld.py`.
2. Add the tool's rows to the lab manual's "Tool and skill index" and to `MIXIN.md`,
   and copy the manual's "Keep the lab current" section (`tools/tests/test_index.py`
   fails until the index names the tool).
3. Under Claude Code, add the hook beside the `check_clis.py` one in
   `.claude/settings.json` (`optimizer/install.sh` here shows the entry).
4. Read every entry below, apply what your lab lacks, then run
   `python3 games/webdiplomacy/tools/check_coworld.py --ack` and commit.

## 2026-10-12 · Coworld 0.7.9 · Shorter hosted games

**What changed.** A hosted request can shorten its own games with
`game_config_overrides`: `end_year`, `phase_minutes` and `retreat_build_minutes`.
The game did not change; the template now says so and has the tools for it.
`tools/make_request.py --config KEY=VALUE` writes any episode setting into a request,
and `tools/run_ab.py --variant VARIANT --config KEY=VALUE` passes it to a screen stage.
`docs/platform.md` has a new section, "Shorter games". A shortened game is for health
and behaviour checks, never for score.

**In your optimizer.** Copy `tools/make_request.py`, `tools/run_ab.py`,
`tools/tests/test_make_request.py` and `tools/tests/test_campaign_tools.py`. Merge
the "Shorter games" section of `docs/platform.md`, the "A shorter game than the short
variant" item of `skills/eval-design/SKILL.md`, the note under the variants table of
`docs/game.md`, and the `make_request.py` and `run_ab.py` rows of the lab manual.

## 2026-10-09 · Coworld 0.7.9 · Pinned countries, and the end year and scoring for bots

**What changed.** Coworld 0.7.9 went live. An episode config takes `countries`: a
permutation of 1 to 7 where `countries[slot]` is that slot's power, so a request can
pin and rotate powers. The launcher sets `WEBDIP_END_YEAR` and `WEBDIP_SCORING` for
every bot. Without `countries`, the seed still shuffles the powers.

**In your optimizer.** Nothing: the template was written against this version.
