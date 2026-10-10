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

*(stamped by `tools/add_game.sh` on install; update on `--update`)*

| | |
|---|---|
| **Upstream mixin** | {{MIXIN_REPO_URL}} |
| **Commit** | {{COMMIT}} |
| **Installed** | {{DATE}} |

This lab is a vendored copy and is expected to drift from upstream. That's
fine — see SEED.md's divergence stance.

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
| `ab` | `skills/ab/` | Score vs same-batch field par **per power** as the headline metric; paired seating as the default design; \|z\| < 2 = no result; measured sizing priors (SD 0.12–0.18, about 150/arm for 0.04); the taint list (cancelled, rejected orders, exceptions, missing artifacts, failing LLM seats, mixed opponent sets); `wd.py metrics`, `paired.py`, `compare.py` | Any comparison between versions or policies (core: `ab-compare`) |
| `survey` | `skills/survey/` | The per-power overview table with outcome, reason and health lines; which episodes are worth opening (crashes, failing LLM seats, opponent solos, early elimination, big swings, best and worst per power); `wd.py metrics` and `seats` | Reading any batch of episodes (core: `survey`) |
| `replay-inspection` | `skills/replay-inspection/` | The replay frame format (gzip JSON of public upstream files), our own artifacts (`decision` lines, `llm_call` events, private press), the `(turn, phase)` clock, what to look at; the episode loader. A local game viewer comes later | Extracting truth from episodes (core: `replay-inspection`) |
| `eval-design` | `skills/eval-design/` | Opponents from the current field, fixed within a campaign, explicit `policy_ref`s; paired and separate-arm rosters with a request example; no self-play verdicts; health check on `classic-press-short`; floors; country pinning (coworld 0.7.9+); cost and duration; local-run tools | Designing any hosted eval (core: `run-eval`) |
| `diagnosis` | `skills/diagnosis/` | Known failure modes (silent order drops, invisible degradation, wrong map knowledge, misplaced trust, ignoring the game horizon, over-tuning) and a six-step procedure for new problems (a sketch, to build out) | Turning signals into hypotheses (core: `diagnose`) |

### Meta-recon support

| Provides | Path | Notes |
|---|---|---|
| Strategy doc | `docs/strategy.md` | A general Diplomacy primer (not yet verified against this field) and measured field facts from 2026-10: power par, the strongest seats, league rosters |
| Game reference | `docs/game.md` | Rules, scoring, `results.json`, variants, leagues, timing |
| Platform notes | `docs/platform.md` | XP requests, costs, artifacts, LLM sidecar quirks, credentials |
| Field decode | `skills/replay-inspection/`, `skills/survey/` | Replays carry every power's adjudicated orders and public press; `wd.py seats` gives every seat's center trajectory. Rivals' logs are not readable |

### Additional skills

*(everything else this mixin ships — game-specific capabilities beyond the
required set. List them all: an unlisted skill is an undiscoverable one.)*

| Skill | Path | What it does | Use when |
|---|---|---|---|
| *(none)* | | | |

## What else this mixin provides

| Element | Path | Notes |
|---|---|---|
| Lab manual | `AGENTS.md` | How to use this lab, the knowledge map, the loop table and the gotchas |
| Game docs | `docs/` | `game.md` (rules, scoring, results, variants, leagues), `protocol.md` (the bot contract), `platform.md` (hosted specifics), `strategy.md` (primer and measured field facts) |
| Reference policy | `players/castlereagh/` | Python package `castlereagh`. Kissinger search as the core, plus an optional LLM press layer. Mode set by `CASTLEREAGH_POLICY`: `search` (default; press off), `press` (search plus press; plays its search floor without `COWORLD_LLM_ENDPOINT`). Logs one `decision` line per phase. The starting point `seed-a-policy` improves on |
| Build tooling | `tools/build.sh` | `tools/build.sh [--ref <game-ref>] [--tag <image-tag>] [--policy search\|press]`. Builds the coworld player base image from a pinned coworld-webdiplomacy commit on GitHub, then the reference policy, for linux/amd64; prints the tag (default `webdip-castlereagh-<policy>:latest`). Needs Docker |
| Instruments | `tools/` | Standard-library Python: `webdip_episodes.py` (loader), `wd.py` (`metrics`, `seats`, `costs`, `local`, `arena`, `slim`), `paired.py`, `compare.py`, `llm_sidecar_local.py`. See `AGENTS.md` |
