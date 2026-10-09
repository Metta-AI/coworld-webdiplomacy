# MIXIN — webDiplomacy

The manifest for this lab: what game it binds, where it came from, and —
the load-bearing part — **every skill this mixin provides**, so core skills
resolve bindings here instead of guessing, gaps are machine-checkable, and
extra capabilities are discoverable.

**Placeholder conventions** (delete this note when filling in):
`webDiplomacy` = the human-readable game name. `webdiplomacy` = the
lowercase directory-safe name; it should match the lab's directory
(`games/<slug>/`, i.e. what `add_game.sh --name` was given) — core skills
address the lab by directory, so a mismatched slug in skill frontmatter is
cosmetic, but keep them aligned anyway. Rows marked *(optional)* may be
deleted when not shipped; `.gitkeep` files exist only to keep empty
directories in git — delete them once a directory has real content (keep
`instruments/.gitkeep`: that directory should exist even when empty).

## Identity

| | |
|---|---|
| **Game** | webDiplomacy |
| **Coworld** | `webdiplomacy`, built from https://github.com/Metta-AI/coworld-webdiplomacy (`coworld_manifest_template.json`); check the hosted version with `coworld games` — free-form for humans (name + version + where its manifest lives); no core skill parses this |
| **League(s)** | "webDiplomacy" (`classic-press`, main) and "webDiplomacy Gunboat" (`classic-gunboat`) — the `league_…` id(s), from `coworld leagues --json` |
| **Game source of truth** | the upstream webDiplomacy server at the coworld-webdiplomacy submodule commit, via that repo's `docs/upstream-bot-api.md` — never answer mechanics questions from memory |

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
| `ab` | `skills/ab/` | Metrics that matter here, decompositions (roles/seats/phases), taint definition, appropriate statistical tests, N floors — ideally with working tooling | Any comparison between versions or policies (core: `ab-compare`) |
| `survey` | `skills/survey/` | What a batch overview shows for this game; which stats and splits make an episode "interesting" | Reading any batch of episodes (core: `survey`) |
| `replay-inspection` | `skills/replay-inspection/` | How to open/decode/expand this game's replays; what the policy's own artifacts contain; the shared clock for joining them | Extracting truth from episodes (core: `replay-inspection`) |
| `eval-design` | `skills/eval-design/` | Sensible rosters, episode-count floors by question type, role pinning options, pacing limits for this game | Designing any hosted eval (core: `run-eval`) |
| `diagnosis` | `skills/diagnosis/` | This game's failure vocabulary and diagnostic instruments | Turning signals into hypotheses (core: `diagnose`) |

### Meta-recon support

*(expected: at least entry-level decode knowledge or tooling so `meta-recon`
is never blind — strategy docs count; deeper instruments can grow in the lab)*

| Provides | Path | Notes |
|---|---|---|
| {{e.g. strategy/meta docs}} | `docs/strategy.md` | … |

### Additional skills

*(everything else this mixin ships — game-specific capabilities beyond the
required set. List them all: an unlisted skill is an undiscoverable one.)*

| Skill | Path | What it does | Use when |
|---|---|---|---|
| *(none)* | | | |

## What else this mixin provides

| Element | Path | Notes |
|---|---|---|
| Game docs | `docs/` | Enough that a newcomer understands the game without leaving the repo, including how it's won |
| Reference policy | `players/{{REF_POLICY}}/` | Buildable; the starting point `seed-a-policy` improves on. Give it a real `VERSION_LOG.md`; keep `players/_VERSION_LOG_template.md` in place for future policies |
| Build tooling | `tools/build.sh` | The build entry point `build-upload` invokes. Convention: `build.sh [--ref <game-ref>] [--tag <image-tag>]` — builds the policy image for linux/amd64 and prints the image tag; pinned game/SDK refs live inside with their rationale |
| Eval defaults | `eval_defaults.yaml` | *(optional — machine-readable defaults for `run-eval`; delete this row if not shipped and say so in the eval-design binding)* |
