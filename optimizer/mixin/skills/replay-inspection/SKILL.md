---
name: webdiplomacy-replay-inspection
binding: replay-inspection
description: >
  webDiplomacy binding for the core replay-inspection skill: how to open,
  decode, and read this game's replays and the policy's own artifacts.
---

# Replay-inspection binding — webDiplomacy

The core `replay-inspection` skill carries the method: the replay is ground
truth, the policy's artifacts are its point of view, and diagnosis lives in the
gap between them. This binding supplies the formats and the clock.

This binding is a first version. A better local game viewer is planned (see
Tooling).

## Replays

- **Format:** a JSON array of public frames, oldest first. The platform stores
  it gzip-compressed; check the first bytes rather than the file name. Each
  frame holds upstream's public files verbatim plus a few fields:

  | Field | Contents |
  |---|---|
  | `variant` | The map: territories, adjacency, supply centers (same in every frame) |
  | `game` | Current turn, phase, deadline, members, units, territory owners |
  | `status` | Who has saved orders, who is Ready, current votes |
  | `history` | Every completed phase: units, owned territories (`centers`, not only SCs) and adjudicated orders with `success` / `dislodged` |
  | `messages` | **Public** press only |
  | `lifecycle` | `turn`, `phase`, `process_status` |
  | `episode.seed` | The episode seed |
  | `map` | Optional PNG of the adjudicated turn (large; `wd.py slim` strips it) |
  | `ending` | Last frame only: `outcome` and `reason` |

- **Read the last frame's `history.phases`** for the whole game's orders and
  results. A new frame starts whenever `lifecycle` changes; it is an observed
  phase replay, not an event log.
- **Final centers:** the `Finished` history entry shows ownership from before
  the last Autumn. Take final counts from `results.json` `members`.
- **Watch one:** `coworld replay-open <episode-request-id> --hosted` opens the
  hosted viewer (positions, adjudicated orders, public press, map per season).
- Full format:
  [docs/replay.md at b4aca73](https://github.com/Metta-AI/coworld-webdiplomacy/blob/b4aca7310d1de95fe3fc6f61606bfe7ac05335ab/docs/replay.md)
  and upstream's game data spec (`webdiplomacy/doc/gamedata/02-spec.md` in that
  repo).

## Policy artifacts

Only our own seats' logs and artifacts are readable.

- **Player log:** everything our bot printed. The reference policy
  (`players/castlereagh/`) logs as much as it can, because the launcher kills
  the bot at game end and an end-of-game summary may never be written:
  - one `decision` JSON line per phase: `turn`, `phase`, the orders chosen,
    and `rejected` (orders upstream dropped);
  - `exception` events with a traceback tail;
  - in `press` mode, `llm_call` events (model, status, `usage.cost`) and the
    LLM's requests, replies and tool calls.
  Other event names are in the policy's source under `players/castlereagh/`.
- **Private press:** the launcher's `private_press` record at the end of the
  player log, and `private-press.json` in the seat's artifact ZIP. Our seat's
  private messages only.
- Hosted logs sometimes arrive as a Python `b'...'` bytes literal;
  `webdip_episodes.py` decodes them.

## The shared clock

**`(turn, phase)`** joins everything. Turn 0 is Spring 1901; year is
`1901 + turn // 2`; even turns are Spring. Phase is the raw upstream value
(`Diplomacy`, `Retreats`, `Builds`). Replay frames carry it in `lifecycle`,
history entries carry it per phase, and our `decision` lines carry it. Press
messages carry the turn they were sent in.

## What to look at

- **The orders we meant versus the orders adjudicated.** Diff our `decision`
  orders against the replay's history for that phase. Any difference is a
  dropped order or a logging bug.
- **The phase where our center count fell.** Read that phase's adjudicated
  orders: who attacked, with which supports, and what we expected.
- **Press against deeds.** For a betrayal, line up the private promise (our
  artifact), the public press, and the orders actually played the next phase.
- **The final year.** Did we take centers in the last Autumn, or hold position
  for a year that never comes?
- **For LLM seats:** did the LLM run at all (`llm_call` statuses), and did its
  committed orders differ from the search's own choice?

## Tooling

Run from the optimizer root. **Exact flags live in each tool's docstring**.

- `games/webdiplomacy/tools/webdip_episodes.py`: the one episode loader. Reads
  results, replay and our seat logs; maps slots to powers; decodes
  bytes-literal logs. Import it in new instruments instead of writing a new
  parser.
- `python3 games/webdiplomacy/tools/wd.py seats DIR...`: per-seat rows with the
  center trajectory by year.
- `python3 games/webdiplomacy/tools/wd.py slim DIR...`: strip map PNGs from
  replays to save disk.
- **Later:** a local HTML game viewer with press shown as chat next to each
  phase's orders (the prior lab's `game_viewer.py`, which needs the
  `diplomacy==1.1.2` package). Until then, use the hosted viewer and the loader.
