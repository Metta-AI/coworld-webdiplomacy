# MIXIN — webDiplomacy

The manifest for this lab: what game it binds, where it came from, and —
the load-bearing part — **every skill this mixin provides**, so core skills
resolve bindings here instead of guessing, gaps are machine-checkable, and
extra capabilities are discoverable.

## Identity

| | |
|---|---|
| **Game** | webDiplomacy: classic seven-power Diplomacy on the real, unmodified webDiplomacy server. Seven seats per episode, simultaneous orders, scored by share of supply centers squared |
| **Coworld** | `webdiplomacy`, built from https://github.com/Metta-AI/coworld-webdiplomacy (`coworld_manifest_template.json`). This lab was written against commit `b4aca73`; check the hosted version with `coworld list` |
| **League(s)** | "webDiplomacy" `league_1bccc63d-cd0a-47d7-92d7-e762797b5f1c` (`classic-press`, the main league) and "webDiplomacy Gunboat" `league_428e91e5-ee25-4f9c-be5e-a4fc4f993f17` (`classic-gunboat`, no press). Re-resolve with `coworld leagues --json` |
| **Game source of truth** | The upstream webDiplomacy server at the coworld-webdiplomacy submodule commit, via that repo's `docs/upstream-bot-api.md` (cites upstream file and line) — never answer mechanics questions from memory |

## Provenance

*(stamped by coworld-webdiplomacy's `optimizer/install.sh` when the optimizer is generated)*

| | |
|---|---|
| **Upstream mixin** | {{MIXIN_REPO_URL}} |
| **Commit** | {{COMMIT}} |
| **Installed** | {{DATE}} |

This lab is a vendored copy and is expected to drift from upstream. That's
fine — see SEED.md's divergence stance. Upstream changes that a lab must act on
are listed in `CHANGELOG.md`; `tools/check_coworld.py` says when there are new
ones, and the lab manual's "Keep the lab current" says how to apply them. Update
the commit above when you do.

## Skill manifest

Core skills resolve their game bindings through this table. A required binding
that is missing or stubbed is a **gap**: the core skill announces it, proceeds
on its generic method, and warns the human that results are weaker.

### Required bindings

**What counts as "filled":** a binding is filled when its knowledge sections
are real (metrics, decompositions, taint, floors…) even if tooling doesn't
exist yet — in that case its Tooling section says so explicitly ("no tooling
yet — build as a lab instrument") and that is *not* a gap. A **gap** is a
binding that is missing entirely or still template boilerplate; core skills
announce gaps and proceed on their generic method with the human warned.

| Binding | Path | What it provides | Use when |
|---|---|---|---|
| `ab` | `skills/ab/` | Score vs same-batch field par **per power** as the headline metric; paired seating as the default design; \|z\| < 2 = no result; sizes from `tools/sizing.py` (its SDs are starting values, to be replaced with your own from `paired.py`); the taint list (cancelled, failed or timed-out episodes, rejected orders, crashes and dead seats, a pod the platform deleted mid-game, missing artifacts, failing LLM seats, mixed opponent sets); the mechanism check beside the score; the two allowed ways to extend a run; `wd.py metrics`, `paired.py`, `compare.py`, `holds.py`, `batches.py` | Any comparison between versions or policies (core: `ab-compare`) |
| `survey` | `skills/survey/` | The per-power overview table with outcome, reason and health lines; saying which games a headline is from; which episodes are worth opening (crashes, failing LLM seats, opponent solos, early elimination, big swings, best and worst per power); `wd.py metrics` and `seats`, `seat_rows.py`, `batches.py` | Reading any batch of episodes (core: `survey`) |
| `replay-inspection` | `skills/replay-inspection/` | The replay frame format (gzip JSON of public upstream files), our own artifacts (`decision` lines, `llm_call` events, private press), the `(turn, phase)` clock, what to look at; the episode loader. One game in the terminal: `opponent_profile.py --game` (the orders) and `seat_log.py` (what our seat was told and committed); in the browser: the IDE's replay viewer | Extracting truth from episodes (core: `replay-inspection`) |
| `eval-design` | `skills/eval-design/` | Opponents from the current field, fixed within a campaign, explicit `policy_ref`s; paired and separate-arm rosters with a request example; no self-play verdicts; health check on `classic-press-short`; floors; sizing before launch; country pinning (webDiplomacy Coworld 0.7.9+); cost and duration as the platform reported them (2026-10-11), re-measured with `tools/batches.py`; local-run tools | Designing any hosted eval (core: `run-eval`) |
| `diagnosis` | `skills/diagnosis/` | What to read before proposing (`closed_levers.md`, `open_levers.md`, every experiment record); kinds of failure and how to detect each; and a seven-step procedure for new problems that ends in a `proposed` experiment record | Turning signals into hypotheses (core: `diagnose`) |

### Meta-recon support

| Provides | Path | Notes |
|---|---|---|
| Strategy doc | `docs/strategy.md` | The strategy of the starter policy, and the lab's own field knowledge (empty until you measure) |
| Game reference | `docs/game.md` | Rules, scoring, `results.json`, variants, leagues, timing |
| Platform notes | `docs/platform.md` | XP requests, costs, artifacts, LLM sidecar quirks, credentials |
| Field roster | `coworld leagues <id> --json`, `tools/field.py`, `field_sets.json`, `META.md` | The league's filler roster ids (readable by a player); who is seated in a league's recent rounds, with names, version ids and each round's seating; named opponent sets; the dated field picture (ships empty) |
| Opponent profiles | `skills/opponent-profile/`, `reports/opponents/` | Per-opponent deep dives that META.md rows link to |
| Field decode | `skills/replay-inspection/`, `skills/survey/` | Replays carry every power's adjudicated orders and public press; `wd.py seats` gives every seat's center trajectory. Rivals' logs are not readable |

### Additional skills

*(everything else this mixin ships — game-specific capabilities beyond the
required set. List them all: an unlisted skill is an undiscoverable one.)*

| Skill | Path | What it does | Use when |
|---|---|---|---|
| `press-audit` | `skills/press-audit/` | Checks what powers said in a press game against what they ordered: an agent (a sub-agent per game) lists each message's promises, threats, requests, statements and proposals in a fixed vocabulary; `tools/press_audit.py` checks them against the adjudicated orders, works out whether we relied on each, and writes `audit.json` and a local `audit.html` | A press game went badly; deciding whom the policy should trust; checking whether our own bot keeps its word |
| `opponent-profile` | `skills/opponent-profile/` | A dated deep dive on one opponent from the public orders: `tools/opponent_profile.py` counts (openings, first targets, captures, order mix and trajectory beside the field, tainted and stalled seats, behaviour toward our policy); the agent opens games, writes claims as pattern / evidence / exploit / test into `reports/opponents/<slug>.md`, and puts one line in META.md | "How does X play"; one opponent keeps beating us; a new version appears; before a matchup write-up or a counter |
| `matchup-writeup` | `skills/matchup-writeup/` | Why our policy wins or loses against each opponent: verdicts from `tools/matchups.py` (with a many-rows allowance), the power pairs and games that carry a gap from `opponent_profile.py --versus`, games read with our decision lines and press audits, "what happened" kept apart from "why" with seen / likely / guess, into `reports/matchups/<ours>-vs-<opponent or field>.md` | "Why do we lose to X"; after a field eval or league round; before choosing what to work on |
| `ide` | `skills/ide/` | Opening and using the local web IDE (`ide/` at the optimizer root): the user chats with the running session from the browser, watches replays, pins notes to phases, and reads the dashboard and reports; the agent answers with `ide/ide say` and posts cards with `ide/ide show` | The user says "open the IDE"; a message starting `[webDiplomacy IDE]` arrives; there is a replay, result or idea worth showing; before a diagnosis, to read the user's notes |

## What else this mixin provides

| Element | Path | Notes |
|---|---|---|
| Lab manual | `AGENTS.md` | How to use this lab, the knowledge map, the index of every tool and skill ("Tool and skill index"), the loop table and the gotchas |
| Game docs | `docs/` | `game.md` (rules, scoring, results, variants, leagues), `protocol.md` (the bot contract), `platform.md` (hosted specifics), `strategy.md` (the starter policy's strategy; the lab's own field knowledge, empty until you measure) |
| Reference policy | `players/castlereagh/` | Python package `castlereagh`: the starter policy. A look-ahead search over sampled opponent plans as the core, plus a basic, neutral LLM press harness that steers the search (no persona, no negotiation doctrine; a user adds a role in `press/souls/<name>/SOUL.md` and skills in `press/skills/`). Mode set by `CASTLEREAGH_POLICY`: `press` (default: search plus press; plays its search floor in a no-press game or without `COWORLD_LLM_ENDPOINT`), `search` (press off). Logs one `decision` line per phase. The starting point `seed-a-policy` improves on |
| Build tooling | `tools/build.sh` | `tools/build.sh --tag <image-tag> [--ref <game-ref>] [--policy press\|search] [--overrides "KEY=VAL,…"]`. Builds the coworld player base image from a pinned coworld-webdiplomacy commit on GitHub, then the reference policy, for linux/amd64; prints the tag. `--tag` is required (one tag per experiment); `--overrides` bakes config overrides into the image. Needs Docker |
| Analysis tools | `tools/` | Standard-library Python: `webdip_episodes.py` (loader), `wd.py` (`metrics`, `seats`, `costs`, `local`, `arena`, `slim`), `paired.py`, `compare.py`, `matchups.py` (score vs par by power, opponent, version and source; the IDE dashboard's numbers), `opponent_profile.py` (what one policy does, from the public orders), `holds.py` (hold share beside the field, stopped seats, and what our press layer committed), `board_counts.py` (an order, a centre or a unit counted over every game, the field beside it), `seat_rows.py` (one row per seat, worst first, with the other policy's side), `seat_log.py` (one of our seats' log for a turn), `hold_reasons.py` (why our press build's units hold), `centre_losses.py` (every supply centre we lost, who took it and what we thought of them beforehand), `wake_bench.py` (recorded decisions replayed under another prompt or setting), `press_behaviour.py` (what our press agent does, per version), `batches.py` (cost and wall-clock time per batch), `ab_stats.py` (the statistics library behind `compare.py`), `llm_sidecar_local.py`, `check_clis.py` (CLI version check), with unit tests in `tools/tests/`. See `AGENTS.md`, "Tool and skill index" |
| Campaign tools | `tools/` | `run_ab.py` (one paired A/B from an experiment record; `--alone` for the candidate-alone check), `make_request.py` + `field_sets.json` (named opponent sets; balanced power rotation with both seat orders), `ship.py` (build, upload, VERSION_LOG row), `my_versions.py` (every version we have uploaded, with league entries marked), `field.py` (league field from its rounds), `sizing.py`, `seat_bias.py`, `flag_episodes.py`, `year_deltas.py`, `mine_variance.py`, `gzip_replays.py`, `fetch_league.py` (a league's rounds into the artifacts layout), `press_audit.py` (press against orders; see the press-audit skill) and `press_report.py` (the module that draws its HTML page). See `AGENTS.md`, "Tool and skill index" |
| Staying current | `CHANGELOG.md`, `tools/check_coworld.py` | The lab's copy of coworld-webdiplomacy's changelog (stamped at install, replaced by `check_coworld.py --ack`), and the check that lists entries the lab has not applied and the hosted Coworld version. Lab manual, "Keep the lab current" |
| Session setup | `tools/session_env.sh` | `source` it: private credentials directory, Docker config and active player; `git` and `gh` keep the real home; prints the acting identity. Pin `WEBDIP_SESSION_HOME` in an agent harness |
| Registers | `open_levers.md`, `closed_levers.md`, `best_practices.md` | Levers that were measured and ended inconclusive (with the numbers, what the run could have seen and what a next test needs), levers that were refuted, and graduated practice. Read the first two, and the records in `experiments/`, before proposing. All three ship with the format only: the entries are your own lab's |
| Opponent sets | `field_sets.json` | Named opponent sets for `tools/make_request.py`. Ships with the format only (placeholder seats): fill it from `tools/field.py` and date each set |
| Reports | `reports/` | Write-ups from the opponent-profile and matchup-writeup skills (`opponents/`, `matchups/`); tracked; listed and rendered by the IDE at `/reports`. Created on first use |
| Replay notes | `annotations/` | The user's and the agent's notes on replays, one JSON file per episode, written by the IDE (`ide/ide annotations`); tracked. Created on first use |
| Your instruments | `instruments/` | Empty. Your own analysis code goes here; everything the mixin ships is in `tools/` |
