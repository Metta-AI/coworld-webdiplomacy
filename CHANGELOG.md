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
