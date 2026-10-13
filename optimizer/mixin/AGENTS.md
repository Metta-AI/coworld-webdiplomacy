# AGENTS — webDiplomacy lab

Loaded whenever you work in this lab, on top of the root AGENTS.md. This is the
lab's operating manual: what is here, how to use it, and the mistakes that are
easiest to make. Game facts live in [docs/game.md](docs/game.md).

## The game in brief

Classic Diplomacy for seven seats on the real webDiplomacy server. Each seat
plays one of seven powers, assigned by a seeded shuffle per episode. All powers
order at once each phase; the server adjudicates. A game ends with a solo (18
supply centers), an agreed draw, or the variant's year cap. At the cap each
survivor scores **SC² / total SC²** over survivors, so the largest power gains
most; parity is 1/7 = 0.143. Two leagues: **webDiplomacy** (`classic-press`,
public and private press, 3-minute movement phases, ends 1908) and **webDiplomacy Gunboat**
(`classic-gunboat`, no press, ends 1910). Full rules: [docs/game.md](docs/game.md).

## Scoring, structures and platform specifics

The optimizer's core skills look for these three topics in this file. They are
kept in the game docs so each fact has one home:

- **Scoring and what actually ranks:** [docs/game.md, "Scoring"](docs/game.md#scoring)
  and ["Leagues"](docs/game.md#leagues). Leagues rank by OpenSkill: each game
  orders the entrants in it by score and ratings move on that order, so finishing above
  the other entrants is what ranks. Score per game is still the number an experiment
  moves, because a higher score is how a seat places higher.
- **Structures and semantics** (slots and countries, `results.json`, replay
  frames): [docs/game.md](docs/game.md#slots-and-countries) and the
  [replay-inspection binding](skills/replay-inspection/SKILL.md).
- **Platform specifics** (requests, cost, timing, artifacts, identity):
  [docs/platform.md](docs/platform.md).

## What is in this lab

| Need | Go to |
|---|---|
| Every tool and every skill, in one index | [Tool and skill index](#tool-and-skill-index) |
| Rules, scoring, `results.json`, variants, leagues, timing | [docs/game.md](docs/game.md) |
| The bot contract: image, launcher, environment, HTTP API, LLM sidecar | [docs/protocol.md](docs/protocol.md) |
| Hosted specifics: XP requests, cost, artifacts, model quirks, credentials | [docs/platform.md](docs/platform.md) |
| The strategy of the starter policy, and the lab's own field knowledge (empty until you measure) | [docs/strategy.md](docs/strategy.md) |
| The live field picture | [META.md](META.md) (maintained by meta-recon; dated) |
| Comparing versions | [skills/ab](skills/ab/SKILL.md) |
| Reading a batch | [skills/survey](skills/survey/SKILL.md) |
| Who lied, who kept their word, where we were betrayed | [skills/press-audit](skills/press-audit/SKILL.md) |
| How one opponent plays (openings, first targets, how it treats us) | [skills/opponent-profile](skills/opponent-profile/SKILL.md); profiles in `reports/opponents/` |
| Why we win or lose against each opponent | [skills/matchup-writeup](skills/matchup-writeup/SKILL.md); write-ups in `reports/matchups/` |
| Showing the user replays, results and ideas in the browser, and reading their notes | [skills/ide](skills/ide/SKILL.md): the local web IDE in `ide/` at the optimizer root (`ide/ide start --open`) |
| Reading replays and our logs | [skills/replay-inspection](skills/replay-inspection/SKILL.md) |
| Designing a hosted eval | [skills/eval-design](skills/eval-design/SKILL.md) |
| Finding why we lose | [skills/diagnosis](skills/diagnosis/SKILL.md) |
| What already works, what is refuted (both ship empty: they fill from your own records) | [best_practices.md](best_practices.md), [closed_levers.md](closed_levers.md) |
| What was tested and gave no result (not closed; read it before proposing) | [open_levers.md](open_levers.md), and every record in `experiments/` |
| Every binding and element, as a manifest | [MIXIN.md](MIXIN.md) |
| What changed in the game or in this lab's template, and whether this lab has it | [Keep the lab current](#keep-the-lab-current); [CHANGELOG.md](CHANGELOG.md) |
| Current objective and open threads | [WORKING_CONTEXT.md](WORKING_CONTEXT.md) |

Write your own longer references in `docs/` when you need them (a verified map
reference, a press-protocol study). The coworld's own long docs are linked from
each doc at a pinned commit.

## The reference policy

`players/castlereagh/` (Python package `castlereagh`) is the starting point: a
working player that is a structure to build on, not a finished strategy. It ships
no persona, no negotiation doctrine and no results; those are yours to add and
to measure. [docs/strategy.md](docs/strategy.md) says how it decides, and its
[README](players/castlereagh/README.md) how to change each part.

- **Search core.** A heuristic (DumbBot) values the provinces and proposes
  plans; the search improves the best one, one or two units at a time, against
  16 sampled plans for the other powers, using a fast adjudicator. It looks one
  phase ahead. Retreats and builds come from the heuristic.
- **Press harness.** A basic LLM agent negotiates and steers the search through
  a policy (stances, trust, expected or required orders, forbidden provinces).
  The search's legal orders are saved first, so the LLM can never leave the seat
  without orders. Its prompt gives the objective, the mechanics and two
  reference skills, and nothing about how to negotiate. Write your own role in
  `press/souls/<name>/SOUL.md` and select it with `PRESS_SOUL`.
- **Two modes**, set by the `CASTLEREAGH_POLICY` environment variable in the
  image: `press` (default: search plus press; in a no-press game, or without
  `COWORLD_LLM_ENDPOINT`, it plays its search floor) and `search` (press off).
  Upload a press build with an LLM model; `tools/ship.py` does that by default.
- **Build:** `tools/build.sh --tag <image-tag> [--ref <game-ref>] [--policy press|search] [--overrides "KEY=VAL,…"]`
  (`--overrides` bakes `CASTLEREAGH_OVERRIDES`, any `config.py` value, into the image, so a
  one-setting experiment needs no source edit). `--tag` is required and there is no default:
  one tag per experiment. `tools/ship.py` wraps build, upload and the version-log row. Needs Docker; it builds the
  coworld player base image from a pinned coworld-webdiplomacy commit on GitHub.
  Without Docker you can still edit, test and analyze, but not build or upload.
- **Logs:** one `decision` JSON line per phase (with `rejected`), `exception`
  events, and in press mode `llm_call` events with `usage.cost`.

## Whose policy is whose

Three kinds of policy sit in these games. Tell them apart before you say "our earlier
version" to the user.

- **The user's own lineage.** The names in the first column of
  `players/castlereagh/VERSION_LOG.md` (every upload `ship.py` made), and the one the user
  named in the IDE (`ide/ide follow <name>`). A version is "earlier" only if it is an earlier
  row of that log under the same name.
- **House bots (fillers).** The league owner's bots, which take the empty seats. Their
  version ids are the league's `filler_policy_version_ids`
  (`coworld leagues <league_id> --json`), and a league game's `episode.json` marks a seat
  filled from that roster `"is_filler": true` (an experience-request game marks no seat,
  so go by the roster ids there). A house bot can be built from the same reference code
  as this lab's policy and carry a similar name: it is an opponent, not a version of ours.
- **Other entrants.** Everyone else in the standings (`coworld results <div_id>`).

A log on disk does not mean a seat is ours. An account that owns the house bots (a Softmax
team account) downloads every seat's log; a normal account gets only its own seats' logs and
403 for the rest.

## Tool and skill index

Every tool in `tools/` and every skill in `skills/`, each listed once. The tables under
[Tools](#tools) give each tool's flags and caveats; this index is for finding the right one.
`tools/tests/test_index.py` fails when a tool or a skill is missing here or a skills cell is stale.

| Tool | For | Skills that use it |
|---|---|---|
| **Build and ship** | | |
| `ship.py` | Build, upload and log one version in one step | `ide` |
| `build.sh` | Build the starter policy image (called by `ship.py`) | none (this manual only) |
| `my_versions.py` | Every version we have uploaded, with league entries marked | none (this manual only) |
| **Run experiments** | | |
| `run_ab.py` | One paired A/B end to end, from an experiment record | `ab`, `eval-design`, `ide` |
| `wake_bench.py` | Replay recorded decisions under another prompt or setting, in minutes | `diagnosis`, `eval-design` |
| `make_request.py` | Write a hosted eval request from a named opponent set | `ab`, `eval-design` |
| `sizing.py` | How many games an A/B needs | `ab`, `diagnosis`, `eval-design` |
| `paired.py` | Paired difference between two policies in the same games | `ab`, `eval-design`, `ide` |
| `compare.py` | A/B of two separate batches, by power | `ab`, `eval-design` |
| `ab_stats.py` | The statistics library behind `compare.py` | none (this manual only) |
| `batches.py` | What each batch cost and how long it took | `ab`, `eval-design`, `survey` |
| **Fetch and survey** | | |
| `fetch_league.py` | Download a league's own rounds | none (this manual only) |
| `field.py` | Who is in a league's field, with version ids | `opponent-profile` |
| `wd.py` | Batch metrics, seat rows, LLM costs, local runs | `ab`, `diagnosis`, `eval-design`, `replay-inspection`, `survey` |
| `flag_episodes.py` | Which episodes are worth opening | `diagnosis`, `survey` |
| `gzip_replays.py` | Compress fetched replays, about 20x | `replay-inspection` |
| `webdip_episodes.py` | The one episode loader every tool uses | `ab`, `diagnosis`, `replay-inspection` |
| **Performance** | | |
| `matchups.py` | Score by power, opponent, version and source (the IDE dashboard) | `matchup-writeup`, `opponent-profile`, `survey` |
| `seat_rows.py` | One row per seat, worst first | `diagnosis`, `matchup-writeup`, `opponent-profile`, `press-audit`, `replay-inspection`, `survey` |
| `year_deltas.py` | Centre change per game year | `diagnosis`, `survey` |
| `mine_variance.py` | What goes with a policy's good and bad games | `diagnosis` |
| `seat_bias.py` | Whether one roster seat outscores another | `ab` |
| **Diplomacy and behaviour** | | |
| `press_audit.py` | What was said against what was ordered: who betrayed us, when we broke our word | `ide`, `press-audit`, `replay-inspection` |
| `press_report.py` | The HTML page for a press audit | `press-audit` |
| `centre_losses.py` | Every supply centre we lost: who took it and what we thought of them beforehand | `diagnosis` |
| `press_behaviour.py` | What our press agent does, per version | `ab`, `diagnosis`, `eval-design` |
| `opponent_profile.py` | How one opponent plays, from public orders; one game phase by phase | `diagnosis`, `matchup-writeup`, `opponent-profile`, `press-audit`, `replay-inspection` |
| `board_counts.py` | A claim about orders, units or centres counted over every game | `ab`, `diagnosis`, `matchup-writeup`, `opponent-profile` |
| `holds.py` | How much a policy holds, beside the field | `ab`, `diagnosis`, `matchup-writeup`, `opponent-profile` |
| `hold_reasons.py` | Why our press build's units hold | `diagnosis` |
| `seat_log.py` | One of our seats' own log for a turn | `diagnosis`, `matchup-writeup`, `press-audit`, `replay-inspection` |
| **Environment** | | |
| `session_env.sh` | Private credentials and active player for this shell | none (this manual only) |
| `check_clis.py` | Warn when the `coworld` or `softmax` CLI is stale | none (this manual only) |
| `check_coworld.py` | Say when the Coworld or the optimizer template has changed since this lab last checked | none (this manual only) |
| `llm_sidecar_local.py` | Local stand-in for the hosted LLM sidecar | `eval-design` |

| Skill | Use when | Tools it runs |
|---|---|---|
| [`ab`](skills/ab/SKILL.md) | Comparing two versions | `batches.py`, `board_counts.py`, `compare.py`, `holds.py`, `make_request.py`, `paired.py`, `press_behaviour.py`, `run_ab.py`, `seat_bias.py`, `sizing.py`, `wd.py`, `webdip_episodes.py` |
| [`survey`](skills/survey/SKILL.md) | Reading a batch that came back | `batches.py`, `flag_episodes.py`, `matchups.py`, `seat_rows.py`, `wd.py`, `year_deltas.py` |
| [`replay-inspection`](skills/replay-inspection/SKILL.md) | Reading replays and our own logs | `gzip_replays.py`, `opponent_profile.py`, `press_audit.py`, `seat_log.py`, `seat_rows.py`, `wd.py`, `webdip_episodes.py` |
| [`eval-design`](skills/eval-design/SKILL.md) | Designing a hosted eval | `batches.py`, `compare.py`, `llm_sidecar_local.py`, `make_request.py`, `paired.py`, `press_behaviour.py`, `run_ab.py`, `sizing.py`, `wake_bench.py`, `wd.py` |
| [`diagnosis`](skills/diagnosis/SKILL.md) | Finding why we lose, before proposing a change | `board_counts.py`, `centre_losses.py`, `flag_episodes.py`, `hold_reasons.py`, `holds.py`, `mine_variance.py`, `opponent_profile.py`, `press_behaviour.py`, `seat_log.py`, `seat_rows.py`, `sizing.py`, `wake_bench.py`, `wd.py`, `webdip_episodes.py`, `year_deltas.py` |
| [`press-audit`](skills/press-audit/SKILL.md) | Who lied, who kept their word, where we were betrayed | `opponent_profile.py`, `press_audit.py`, `press_report.py`, `seat_log.py`, `seat_rows.py` |
| [`opponent-profile`](skills/opponent-profile/SKILL.md) | How one opponent plays | `board_counts.py`, `field.py`, `holds.py`, `matchups.py`, `opponent_profile.py`, `seat_rows.py` |
| [`matchup-writeup`](skills/matchup-writeup/SKILL.md) | Why we win or lose against each opponent | `board_counts.py`, `holds.py`, `matchups.py`, `opponent_profile.py`, `seat_log.py`, `seat_rows.py` |
| [`ide`](skills/ide/SKILL.md) | Showing the user replays, results and ideas in the browser | `paired.py`, `press_audit.py`, `run_ab.py`, `ship.py` |

The first five are the bindings the optimizer's core skills resolve; the other four are this
lab's own. [MIXIN.md](MIXIN.md) has each skill's full description.

## Tools

Standard-library Python in `tools/`, run from the optimizer root as
`python3 games/webdiplomacy/tools/<tool>.py`. They read the directories that the
optimizer's `fetch_artifacts.py` or a local `coworld run-episode` writes, so they
work the same for hosted and local runs. **Exact flags live in each tool's
docstring**; they may shift slightly from what is shown here.

| Tool | For | CLI |
|---|---|---|
| `webdip_episodes.py` | The one episode loader (results, replay, our seat logs; slot to power; bytes-literal logs) and the taint flags, listed in its docstring. Import it in your own instruments | library |
| `wd.py metrics` | Per-power score vs same-batch field par, coverage, telemetry | `wd.py metrics DIR... [--policy NAME[:vN]] [--json]` (a bare `NAME` is every version) |
| `wd.py seats` | One JSON line per seat with the center trajectory by year | `wd.py seats DIR... [--policy NAME[:vN]]` |
| `wd.py costs` | LLM spend per seat and per phase | `wd.py costs DIR...` |
| `wd.py local` | Local episodes, one image in all seats (needs Docker and `coworld`) | `wd.py local ...` |
| `wd.py arena` | Local: one candidate against a local field (needs Docker and `coworld`) | `wd.py arena ...` |
| `wd.py slim` | Strip map PNGs from replays to save disk | `wd.py slim DIR...` |
| `matchups.py` | One policy's score vs par by power, by opponent (with and without them, head to head, power pairs), by version, by source (league matches or experience requests) and by game year. SE clustered by game; fewer than 16 games is "too few", with a `lean` ("too few games (14 of 16), leaning below par") when |z| >= 2 and the 95% interval excludes par: a lead, never a result. `--alone` leaves out paired games (two or more of our seats). `--ours OTHERNAME` (repeatable) names another policy that is also ours: not par, not an opponent, and paired with the policy for `--alone`; without it the tool knows "ours" only by the `--policy` name. A source with games read and none of ours (league rounds, say) gets a line saying so. The IDE dashboard shows this report | `matchups.py DIR... --policy NAME[:vN] [--source league\|xp\|local\|all] [--variant V] [--opponent NAME] [--alone] [--ours OTHERNAME]... [--episodes FILE] [--out PREFIX] [--json]`; `matchups.py DIR... --list [--variant V] [--source S]` |
| `opponent_profile.py` | What one policy does, from the public orders: openings by power, first targets (and replies), captures, order mix and trajectory beside the field, dead and stalled seats, how it treats our policy (`--versus`). `--game` prints one game phase by phase (the way to read a game without the IDE), with `--versus OURS` marking our seats "(ours)"; `--decisions --versus OURS` adds what our own seats' logs committed each turn, and never prints another policy's log | `opponent_profile.py DIR... --opponent NAME[:vN] [--versus OURS] [--variant classic-press] [--out PREFIX] [--episodes FILE] [--json]`; `opponent_profile.py DIR... --game EPISODE_ID [--powers P,Q] [--years 1901-1903] [--versus OURS [--decisions]] [--logs]` |
| `holds.py` | How much one policy holds beside the field at the same power, by version and by game year; seats that stopped moving, with what their log says; and for our press builds, the holds split by what the press layer committed (pinned orders, forbidden provinces, the search floor) with any refusal counters the press layer logs. The mechanism check for any change that should free units | `holds.py DIR... --policy NAME[:vN] [--variant V] [--alone] [--ours OTHERNAME]... [--episodes FILE] [--stopped-phases N] [--json]` |
| `hold_reasons.py` | Why our press build's units hold: each hold as fixed by the agent (`require_orders`) or left to the search and where the unit stood (our own centre, another power's centre, elsewhere), and the hold share by how many provinces the policy forbade and how many allies it named. One column per version. Counts, not causes | `hold_reasons.py DIR... --policy NAME[:vN] [--variant V] [--json]` |
| `centre_losses.py` | Every supply centre our press build lost, one row each: home or gained, the taker, our stance toward the taker going in and in the year of the loss, the trust number we gave them, and whether we exchanged private messages that year; one table per split, the centres lost most often, and how often a power we called an ally, neutral or hostile took a centre from us in a year. `--going-in` uses the stance held the year before, which an attack cannot have changed; `--rows` lists every loss. "Talks" means messages were exchanged, not that a deal existed (`press_audit.py` reads that). Counts, not causes | `centre_losses.py DIR... --policy NAME[:vN] [--variant V] [--going-in] [--rows] [--json]` |
| `press_behaviour.py` | What our press agent does, per version, from our own seat logs: share of orders fixed, fixed as holds, every unit fixed, holds, stances, centre values, forbidden provinces, messages per phase, three or more messages to one power, wakes, LLM cost. The mechanism check for any prompt or press-guard change. Counts only, never a score | `press_behaviour.py DIR... [--policy NAME[:vN]] [--json]` |
| `board_counts.py` | A claim counted over every game, for one policy at one power and for the field beside it: an order given (`"A VEN - TRI"`, `"* - HOL"`), a centre owned after each year, a unit left in a province. Use it instead of writing a script for "it does X in n of m games" | `board_counts.py DIR... --policy NAME[:vN] --as POWER [--order TEXT]... [--owns PROV]... [--unit-at PROV]... [--when S1901-A1902] [--split-by POWER] [--variant V] [--rows] [--episodes FILE] [--json]` |
| `seat_rows.py` | One row per seat of a policy, worst score first: centres by year, taint (its own and other seats'), first targets, home centre lost; with `--versus`, the other policy's side of each shared game, written with the two policy names (never "we" or "it", because `--policy` may be an opponent). "Our five worst games as Austria" in one command | `seat_rows.py DIR... --policy NAME[:vN] [--as POWER] [--versus OTHER] [--variant V] [--sort score\|episode] [--limit N] [--episodes FILE] [--json]` |
| `seat_log.py` | One of our seats' own log for a turn: press received and sent, each policy it committed with the orders that followed, wakes, the decision line, errors. The "why" beside `opponent_profile.py --game`'s "what". Prints private press: terminal only | `seat_log.py DIR... --game EPISODE_ID --power POWER [--when A1902] [--events ...] [--chars N]` |
| `batches.py` | What each fetched batch cost and how long it took, from the episode rows: launch and finish (Pacific Time), wall-clock minutes, game and queue minutes, `cost_usd`, and the platform's credit estimate when the create responses are on disk. The games cell says whether the batch is whole: "30 of 70 in, still arriving" when the create responses say more games were asked for than are on disk (no finish or wall time is printed then), "asked for unknown" when no response says | `batches.py DIR... [--responses DIR] [--json]` |
| `paired.py` | Paired difference, its SD and z for two policies in the same games; `vs_par_by_power` compares the two at the same power | `paired.py ...` |
| `compare.py` | A/B by power for separate arms | `compare.py BASE_DIR CAND_DIR --baseline NAME:vN --candidate NAME:vM` |
| `session_env.sh` | Private credentials directory, Docker config and active player for this shell, in one step; `git` and `gh` keep using the real home. In an agent harness pin `WEBDIP_SESSION_HOME` and source it on every command line ([docs/platform.md](docs/platform.md#setup)) | `source games/webdiplomacy/tools/session_env.sh <player id>` |
| `check_clis.py` | Warns when the `coworld` or `softmax` uv tool is missing or older than PyPI's latest. With the Claude Code harness a SessionStart hook runs it; on other runtimes run it yourself at session start (`-v` also reports when both are current) | `check_clis.py [-v]` |
| `check_coworld.py` | Compares the lab's `CHANGELOG.md` with the current one in coworld-webdiplomacy and looks up the hosted Coworld version; lists the entries this lab has not applied. A SessionStart hook under Claude Code; on other runtimes run it at session start. See [Keep the lab current](#keep-the-lab-current) | `check_coworld.py [-v] [--show] [--ack]` |
| `llm_sidecar_local.py` | Local stand-in for the hosted LLM sidecar (needs `OPENROUTER_API_KEY`). `--upstream URL --key-env NAME [--drop FIELD]...` forwards to another OpenAI-compatible provider instead: not the hosted path, so label any read from it with its model | `llm_sidecar_local.py [--port N] [--ledger FILE] [--upstream URL --key-env NAME --drop FIELD]` |
| `ab_stats.py` | The statistics behind `compare.py` (Welch t, Fisher exact, multiple-test correction) | library |

**Where code lives.** Everything this mixin ships is in `tools/` (linted and unit-tested
upstream). `instruments/` starts empty and is yours: analysis you write and will run more
than once goes there, importing `tools/webdip_episodes.py`. Before you write one, check the
table above: `holds.py`, `seat_rows.py` and `board_counts.py` already print hold shares,
per-seat rows, order counts and centre ownership. Scratch output goes in a folder under
`.runtime/`, not loose in `.runtime/` itself.

### Campaign tools

Also in `tools/`, run the same way; flags are in each docstring.

| Tool | For |
|---|---|
| `field.py press\|gunboat` | Who is in a league's field (from its rounds), with version ids for rosters, and the seating of each round |
| `make_request.py` + `../field_sets.json` | Request bodies from a named opponent set; `--balanced` (powers pinned and rotated; a paired A/B gets both seat orders, 14 bodies), `--pin-a POWER` (our seat fixed to one power), `--no-maps`, `--config KEY=VALUE` (any other episode setting; `end_year` and `phase_minutes` give a shorter game, see [docs/platform.md](docs/platform.md#shorter-games)). `field_sets.json` ships with the format only: list the field with `field.py`, then write your own named, dated sets (a stale id fails at create time with "Policy version … was not found") |
| `seat_bias.py` | Whether one roster seat outscores another whoever sits there (reads `wd.py seats` on stdin); for same-code checks |
| `mine_variance.py` | Which measured behaviours go with a policy's own good and bad games (correlations: hypothesis fuel only) |
| `run_ab.py` | One paired A/B end to end from an experiment record: bodies, dry run, launch, ids into the record, fetch, compress, read (pooled over the record's `artifacts:` folders when it lists them). `--dry-run` prices a run and launches nothing: the platform's saved quotes for requests of the same kind this lab created, the total, and a line beside `batches.py`'s finished batches (it works with `--alone`, `--variant` and `--health`); the price moves, so an old quote can be short. `--resume` picks up an interrupted run at the fetch; `--health SET` also launches one `classic-press-short` health game and notes its id (it does not read it); `--health-games N` makes it N games. `--alone` runs the candidate-alone check (each version alone against a six-seat field), which every paired win needs before promotion; it fetches both arms at once. `--variant classic-press-short` runs a screen stage instead: the paired design on the short variant (about 25 minutes), ids kept apart in the record's `screen:` list, read for health and behaviour only, no score verdict; `--config KEY=VALUE` with it shortens the screen games further (`--variant classic-press --config end_year=1903 --config phase_minutes=2`). `--max-credits N` stops a paired launch as soon as the batches still to create, at the price the platform just quoted, would pass N (some batches are then launched and are not a balanced run by themselves; the tool says so). `--add-set` launches one more full set into a record that already has batches, read together with the rest: plan the sets in the decision rule first |
| `wake_bench.py sample\|run\|report` | Replays recorded phase-start decisions of our seats under another prompt, model or setting, through the policy's own code (real tools, real search, no server): a read of the agent's behaviour in minutes for cents, printed as the `press_behaviour.py` table. It also shows how often the final orders differ from the plain search's, beside how often a plain re-search differs by itself (the zero for that row), and how many decisions were cut off at a time or call limit. A screen for behaviour, never a score. A real-model run needs `llm_sidecar_local.py` with a working key and pydantic-ai; `--scripted` needs neither. Keep cases and runs under `.runtime/bench/` |
| `sizing.py` | Games needed for an effect size, and the smallest effect a number of games can see. Its default SDs are starting values measured once; pass your own with `--sd` (`paired.py` prints `sd`) |
| `ship.py` | Build, upload, look up the version id and append the VERSION_LOG row in one step |
| `my_versions.py` | Every version the active player has uploaded, by policy name, newest first, with the versions that hold a league entry now marked `IN LEAGUE` (league, division, `active`, `benched` or `champion`). Reads every page of the platform's lists, so the count is whole. `--policy NAME`, `--in-league`, `--past` (entries that ended), `--json`. Use it before an upload under a name you did not choose yourself, and before saying "nothing of ours is entered" |
| `flag_episodes.py` | Episodes worth opening (reads `wd.py seats` on stdin) |
| `year_deltas.py` | Centre change per game year by policy (reads `wd.py seats` on stdin) |
| `gzip_replays.py` | Compress fetched replays in place, about 20x; the loader reads them |
| `fetch_league.py press\|gunboat` | A league's finished rounds (the most recent 20; `--rounds N`) into `.runtime/artifacts/league-<press\|gunboat>/round-NNNN/`, so league matches sit beside experience requests (`webdip_episodes.episode_source` tells them apart); `--policy NAME` keeps only the rounds that seat it |
| `press_audit.py extract\|check\|verify\|report` | One press game from our seat: every message we saw, its claims (an agent lists them from `annotate.json`, which shows no orders or results, or its per-year parts from `extract --by-year`; `check` tests the format), each checked by code against the orders, and a local HTML page (`press_report.py` draws it). Read the flagged claims' evidence before quoting its counts. See the press-audit skill |

## The IDE

`ide/` (at the optimizer root) is a local web page for the user: replays with notes and the
press audit laid over them, the `matchups.py` dashboard, the experiment records
(`/experiments`: each record's status and rule with `paired.py`'s number for its games so far),
the reports the two write-up skills produce, and a chat panel that reaches **this session**. You start it (`ide/ide start --open`)
when the user asks or when you have something to show; their messages arrive through this
session's hooks as text starting `[webDiplomacy IDE]`, and you answer with `ide/ide say` and
`ide/ide show`: the user reads the browser, so the whole answer and any question for them go
there, not to the terminal. When they say which policy is theirs, record it with
`ide/ide follow <name>`. Their replay notes (`annotations/<episode id>.json`, `ide/ide annotations`) are
evidence for the loop: read them before a diagnosis. The [IDE skill](skills/ide/SKILL.md) has
the commands; `ide/README.md` explains how delivery works.

## Keep the lab current

The game and this lab's template both change. A lab is a copy: nothing updates it but
you. So **at the start of every session, before other work, check for changes**:

```sh
python3 games/webdiplomacy/tools/check_coworld.py -v
```

(Under Claude Code a SessionStart hook runs it and prints only when something is new.)
It compares the lab's [CHANGELOG.md](CHANGELOG.md), the copy this lab was last brought
up to date with, against the current file in coworld-webdiplomacy, and looks up the
hosted Coworld version. When it lists new entries:

1. **Read them:** `python3 games/webdiplomacy/tools/check_coworld.py --show`. Tell the
   user what changed before you change anything.
2. **Get the source:** `git clone --depth 1 https://github.com/Metta-AI/coworld-webdiplomacy
   <scratch dir>`. The lab's files are under `optimizer/mixin/` there, and `ide/` is
   `optimizer/ide/`.
3. **Apply each entry's "In your optimizer" steps, oldest entry first.** For a file the
   entry says to copy: if this lab never changed it (`git log --oneline -- <file>` shows
   only the commit that created the lab), take the new file. If the lab changed it, merge
   the upstream change into the lab's version and keep the lab's own work. Never
   overwrite `players/`, the registers (`open_levers.md`, `closed_levers.md`,
   `best_practices.md`), `META.md`, `field_sets.json`, `experiments/` or `reports/`:
   those are this lab's own.
4. **Carry a game change through the lab.** When an entry changes what the game does (a
   config field, an environment variable, a rule, a variant), find every place the lab
   states the old fact (`grep -rn` the lab for the field or the number) and fix the docs,
   the skills and your policy's code. Check `PINNED_GAME_REF` in `tools/build.sh` against
   the entry. Then run one health game before any batch.
5. **Check and record:** `(cd games/webdiplomacy && python3 -m unittest discover -s
   tools/tests)`, then `python3 games/webdiplomacy/tools/check_coworld.py --ack`, update
   the commit in [MIXIN.md](MIXIN.md)'s "Provenance", and commit it all with the entries'
   titles in the message.

When the tool says the hosted Coworld version is one the changelog does not name, the
game was released before its entry was written. Read the recent commits of
coworld-webdiplomacy, and treat every game fact in `docs/` as unchecked until an entry
arrives or you have verified it.

A new Coworld version can change scores. Do not pool games played on two Coworld
versions in one read; `coworld xp-request get <xreq>` prints the version a request ran on.

## How the loop runs here

| Loop step | In this game |
|---|---|
| Understand | [docs/game.md](docs/game.md), then [docs/strategy.md](docs/strategy.md); refresh `META.md` if stale (`coworld leagues <league_id> --json` gives the filler roster, `tools/field.py` who was seated, and the [opponent-profile](skills/opponent-profile/SKILL.md) skill how each plays); replays show every power's orders and public press |
| Evaluate | Hosted XP requests on the league's full variant against explicit field `policy_ref`s; paired seating by default; stream artifacts. See [eval-design](skills/eval-design/SKILL.md) |
| Read | Taint first, then score vs same-batch par **per power**; \|z\| < 2 is no result. See [ab](skills/ab/SKILL.md) and [survey](skills/survey/SKILL.md) |
| Hypothesize | Known failure modes and the procedure in [diagnosis](skills/diagnosis/SKILL.md). Before proposing, read [closed_levers.md](closed_levers.md) (every heading), [open_levers.md](open_levers.md) and every record in `experiments/`, whatever its status. An idea you offer the user becomes a `proposed` experiment record at once (`record.py new`), not a line in `WORKING_CONTEXT.md` |
| Build | `tools/ship.py` (build, upload and VERSION_LOG row in one step; it calls `tools/build.sh`), one image tag per experiment; press builds are uploaded with an LLM model (default `z-ai/glm-5.3-flash`, `--llm-model` to change) |

## Run one A/B, start to finish

In the main league (`classic-press`), which is where to work unless you have a
reason to use Gunboat. From the optimizer root, with the private `HOME` from
[docs/platform.md](docs/platform.md#setup) and the right player active.
`L=games/webdiplomacy`, `R=skills/run-eval/scripts`. First fill
`field_sets.json` with a five-seat set from the current field
(`python3 $L/tools/field.py press` lists it with version ids).

```sh
skills/experiment/scripts/record.py new $L <slug>          # then fill hypothesis, predictions, rule
#   run record.py directly (its first line uses uv); `python3 …/record.py` fails with "No module named 'yaml'".
#   It copies the template with the id set. Write `candidate: n/a` until ship.py has printed the version, then the version.
python3 $L/tools/ship.py --name <policy> --slug <slug> \
    --change "<the one change and its mechanism>" --overrides "KEY=VAL" --experiment <record id>
python3 $L/tools/make_request.py paired --a <policy>:vNEW --b <policy>:vBASE \
    --field-set <paired set> -n 2 --balanced --no-maps --note <record id> --out $L/.runtime/requests/<slug>.json
$R/eval_request.py create $L/.runtime/requests/<slug>-r0.json --dry-run
bash -c 'for f in '$L'/.runtime/requests/<slug>-r*.json; do '$R'/eval_request.py create $f; done'   # 14 batches; note each id
skills/fetch-artifacts/scripts/fetch_artifacts.py XREQ1 XREQ2 … --watch --out $L/.runtime/artifacts/<record id>
python3 $L/tools/gzip_replays.py $L/.runtime/artifacts/<record id>
python3 $L/tools/paired.py $L/.runtime/artifacts/<record id> --a <policy>:vNEW --b <policy>:vBASE
```

Everything from the third command on is one step with
`python3 $L/tools/run_ab.py --record <record id> --a <policy>:vNEW --b <policy>:vBASE --field-set <paired set> -n 2`
(it refuses a record whose front matter still has a `<...>` placeholder, and `--resume`
picks up an interrupted run). A record's result is read from
`.runtime/artifacts/<record id>` plus any folders its `artifacts:` key lists
([experiments/_template.md](experiments/_template.md)); the IDE reads the same folders. `ship.py` writes every row to `players/castlereagh/VERSION_LOG.md`,
whatever `--name` you upload under: the log follows the source directory, not the
uploaded policy name.

- `ship.py` builds the press mode and uploads it with an LLM model by default.
  For a press set, `make_request.py` gives each game an LLM budget (a cap of
  $14 split over the seven seats); with a zero budget every LLM seat would play
  its search floor and say nothing.
- `--balanced` writes 14 batches: every power and both seat positions equally
  for each version. `-n` is games per batch:

  | `-n` | Games | Platform's estimate at create (1.4 to 3.3 credits a press game) | Recorded `cost_usd` (about $0.5 a press game) | Smallest effect at z = 2, with `sizing.py`'s starting SD |
  |---|---|---|---|---|
  | 1 | 14 | 20 to 46 credits | about $7 | 0.11 |
  | 2 | 28 | 39 to 92 credits | about $15 | 0.08 |
  | 6 | 84 | 118 to 277 credits | about $45 | 0.04 |

  **What a game costs, and what is not known** (as the platform reported it on
  2026-10-11 and the night after; `tools/batches.py` prints both numbers for your own batches). The platform
  prints an estimate when a request is created (`cost_preview.estimated_cost_credits`;
  `eval_request.py create` shows it and saves it; `coworld xp-request get <xreq>
  --json` returned none for requests made on the night of 2026-10-11): 1.37 to 3.34 credits per full press game and 0.50 per
  gunboat game. It moves: in one night the same request was quoted at 2.23 credits a game,
  then 3.24 to 3.34 five hours later, a request of ten games was quoted at 2.82 a game in
  between, and a short health game costs the same as a full one. Nothing prices a request
  without creating it. So never give the user a figure from this page before a launch: give
  the one the create step prints, and when the user has set a credit limit, launch in sets
  and read each set's estimate before the next. After a game ends its episode row carries `cost_usd`: $0.51 to $0.61 per
  press game, $0.026 per gunboat game, $0.11 to $0.28 for a short health game.
  **Not established:** the credits actually charged (nobody read a balance), and how
  `cost_usd` converts to credits. Quote the platform's estimate, say it is an estimate,
  and ask the user to check their credit history if it matters.

  The effect sizes come from `python3 $L/tools/sizing.py --games N`. They rest on the
  tool's starting SD for a paired press difference (0.20: measured once, on 2026-10-10/11,
  against one or two opponent sets; not a fact about the game). Check it against your first
  batch (`paired.py` prints `sd`) and re-size with `--sd`.
- **Size the run for the effect you can expect, before the first game.** `sizing.py
  --games N` gives the smallest difference a run can see. A run that cannot see the
  effect you expect will end "inconclusive", and extending it afterwards means a rule
  written after seeing data. Either plan the larger run from the start, or write a
  two-stage rule into the record before launch (the
  [ab binding](skills/ab/SKILL.md#extending-a-run) has the wording): stage one checks
  that the mechanism fired and nothing broke; the one score read is on the full total.
- **A full press game ran about 61 minutes with 4-minute phases (about 48 are expected with the 3-minute phases of Coworld 0.7.10; not yet measured); what you wait for is the slowest one.**
  As the platform reported it on 2026-10-11 (`tools/batches.py` prints it for your own
  batches): median 61 minutes of play, longest 75; a short health game 23 to 27.
  Batches run in parallel, and most games start within 3 minutes of launch:

  | Launched together (2026-10-11) | All finished after |
  |---|---|
  | 57 press games | 70 minutes |
  | 56 press games | 100 minutes: 54 were in after 68; two started 38 minutes late |
  | 85 press and 238 gunboat games | press games 79 to 129 minutes, with one game restarted by the platform; a 140-game gunboat batch waited a median 56 minutes behind the press games |

  So plan about 70 minutes for up to about 60 press games, allow 100 to 130 for a
  straggler or a crowded queue, and do not launch a large gunboat batch into a queue
  full of press games (a gunboat game runs 2 minutes but waits its turn). The platform
  retries a failed episode up to twice (`fulfillment.retry_times` in the league
  settings), which is what a late straggler probably is. Launch, record the ids, and
  read the result later: `--resume` fetches and reads when the games are done.
  `fetch_artifacts.py --watch` prints only a heartbeat until games end, then everything
  arrives within a few minutes: there is no partial read to wait for.
- **You have no clock.** Run `date` before you tell the user a time, a duration or
  "how long is left", and take batch durations from `tools/batches.py`.
- **`run_ab.py`, what it does and does not do for you:**
  - It refuses a record whose `evals` already has paired ids (use `--resume`), and it
    writes each new id into the record as the file is at that moment, so an edit you
    make during the launch is kept.
  - `--alone` can run at the same time as the paired games. Its ids go into `evals` and also into
    `alone_a:` and `alone_b:`, so the paired `--resume` leaves them out and
    `--alone --resume` fetches the two arms again.
  - `--alone -n 2` is 14 games per arm. `compare.py` gives a verdict only from 30 seats
    per side, so that size can show a large reversal and nothing else (the tool warns).
    Use `-n 5` (35 per arm) or more when the alone check has to be able to pass or fail.
  - `--health <six-seat field set>` launches the health game with the batch and writes
    its id into the record's text (not `evals`). It does not fetch or read it: do that
    as the next item says.
  - The "launched N batches" line gives the platform's estimate in credits. Quote that.
- **Run it in the background and poll its output file** for "launched 14 batches"; it
  then watches until the games end. Nothing else signals that the ids are in the record.
  A watcher started from an agent's shell can die with that session, `nohup` or not, and
  nothing tells the next session. The games are not affected. At the start of a session
  with a run in flight, check `pgrep -fl run_ab`; if it is gone, start it again with
  `--resume` (or `--alone --resume`), which launches nothing.
- After every press upload or model change, run one health game on
  `classic-press-short` and confirm every `llm_call` in our seat logs succeeded
  (`make_request.py field … -n 1 --variant classic-press-short` builds it; see
  the eval-design binding). A failing LLM seat looks healthy. The pass line is
  the `telemetry` line of `wd.py metrics DIR --policy NAME:vN`: `rejected 0`,
  `exceptions 0`, `llm calls N (0 failed, …)`, and `press_sent` above zero in
  the trace. The same line prints `http errors`: report the number when it is not
  zero, and do not write "no errors" over it. A seat's log cannot be read until its game ends (about 25 minutes
  for the short variant, measured 2026-10-10), so in a short session launch the
  health game and the first batch together and discard the batch if the health
  game fails. Write that choice into the experiment record.
- **A paired run gives a fair difference, not a fair level.** With two of our
  seats in one game the score level is not what one seat gets alone, and the
  gap can go either way. Read "how good is this version" from an alone
  run (`run_ab.py --alone`, or a field eval), never from a paired one.
- Put the batch ids and the artifact directory in the experiment record as
  soon as they exist.

**The Gunboat league** (`classic-gunboat`, no press) runs the same recipe with a
gunboat field set. Games take about 2.4 minutes and half a credit
(2026-10-10), so it is a fast way to test a change to the search core alone.
It says nothing about negotiation.

## Mechanics ground truth

The source of truth is the **upstream webDiplomacy server pinned by
coworld-webdiplomacy** (see [MIXIN.md](MIXIN.md)), described with file and line
citations in that repo's
[docs/upstream-bot-api.md](https://github.com/Metta-AI/coworld-webdiplomacy/blob/b4aca7310d1de95fe3fc6f61606bfe7ac05335ab/docs/upstream-bot-api.md).
Verify mechanics claims there, never from memory. Cache verified facts here
with where they were verified:

- Invalid orders are dropped silently with HTTP 200; an unknown `terrID`
  returns 400 — upstream `api.php:1040-1078`, `:1008-1017` (via
  upstream-bot-api.md at `b4aca73`).
- Seats are `User` accounts in a `MemberVsBots` game, so votes count and a
  silent seat holds without delaying the phase — upstream-bot-api.md §11.
- 34 supply centers: 3 per power, 4 for Russia, 12 neutral — upstream
  `variants/Classic/install.php`.

## Gotchas

Each of these costs real time or a wrong conclusion.

- **HTTP 200 does not mean your orders were accepted.** Upstream silently drops
  invalid orders. Diff the saved orders every phase and log `rejected`; any
  nonzero count is a bug.
- **Scores are in slot order, not power order.** `results.countries[slot]` is
  that slot's power.
- **Final centers come from `results.json`** `members[].supplyCenterNo`
  (strings). The replay's `Finished` history entry shows ownership from before
  the last Autumn.
- **Hosted seat logs sometimes arrive as a Python `b'...'` bytes literal.** Use
  `webdip_episodes.py`, which decodes them.
- **Use a private `HOME` per session for Softmax credentials.** Other sessions
  running `coworld player use` switch the identity in the shared
  `~/.softmax/credentials.yaml`; private requests then return 404. Recipe in
  [docs/platform.md](docs/platform.md#setup).
- **One image tag per experiment.** Rebuilding a tag while games run switches
  later games to the new code.
- **Install the CLIs as uv tools:** `uv tool install coworld` and
  `uv tool install softmax-cli`. Keep them current: `tools/check_clis.py`
  prints a fix when either is stale (a SessionStart hook runs it under the
  Claude Code harness). Act on it first.
- **A failing LLM seat looks healthy.** It plays its search floor with no error.
  Check `llm_call` statuses per seat after any model or prompt change.
- **Never use `random` roster seats.** They can seat you against yourself.
- **A deleted pod is a dead seat, not only a lost log.** A seat log that says only "No logs
  collected for pod … the pod was deleted before log collection" means the platform deleted
  the bot's pod mid-game and the seat held from then on (taint `pod_deleted`; about 2.5% of
  press seats on 2026-10-10/11). `wd.py metrics`, `paired.py`, `compare.py` and `matchups.py` drop
  those games (`opponent_profile.py` keeps and counts them); report how many.
  The cause is on the platform side, a lost node under the pod (27 of 29 dead seats on
  2026-10-10/11 fell in three wall-clock windows; press games are exposed for an hour,
  gunboat games for minutes). So dead seats come in clusters, the episode still reads
  `completed`, and re-running a health game is the only check that it was not your
  build. **A rival's dead pod is invisible to a normal account** (its log is 403): it
  shows only as a seat that holds to the end (`tools/holds.py` lists stopped seats), and
  the seats beside it collect free centres.
- **The hand-off is `WORKING_CONTEXT.md`, not a file under `.runtime/`.** `.runtime/` is
  not tracked and the next session does not read it. Batch ids go in the experiment record,
  the current objective and open threads in `WORKING_CONTEXT.md`.
- **Put batch ids in the experiment record at launch; the platform will not find them
  for you later.** `coworld xp-request list --mine` rows have no roster and no title,
  the list is paged (1,000 rows came back with a `next_cursor` on 2026-10-11: follow it, or
  a count is wrong), and
  `coworld xp-request episodes <xreq> --json` returns sealed rows with no participants.
  `coworld xp-request get <xreq> --json` does return the note `make_request.py` wrote
  (`requested.notes`: the experiment id and field set) and the cost estimate.
- **When a later count overturns something a report says, fix the report.** Reports are
  tracked and the IDE shows them. A correction that lives only in a chat message leaves
  the file teaching the next reader the old claim.
- **zsh is the shell on macOS.** `echo ===` fails ("= not found"), an unquoted
  `--include=*.py` fails ("no matches found"), and `$IDS` holding several ids is passed as
  one word (use an array, or `${=IDS}`).
- **The bot is killed at game end.** Log every phase; do not rely on an
  end-of-game summary.
