# Public replay and spectator viewer

`/global` streams the latest public snapshot without requiring a seat. Its only
input behavior is to resend that snapshot. `/client/global` accepts the optional
`address` WebSocket URL and works beneath a proxy path prefix. It has no order,
press-send or vote controls.

The live view counts down to the public `game.processTime` (Unix seconds), clamped
at zero while adjudication catches up. Paused, pre-game, finished, disconnected,
and missing-deadline states show **—**. Everyone marking Ready can end a phase
early. Recorded replays never show this wall-clock countdown. Phase headings,
history choices and replay timeline labels display **Movement** for upstream
`Diplomacy`; stored replay and API values remain unchanged.

The replay artifact is a JSON array of observed public frames, oldest first. The
platform stores it gzip-compressed (`replay_compression` in the manifest). Each
frame contains upstream's public `variant`, `game`, `status`, `history`, and
`messages` files verbatim, plus:

- `lifecycle`: `turn`, `phase` and `process_status` (`Not-processing`,
  `Processing`, `Paused` or `Crashed`) from the committed game row.
- `episode.seed`: the chosen episode seed (absent in older prototype replays).
- `map`, when `render_maps` is true: `turn` (the adjudicated turn pictured, `-1`
  for the starting position) and `png`, a PNG data URL.
- `ending` on the final frame only: `outcome` and `reason`, with the same values
  as `results.json` (see [protocol](protocol.md#game-lifecycle-and-output)).

Where to find things in a frame. Upstream's
[game data spec](../webdiplomacy/doc/gamedata/02-spec.md) (section 2) defines
each file's fields; the [bot API reference](upstream-bot-api.md#4-reading-a-game)
summarizes them.

| Question | Field |
| --- | --- |
| Map, territories, adjacency, supply centers | `variant` (identical in every frame) |
| Current turn, phase, deadline, members, units, territory owners | `game` |
| Who has saved orders, who is Ready, current votes | `status` |
| Every completed phase's units, center owners, orders and results | `history.phases` |
| Public press | `messages` |
| Episode-level state and how it ended | `lifecycle`, `episode`, `ending` |

Turns count from 0 (Spring 1901): year is `1901 + turn // 2`, even turns are
Spring and odd turns Autumn. Upstream's raw movement phase is `Diplomacy`; the
other phases are `Pre-game`, `Retreats`, `Builds` and `Finished`. A new frame
starts whenever `lifecycle` changes, so a pause adds a frame within a phase.

The writer reads only upstream public files and checks their versions and phase
against committed state. It never reads private player contexts or draft orders.
Updates within a phase replace that phase's last snapshot. This is an observed
phase replay, not a timestamped event log: press appears at the phase where it was
last observed. Public history retains the engine's completed adjudications.

PNG capture invokes unmodified `map.php` as a guest, without credentials or the
`preview` parameter. During Diplomacy, upstream exposes the previous completed
season; Retreats and Builds expose the current adjudication. The renderer cache
is bypassed so later retreats and builds update that season's picture. The adapter
checks for a phase change during rendering before pairing a PNG and snapshot.
Cancellation retains the last captured public state and map because upstream
erases the game. PNGs are embedded, so playback does not contact the former game.

The current-position SVG uses Classic's base map, country colors, public unit and
center coordinates. Dislodged units are offset and translucent. If upstream omits
positions after a draw, the viewer labels and uses the last observed board.
Pre-game frames explicitly identify the starting position: units appear in Spring 1901.
The viewer shell uses a light paper background with ink text; the native map palette
is unchanged.
The expandable PNG is separately labeled with its upstream adjudication turn.
History selection shows public orders and their success/dislodgement flags.
Press is rendered as text, never injected as HTML.

## Static bundle

The manifest declares `game.replay_viewer.bundle` and gzip public-copy compression.
`tools/build_replay_viewer.sh` recreates its destination below `build/` (or hydrated `dist/build/`), copying
`adapter/viewer.html`, `adapter/client/viewer.js` and the native Classic sample PNG
generated during image bake. The hook builds the game image from current sources
and copies the PNG from a temporary, unstarted container. This applies upstream
colors and province labels instead of displaying its raw indexing-color resource.
Generated files are ignored by Git. There are no runtime CDN or game-server assets.
The live page loads these same checked-in renderer sources through nginx.

Open `index.html#replay=<URL-encoded artifact URL>`. The legacy query parameter is
also accepted; a nonempty fragment parameter wins. The artifact URL must permit
browser fetches (CORS when on another origin). Bytes are interpreted as JSON,
gzip or zlib by their magic/header, not by URL suffix. Native Fetch,
`DecompressionStream` and image decoding are the only asynchronous browser glue;
no game rules or adjudication are implemented in the viewer.

The viewer reports `coworld-replay` loading/phase/ready/error messages to an
embedding parent. Readiness follows first-frame rendering, base image decoding
and initial embedded image decoding, across a task boundary that also works in
an offscreen iframe. Missing URLs, failed downloads, incompatible/corrupt JSON
and failed map images show an error. Playback supports autoplay, pause, phase
selection, 1×/2×/4× speed, loop or stop at the end, and responsive resizing.
Older public-array replays without embedded PNGs or seed metadata still open.

The static bundle replaces the former container replay service. A game container
is not started for replay viewing. Upload, certification and hosted acceptance
are separate from the local browser checks.

Use `coworld run-episode` followed by `tools.check_replay` for local validation.
In CLI 0.1.56 (the pinned version), the optional `--verify-replay` flag explicitly probes the legacy
container `/client/replay` route even when a static bundle is declared; it is not
the static viewer check. The static browser test replaces that legacy CI probe.
