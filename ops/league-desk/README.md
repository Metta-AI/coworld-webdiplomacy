# The League Desk

A local, read-only operations page for the webDiplomacy leagues. The collector
uses your existing Softmax User login with elevated privileges and saves selected
fields to SQLite. The page reads that cache, never the platform.

**API and public-artifact page:** current memberships, cumulative ratings and
local rating history, submissions, round/game timing, exposure, throughput and
player head-to-head and games together (how often each pair shares a game) are available alongside the health strip. Charts use local
Observable Plot and D3 bundles. Every chart mark shows a formatted hover card
(`static/tooltip.js`, `window.deskTip`); a stacked bar's card holds a small pie and a table of the whole stack
with values, shares and total. Stacked bars carry a legend; past eight series the smallest share one grey
"Other" colour. Static files are served with `Cache-Control: no-cache`, so the browser revalidates them
(a cheap 304) and never runs a stale script after an update. Interactive panels render a
`<div data-widget data-src>` mount point (set `content["widget"]`); the 60-second refresh keeps that node
and its state while `data-src` is unchanged, then calls each function in `window.deskWidgets`. MMR over time scales to the
rating lines, clipping the wider μ ± 3σ band. Timing and seat-health panels sit last. League-only daily source costs, stable player/policy model attribution, SQL seat
spend, compute unit costs and experience-request history are
available with explicit scope/coverage. Public results and replay facts provide The board map (contests, wins, scores, holders by phase and player), policy/power scores,
end reasons. Public 0.7.12 instrumentation adds Ready timing and seat health. There is no rating backfill. Range/version filters, local house fonts, rating
bands and automatic fragment refresh are available.

## Run

From the repository root:

```sh
uv sync --project ops/league-desk --locked --group dev
uv run --directory ops/league-desk python -m league_desk serve
```

Open <http://127.0.0.1:8660>. The process starts one collector child and stops that
child on exit. Another collector holding the cache lock is left alone. To choose
another local port, use `serve --port 8661`; remote binding is not supported.

The page works without login or a network connection:

```sh
uv run --directory ops/league-desk python -m league_desk serve --no-collector
```

An empty cache shows the empty page. League, range (24h/7d/30d/all), cached
Coworld version and rating-band player selections are kept in the URL; browser
Back/Forward restores them. Historical controls do not change the current Now
strip or memberships. Daily costs use Pacific dates touched by the range, across all Coworld versions.
Models in use retains a fixed seven-day league game-creation cohort;
standings model cells and seat spend intersect that cohort with range/version. A version-filtered rating is an observed cumulative rating, not a rebuilt
rating for that version alone.

The browser swaps panel interiors every 60 seconds, preserving scroll, focus,
expanded disclosures and table scroll. Unchanged charts keep their SVG; changed
charts or widths are redrawn with Plot. Pause is per tab and survives reload;
hidden tabs stop requests and refresh on becoming visible unless paused. Ages
continue to advance, including while paused, and expired panel sources turn
terracotta. A failed fragment fetch keeps the previous contents and reports failure.

**Refresh** sends a same-origin local `POST /refresh`, coalescing a SQLite signal
for the collector. The collector checks signals each second between polls. Its
current bounded pass finishes first. Fast groups poll again; failed-source retry
deadlines, shared rate limits and the fifteen-minute scan floor still apply. Bounded
history/detail queues continue on their own due times. The page immediately reads
the cache, then watches for a changed fetch generation for up to one minute; this
confirms a cache update, not completion of every remote source. A paused tab can
still request and watch a manual refresh. With `--no-collector`, the signal waits
for a collector and the page says no update was observed rather than claiming success.

Each Needs-attention item has **Dismiss**. Dismissed items collapse under a muted
“dismissed · show” disclosure with **Undo**. This changes only the local cache;
restarts and page refreshes preserve it. A model alert returns when its model,
league, affected policy-version set or latest Pacific failure day changes. Provider
and attempt alerts remain separate. Mixed-version alerts track the observed
Coworld-version set plus canonical associations recorded with ratings; stale-source
alerts track source names. Stalled-round and refused-check alerts track the latest
listed round, so a dismissal holds until a new round starts. Other alerts track
their displayed facts. Changing counts alone does not revive a model alert on the
same day for the same affected policies. Dismissal does not clear panel errors.

To collect once, or run the collector in a separate terminal:

```sh
uv run --directory ops/league-desk python -m league_desk collect --once
uv run --directory ops/league-desk python -m league_desk collect
```

`--once` respects persisted due times and rate-limit delays; it does not force
another poll. It exits nonzero if a cached source has a collection error. The
continuous collector retries failures and keeps last good data. A second collector
exits with a short lock error. Stop the foreground process with Ctrl-C.

If login is missing, sign in using the project environment:

```sh
uv run --directory ops/league-desk softmax login --server https://softmax.com/api
```

Use James's **User** account, not a player identity. The collector already requests
elevated access; denied access is shown as a source error. It never prints an API
response or credential. The current coworld release pins softmax-cli exactly;
this project uses the compatible pair declared in pyproject.toml. The repository
root's CLI pins and lockfile are independent.

## What the page means

- **Latest listed round** comes from a bounded one-row round listing. It is not
  a full history; skipped/finished rows are shown with their actual status.
- **Next round** displays the collected interval; an exact next slot and due time
  remain unavailable. Latest-round game counts come from its cached episode listing.
- **Budget today** uses the API's spend, projection, limit and reset timestamp;
  it counts tournament spending only. It does not assume reset at local midnight.
- **Credit pool** is the league's own funding, from `owner-status`: the balance in
  credits (and dollars at 10 credits per dollar) and today's grants, play charges and
  reward payouts. The platform refills it once per Pacific day from the daily budget in
  effect then, and starts a round only if the pool and the budget can both cover it, so
  raising the budget does not add credits until the next refill. Polled every five
  minutes; stale after ten.
- **Coworld** means the current canonical version discovered through the game
  record. Its observation time is not the release time, and does not establish
  which version a version-locked league or an older running game uses.
- **Policies** counts active competing memberships and every submission listed
  in the last 24 hours (all versions). It goes stale after ten minutes.
- **Last 24 h** counts observed completed/failed episodes by completion time and
  shows round/episode coverage. These are retained-listing counts, not proof of
  all games ever requested. Retry attempts remain unknown.
- **Needs attention** checks actual/projected budget overruns, an empty credit pool,
  a refused round budget check (the platform's latest admission check, naming the
  daily budget or the credit pool), no new round for two hours (or two round
  intervals, if longer: 48 hours for the daily gunboat league), source freshness,
  multiple observed game versions, and verified platform failure streaks. A streak
  must match the current active competing policy; its limit comes from that
  division's settings. Model-error checks use per-league provider and attempt failure rates; actual seat
  rejection counts come from SQL. Current-cap comparisons are labelled references.
  The meter is navy
  unless actual spend or projection exceeds the budget, when it is terracotta.
- A failed source retains its last successful values. Age uses the older of
  successful fetch time and source `as_of` when supplied. Failed or over-two-minute
  health data is marked in terracotta. Competition data goes stale after two
  five-minute cadences; old terminal episode listings after two daily cadences.
  The masthead includes all panel ages and missing/stale counts, and uses minutes
  past 120 seconds. Panels show a short source line with the age of their newest
  data (so a refreshed panel reads as refreshed); a stale flag still appears if any
  input is overdue. Coverage and a source table appear in View values, one row per
  source name: per-game sources are counted (e.g. "detail ×124"), and the row shows
  the member closest to its stale threshold. The Now completion cell puts its longer coverage in a
  separate disclosure. Missing coverage alone does not turn it red.
  Competition panels have a five-minute refresh contract even when a faster round
  source contributes; stale means older than 600 seconds, not 523. Round-duration
  data retains its minute cadence. Failures always mark the panel stale.
  Slow panels use a 30-minute stale threshold, retaining old seat/query timestamps.
  Per-seat spend rotates through eligible games 50 at a time, one batch per
  15-minute pass, so its threshold is two full rotations.
  Immutable request overrides use the newest pass age and selected-request inspection
  coverage instead; old inspected chunks do not expire. Missing inspections remain visible.
  Finished game details follow their daily schedule (stale after two intervals);
  a detail's schedule follows the game state it just fetched.
  Request lists use their version rotation interval times the visits a full walk
  needs (200 rows per visit), while the canonical list stays
  strict at ten minutes, including on slow panels. Errors always remain visible.
- All display dates use America/Los_Angeles with PDT/PST, including API reset times.

## Competition and game measures

Game panels default to the last seven days, all versions; completed-game measures
use completion time. Unfinished seat-game costs use game creation time. All means retained history, not proof of complete platform
history. Range filters use request/submission creation, game completion, and rating
observation times. Round metrics include unfinished rounds and whole matching
rounds; a version match does not isolate a mixed-version round. Memberships and standings are current, and rating history covers
all locally observed updates. Each panel has a reading generated from the same
values as its chart and expandable table. Missing source data and incomplete scans
remain visible even when some values are available.

- Ratings belong to players within divisions, not policy versions. Intervals use
  μ ± 3σ on a shared, unclipped scale; MMR is the platform rating. They remain
  cumulative across versions. Canonical observations are not release timestamps.
- Each rating view is bracketed by summary-generation reads, and all views by
  commissioner-state generation reads. Racing reads retry once, then retain the
  previous snapshot. History starts at first collection, inserts only changed
  observations. Missed polls and multi-round jumps break delta-comparison segments;
  decreases in rounds played also break plotted lines. Resets without an observable decrease are not proven.
- A 24-hour rating delta needs a baseline within ten minutes of the requested
  baseline time in the same uninterrupted segment; the actual time is displayed.
  Missing baselines stay unknown. Last-20 observed points appear as table sparklines, beside interval cells on one
  shared unclipped scale; these are observations, not invented rounds. Two observed points are connected across polling gaps;
  this interpolation does not reconstruct missing rounds. Resets still break lines. The
  first-run note remains while fewer than six observations exist. The MMR chart
  labels the top three, greys the rest, and shows the pointed-at or selected
  player's interval. Small multiples share time and rating scales; thin lines
  show mu, heavy solid lines MMR, and labels show the latest half-width. Bands span
  observed intervals and break at missing sigma/mu; the panel reports missing intervals.
- Submissions count distinct IDs by Pacific creation day. Prior-week comparisons
  require exhaustion of the API listing. This does not recover deleted history;
  partial rolling-window days and incomplete scans are labelled.
- Seat exposure includes fillers. Eligible zero-game rows require a completed
  round, its recorded entrant roster and a complete episode listing. The scheduler
  target is labelled current, never applied retroactively. A compact visible table
  summarizes membership, filler seats, waiting and median games per player/round. Submission waiting
  means no game observed for that policy in the window, not proof it never played.
- Round duration is completed minus created (upstream started may be null).
  Skips are excluded and unfinished rounds are censored. Historical interval
  comparisons use settings observed before creation; earlier intervals are unknown.
  Duration axes start at zero; the labelled current interval line is a reference,
  not a claim about the settings of older rounds.
- Game duration is running to completed, grouped by completion day/version. Median
  and p90 use linear interpolation. Failures stay separate in throughput; public
  results supply outcome/end reason and draw survivor counts where available. Version differences are associations, not causal claims.
- Scores join by seat position, never array order. Mean score averages multiple
  owned non-filler seats once per player/game; all owned scores must be present.
  The comparison reference is exactly 1/7. Missing scores never become zero.
- Head-to-head compares each unordered player pair once per completed scored game.
  Ties stay in the denominator and are shown in the table; reverse cells share n.
  Fewer than five distinct shared games produces a dashed, uncoloured cell.
  Blue/gold carries the comparison; eligible cells show their ahead share in
  contrasting ink. Terracotta is reserved for status. Time axes shorter than two
  days show Pacific time of day; longer domains show dates.

## Spending and experience-request measures

- Daily costs come from `usage_records`, scoped by league, source and Pacific
  bucket day. League-round compute and estimated LLM are stacked against recorded
  budget references; experience-request spend appears in a separate daily series.
  Only requests attributed to the league are included. Lobby is excluded, matching
  the API; persistent costs, if present, remain in reconciliation but not these
  two-source charts. Daily accounting has no reliable Coworld-version dimension.
  The range selects Pacific dates touched by the interval, not exact clock hours;
  the first/last retained dates may be partial.
- Every slow poll replaces the entire last-30-day accounting snapshot, including
  the 48-hour correction window. Today and the previous two days are provisional.
  Each daily row also carries its exact rolling-seven-day contribution, so the
  partial boundary day is not overcounted. Compute and LLM are compared separately
  per source against `/admin/costs/leagues`; differences above $0.01 are visible
  caveats. The API and SQL have separate fetch times and may straddle ingestion.
- Budget references begin when the desk observes them. The latest recorded limit
  on each Pacific day is shown; missing days stay unknown. This is not historical
  budget reconstruction and does not assume the budget resets at Pacific midnight.
- Models in use is now league-only, keyed by episode/slot, policy-version and
  player IDs. A row summarizes one player/policy version, lists resolved provider
  models and requested attempt models separately, and shows both failure rates.
  The chart is a donut of provider billed USD by resolved model across all
  covered seats; the per-policy breakdown stays in View values.
  Labels never join identities; duplicate names cannot merge policies. No-call
  seats remain in the cohort. No observed calls does not prove model-free code.
- The provider and attempt queries cover tournament games created in the last
  seven days. Models in use and its alerts retain that fixed cohort across
  range/version selections; standings models and seat costs intersect it with the
  selection. Provider events start
  one day earlier and end at the query cutoff. Attempts join through indexed
  job-request IDs, including failures/refusals before provider work. Attempt and
  provider failures have separate denominators and must not be added together.
  Requested models describe observed calls, not inspected policy configuration.
  Raw event retention, delayed ingestion and snapshot timing still limit coverage.
  Family-wide model summaries are no longer polled or used for the league alert.
- Per-seat spend sums provider model rows once per episode/slot, including covered
  no-call seats as observed zero. Uncovered seats remain unknown. The dot chart
  retains player rows and the current cap reference; the table lists models.
  Spend-limit rejection counters still come from `episode_llm_usage` independently,
  so they may lag or be unknown. A general refusal is not called a spend-limit denial.
- Standings list each player's active (champion) policy only, and the observed
  provider models of that policy version, joined by its stable ID; "No covered
  seats" means it has no seats in the cohort yet. LLM/game sums
  all owned non-filler seats once per completed covered game; multiple models do
  not multiply the denominator. A game requires every owned seat's coverage.
  These are provider billed totals; daily accounting uses the corrected usage
  ledger and may differ at cohort boundaries. Compute unit costs still use episode
  details. Per-round LLM reconciliation remains outside this phase.
- Experience counts use request creation time and the selected variant ID, across
  all discovered versions. One request may contain multiple episodes. Requester
  labels/emails are private localhost data. Incomplete version/window coverage is
  shown instead of inferring empty history.
- How long games take: a box plot of play minutes (completed minus running) per
  variant, classic press first. Boxes span the middle half, whiskers reach 1.5 ×
  that span, dots are outliers. Queue time is omitted because it is always
  seconds. Request completion (completed minus created) stays in the table as a p90.
  Episode display names are not joined to request variant IDs; the request link
  supplies that grouping. Missing details and unfinished requests are explicit.
- Override frequency reads only `end_year`, `phase_minutes`,
  `retreat_build_minutes`, `press`, `seed`, and `render_maps` scalar values from
  `request_spec.game_config_overrides`. Notes/rosters/arbitrary values are excluded.
  The denominator is inspected requests, not all requests. For a key with more
  than five distinct values (seeds, in practice), values set by fewer than 5% of
  inspected requests (at least 2) fold into one `key = *` row; the chart shows the
  top ten rows. Setting `end_year`
  does not prove a shortened game without a version-specific default comparison.

## Public artifacts and board measures

The collector fetches public `results` and `replay` artifacts for terminal
league games already in the cache, plus public `logs` on Coworld 0.7.12+. It never
fetches seat logs, policy ZIPs or trajectories. Experience-request artifacts are outside this collector.
The separate collector process downloads and parses; page/fragment requests read
only compact derived facts from SQLite. Optional replay `episode.players` is ignored.

- Power scores include every seat, including fillers. Countries map by results
  slot, never by slot-plus-one. Missing/invalid scores quarantine all score facts;
  known API score conflicts, cancellations, episode failures and timeouts exclude
  the game from competitive summaries. Operational end-reason counts retain them.
- Score intervals reuse the optimizer's game-clustered `matchups.stat` calculation.
  The comparison is exactly 1/7, not empirical field par. Fewer than five distinct
  games have no colored mark/cell; zero variance leaves the interval unavailable.
  Policy/power groups use stable policy-version IDs; labels come from current
  memberships or recorded API participants. Old episode snapshots refresh once,
  within the existing bounded episode queue, to obtain those labels.
- Final centers, survival and solos reuse `webdip_episodes.load_episode`, with
  missing scores checked first. Final member counts come from results, not the
  replay's stale Finished board. Private-log taints cannot be assessed here.
- Instrumented panels state “From Coworld 0.7.12; N of M games covered.” The
  denominator is selected terminal games by completion time and Coworld version;
  older versions remain uncovered, never inferred zero. Stable policy-version IDs
  join slot-ordered facts to API seats, including fillers with known policy IDs.
- Score by policy and power, Time to Ready and Seat health show one row per
  player: the champion membership (the version currently competing). Benched
  older versions are omitted. Time to Ready plots one row per policy with a dot
  per phase type; Seat health is one bar chart of unsaved-due-phase rates.
- Time to Ready separates Movement (upstream Diplomacy) and Retreat/build. It
  shows first-Ready shares of the observed deadline minus phase start (first
  Saved stays in the game log but is not shown). Each game's median share contributes once to the across-game median.
  Never-Ready is the share of due seat-phases with a null first-Ready time. Null
  seats have no orders due. Missing deadlines do not supply timing denominators.
  Final Finished-bound and incomplete phases are censored, so adapter time/year
  caps do not create false never-Ready readings. Samples have about 0.25-second
  resolution and can miss brief Ready states. Timing marks require five measured
  games per estimate; smaller samples and counts remain in the table.
- Seat health counts disconnect/reconnect events, including connection takeover.
  A late first connect is after the first observed order phase; never-connected
  seats are separate. It counts games with any uncensored due phase never Saved,
  with a distinct covered-game denominator. API requests sum each policy's seats
  within a game, then take the median; they include browser/archive worker calls
  and are context, not an alert. Cancelled API counts and pod loss are not shown.
  Existing verified failure-streak alerts are unchanged. No new Ready alert is
  enabled. Health chart marks require five games with covered due phases.
- Logs are bounded and parsed entirely in memory. Only `seat_activity` and
  `timing` JSON lines contribute whitelisted derived facts. No raw log is written
  to disk or SQLite. Unknown events/service lines are ignored; duplicate or
  malformed recognized events fail safely. A terminal game whose final lines
  have not arrived retries. A final interrupted timing profile may legitimately
  lack activity; that absence stays unknown.

Each artifact has an independent ledger entry in `sources`, keyed by
`artifact_results`, `artifact_replay` or `artifact_logs` plus episode ID. No schema migration or
parallel ledger is needed: attempt/success/due/error fields already implement the
retry contract. Successful data stores `state=ready`, the normalized JSON hash,
parser revision, relative path and derived facts in one transaction for results/replay.
Logs store only parser revision, ready state and derived facts, without a path or raw bytes.
Existing 0.7.12 results are reparsed locally at parser revision 2; old-version
results and replay stay at revision 1 and do not need another download. Missing data
is pending; HTTP 404 means not available yet, except for a game that ended without
completing (failed, cancelled, timed out): an hour after it ended, a 404 or an incomplete
log is final and stored as `state=absent`, never retried and never counted stale; panels
count those games in their coverage line. Auth, corrupt and transport
failures stay explicit. An error preserves last good facts. Results remain useful
when a replay is missing or corrupt; results-only panels do not inherit replay
errors. Successful immutable artifacts never become stale merely because they age;
panels show per-kind coverage and last ingest, with retry failures still visible.

Downloads use the existing public route/file conventions and optimizer loader,
through the repository-relative `optimizer_tools.py` seam. The broader optimizer
fetcher is intentionally not called: it downloads private seat files and its
`.done` marker means any artifact succeeded. Results/replay stage their standard JSON
filenames separately and promotes it only after successful validation. Gzip is
detected by bytes; HTTP gzip is handled by the transport. Redirects are refused.
A successful artifact is not fetched again; parser revision changes reparse the
hash-verified local file. Errors retry with exponential backoff from a minute to
an hour, respecting the shared persisted rate-limit deadline and Retry-After.
At most four artifact attempts run after normal API groups, stopping between
attempts after twenty seconds. Individual downloads check a thirty-second total
deadline between chunks (bounded HTTP reads may run past it); limits are 64 MiB
of streamed bytes and 128 MiB expanded JSON. Limits live in `config.py`.

### The board

The board section holds the **The board** map and **Score by policy and power**. The map is the
optimizer IDE's Map tab (`player_ade_webdip`: `tools/map_stats.py`, `static/map.js`) drawn on
webDiplomacy's Classic map (`static/map/`, AGPL-3.0, provenance in `static/map/README.md`).
`static/board-map.js` fetches `GET /board-map?league=&range=&version=[&player=]`, which reads
only the cache (`board_map.py`) and returns every phase at once; the phase slider never asks the
server, and choosing a player refetches. The page carries only the URL, so it does not grow.

- Games: terminal games selected by league, range (completion time) and version whose results
  pass the score checks above (no taints, no API score conflict) and whose replay board is parsed.
  Scored games still waiting for a parsed replay are counted as pending, never as zero.
- Phases are movement phases at their start (`S1901`, `A1901`, …); a game counts toward each
  phase it reached. **All phases** pools every phase (contest, held) or uses the final result
  (score, win).
- **Contested provinces**: a province is contested in a phase when units of two or more powers
  try to occupy or keep it: two powers moving in, or one moving in while another power's unit
  stays (holds, supports, convoys, or fails to move). Unopposed moves and one power's own bounces
  do not count; coasts fold into their province. Rate = contested games / games at that phase;
  for All, contested phases / game-phases.
- **Win**: one win per game. Final: the solo winner, otherwise the top final score; tied leaders
  split it (two tied leaders get ½ each). In a phase: the power with the most supply centres at
  its start, ties split. Rate = wins / games; solos are counted separately.
- **Mean score by power**: in a phase, the league score (centres² over the sum of squares) if the
  game had ended at its start; for All, the real final score. ± is the standard error over games.
- **Who holds it**: a supply centre is held by its owner, any other province by the power whose
  non-retreating unit stands there. Each province takes the colour of its most frequent holder,
  paler when that is less often; hovering shows the full split as a pie.
- **Player filter**: a player is a `player_id` across all their policies in the selected league,
  named from the API seats. Score and win then use only the powers that player played, each with
  its own game count; fewer than five games reads "few" and is left unshaded. Contest and held
  use only games the player was in. Filler seats are not the player's games (as in head-to-head).
- Facts: `artifacts.replay_facts` stores, per game, each movement phase's holders and contested
  provinces plus a small province table (about 6 KB a game). Replay parser version 2 added
  them for every Coworld version; existing games reparse from their local files without a
  download, at the normal four artifacts per collector pass.
- The widget keeps its view, phase and player across the 60-second fragment refresh. Its URL
  includes the usable-game count, so it refetches only when more games become usable.

## Tournament planner

The "Tournament planning" section (between standings and matchups) plans the week's final:
a tournament among seven chosen players. Pick a format and its size, pick the players, and
the planner predicts who wins, how sure that is, and how many games it takes to be sure.
Statistics run in the browser, in a Web Worker (`static/tournament-worker.js`), on data from
`GET /tournament-data?league=…&version=…` (cache only, `Cache-Control: no-store`).

**Data.** All cached history for the league (the range control does not apply; the version
control does): completed games with all seven seats scored. Powers join by slot from accepted
results facts (`board_metrics.score_facts`); games whose results are tainted or conflict with
API scores are left out; games without results facts are kept with unknown powers. League
scores in a game always sum to 1 (the panel's "How these numbers were made" shows the largest
observed deviation; on the current cache it is about 1e-16). A chosen player is represented by
their competing (champion) policy version; "Also learn from older policy versions" adds every
version they have played. Filler seats never count as a chosen player. Every other policy
version is its own opponent in the fits, so a strong field and a weak field are not averaged.
Players default to the seven competing champions with the highest MMR.

**Formats.**

- *Full-table rotation.* All seven play every game; only powers change. A cycle is seven games
  laid out as a cyclic Latin square, so each player plays each power exactly once per cycle;
  "reshuffle" draws a new player order each cycle. Size: cycles (games = 7 × cycles). Winner:
  highest total score.
- *Evolutionary.* A Moran-style population starts with C copies of each player. Each game seats
  seven individuals drawn from the population (copies may share a table) at random powers; the
  top scorer's player gains one individual and the bottom scorer's loses one (no change if they
  are the same player). Size: copies C and games T, or run until one player is left. Winner:
  largest share at the end. The planner also reports the games until one player is left.

**Models, side by side.**

- *A, player + power:* score = player strength + power effect + noise, least squares with power
  effects summing to zero. A simulated seat draws its noise from that player's own residuals
  (the pooled residuals if it has fewer than five), is clamped at 0, and the table is rescaled
  to sum to 1.
- *B, head-to-head:* Plackett–Luce finishing orders with worth = player worth × power worth,
  fitted by the MM algorithm (Hunter 2004). Score ties are broken at random in each fit, and
  every player and power gets one virtual win and loss against a worth-1 reference so rarely
  seen entries stay finite. A simulated game draws an order, then hands out the sorted score
  vector of a randomly drawn real game, so solos and draw shapes stay realistic.

A rewards steady score share; B rewards finishing ahead, however narrowly. They can disagree a
lot: a player who often places well but rarely wins ranks higher under A. The panel lists the
players whose win chance differs by 10 points or more, or whose rank moves by 2 or more.

**What the numbers mean.**

- *Win chance and its range:* each refit resamples league games with replacement (Quick 40,
  Standard 100, Thorough 200 refits) and simulates the tournament 100–300 times. The headline is
  the median refit; the range holds the middle 90% of refits. The range is uncertainty about
  strengths, plus a little simulation noise.
- *Final total (or share), 90% range:* the spread of results across simulated tournaments, so
  mostly luck inside one tournament.
- *Winning margin:* first minus second, as a distribution over simulated tournaments.
- *How many games are enough:* the chance the strongest player (by each refit's own strengths)
  finishes first, and the chance the winner's lead is clear — larger than two equally strong
  players would reach 1 time in 20, using the observed seat-score noise. That second line is the
  tournament's statistical power: the chance it gives an answer that is not just luck.
- *Games needed to separate neighbours:* for each adjacent pair in a model's expected order, the
  games needed for the better player to finish ahead with 80/90/95% probability, assuming the
  estimated strengths are right (normal approximation from 3,000 simulated cycles).
- *Cost and time:* games × (mean compute per league game + the chosen policies' mean
  provider-billed LLM USD per seat-game, from `seat_models`, which covers games created in the
  last seven days). A policy without covered seats shows as unknown and counts as $0 in the sum.
  Wall-clock assumes at most 8 games in flight and the median league game duration; evolutionary
  games run one after another because each changes the population.

**Limits.** League games are mixed fields, not this final seven, and policies may play
differently against each other or adapt. Evolutionary clones are hypothetical: no league game
seated two copies of one policy. Older policy versions add data but may not match today's
strength. Fewer than about 50 games for a player gives wide ranges.

The widget keeps its settings across the 60-second refresh; its data URL includes the
scored-game count, so it refetches (keeping the settings) only when more games arrive.

## Storage and privacy

Everything mutable is in this project's ignored `.runtime/`: `desk.sqlite3`,
SQLite WAL/SHM sidecars, `collector.lock`, and the public-only `artifacts/` subtree.
Artifact paths use a neutral `round-0000` bucket with globally unique episode IDs;
league/round attribution comes from API cache rows, not the folder name. The directory has mode 0700 and the
main database 0600. Never commit, publish, serve, or upload this directory. It contains
private operational data, including requester labels/emails.

Experimental live collection must use a separate private scratch directory with
`Store(scratch_directory)`, never the dashboard's shared `.runtime/`. When seeding
from an existing cache, use SQLite's backup API and retain all persisted due times
and rate-limit deadlines. A new directory is not permission to bypass scan floors.
Pass that Store explicitly to the experimental collector and cache-only app;
browser input cannot select a cache directory.

Schema version 2 keeps four tables (dismissals are an additive table):

| Table | Meaning |
|---|---|
| `sources` | Independent artifact ledgers/facts, selected-field snapshots, resumable round/submission scans, per-round episode lists, attempt/success/due times and safe errors |
| `control` | Persisted shared rate-limit deadline and coalesced refresh request |
| `observations` | Changed canonical version, league settings, budget references and consistent ratings, stamped when observed locally |
| `alert_dismissals` | Local alert fingerprints and dismissal times, preserved across restarts |

Source replacement and observation insertion happen in one short transaction.
The database uses WAL and a five-second busy timeout. Page reads use one read-only
transaction for sources and observations. Attribution snapshots reuse sources and observations. Initialization adds the
dismissal table to existing version-2 caches without rewriting their data. Initialization migrates schema 1 by adding the refresh flag without
rewriting snapshots or observations. A newer unsupported schema fails explicitly.
Stop the server/collector and back up the closed cache before upgrading if its
observed history matters; older app versions cannot open schema 2.

The collector allows only these GET paths:

- `/v2/games`, `/v2/leagues` (discovery, without embedded private notes)
- `/v2/coworlds/{coworld_id}` (selected canonical identity only, not its manifest)
- `/v2/budgets`
- `/v2/leagues/{league_id}/settings`
- `/v2/leagues/{league_id}/owner-status` (credit pool fields only)
- `/v2/leagues/health` (recent rounds and the latest round budget check)
- `/v2/rounds` (latest round and resumable history)
- `/v2/rounds/{round_id}/episodes`
- `/v2/league-policy-memberships`, `/v2/league-submissions`
- `/v2/divisions/{division_id}/leaderboards` and `/leaderboard/summary`
- `/v2/leagues/{league_id}/commissioner-state`
- `/v2/coworlds/summaries` (version discovery; no manifest bodies)
- `/v2/experience-requests`, `/v2/experience-requests/{request_id}`
- `/v2/episode-requests` (paginated request episode IDs), `/v2/episode-requests/{episode_id}`
- `/v2/episode-requests/{episode_id}/artifacts/results` , `/artifacts/replay` and `/artifacts/logs` (bounded public-artifact transport)
- `/admin/costs/leagues`, `/admin/llm-coworld-usage`
- `/sql/tables/episode_llm_usage/schema`, `/sql/tables/experience_requests/schema`

The sole platform POST is `/sql/query`, through five named fixed SELECT templates:
`seats`, `overrides`, `daily_spend`, `seat_models`, and `attempts`. IDs are validated
before interpolation; time windows are bounded integer epoch seconds, and model
cursors accept a restricted character set. A caller cannot supply SQL text.
The three attribution templates read only `usage_records`, `llm_provider_events`,
`llm_attempt_events`, `episode_requests`, `episode_request_attempts`,
`episode_request_policies`, `rounds`, `divisions`, `leagues`, `policy_versions`,
`policies` and `players`. Credential/session/account tables are never queried.
Daily aggregates have a hard 500-row bound; a full response is an explicit error.
Seat/model rows keyset-page by episode/slot/model, up to twenty pages.
Attempt aggregates group by policy version/requested model and fail on a full page.
All pages must succeed before replacing a snapshot. The older seat/override
keysets retain their ten-page limit. SQL transport allows 25 seconds so the
platform's 20-second timeout can return an explicit 408. Repeated/unscoped rows or incompatible
schemas fail explicitly. HTTP 408 splits older multi-ID seat/override batches. Attempt queries split
disjoint game-creation windows down to at most one day, merging counts only within
that one successful poll. This cannot double-count games. A terminal timeout or
any failed subquery retains the previous snapshot and the slow retry floor.
Daily/provider timeouts likewise retain previous facts; no partial totals succeed. Integer sums are cast to bigint to preserve integer wire types. No
arbitrary route, SQL or URL comes from the browser.

Health/round scans run every 60 seconds; memberships, submissions and ratings every
five minutes. A newly observed round completion also triggers a rating read unless
the last rating read failed. Up to four due round-episode listings run per league
per poll, oldest successful fetch first. Unfinished rounds refresh each minute,
recent terminal rounds every five minutes, older terminal rounds daily. Separate
source errors retain last good data and do not prevent other eligible polls.

Round and submission history walks use at most two pages of 100 rows per poll,
with cursor/seen-ID state persisted across restarts. They do not assume listing
order. Each completed walk updates visibility, while retaining disappeared rows
with `listed=false` (a reset or hidden round is not a deletion). The next walk
starts at the head; an interrupted or malformed walk restarts after backoff. The
page reports incomplete walks and episode-listing coverage. API retention before
the earliest visible round is unknown. Membership scans and each episode listing
are atomic, bounded at ten pages; larger scans fail explicitly without replacing
last good values. No full-page cutoff is interpreted as completeness.

Version discovery is daily. Two version request walks advance per collector pass;
a due canonical version takes priority. Its cadence is five minutes. Other versions
use the larger of five minutes or one minute per noncanonical version, reserving
one of the two slots for canonical work. The version catalog refreshes daily, or within five minutes
when the canonical version is missing from it. Freshness uses twice that interval.
The walks advance
in 30-day creation windows back to the version's creation time, then refreshing
seven-day windows. Cursors keep their fixed window bounds across retries. Last
recent-window time remains visible while older windows backfill. The detail loop
reads twelve due requests per pass, reserving one for a known unfinished request when
available, and sixty episode details (a detail read takes about 0.3 s, so a pass stays
well inside the minute). League games come first, so a flood of newly listed
experience-request games cannot starve them; then unfetched and unfinished games.
Request episodes use a separate paginated ID listing, not the unpaginated detail's
embedded episode array. Request details can refresh outside the creation window.
Known finished episode details use the daily reconciliation cadence; unfinished or
previously unknown episode details use 15 minutes.

Admin cost scans and SQL groups reserve a 15-minute minimum between attempts
**before** I/O. Errors, crashes and forced polls cannot bypass it. Each seat/override
SQL pass rotates at most 50 known IDs, replacing those rows and preserving per-ID
check times for older chunks. Late usage is re-read; poll totals are never added
together. The page discloses when slow groups are eligible again. Manual refresh cannot move those deadlines forward.

HTTP connect/read timeouts are bounded. The transport supports
object cursors and `X-Next-Cursor` list headers, rejects repeated/incomplete pages,
and preserves successful data when a new scan fails. It disables redirects,
uses login headers in memory, and handles `x-ratelimit-retry-after` itself rather
than allowing the SDK's inner transport to retry before the persisted deadline.
Other transient failures back off up to about 15 minutes. A slow request or
backoff can make a source older than its normal cadence.

The server accepts loopback Host names only, including on static routes, and
serves pages and fragments with `no-store`. Jinja escapes API labels. Local
`POST /refresh` queues collection; `POST /alerts/{fingerprint}?dismissed=true|false`
changes local dismissal state. Both require an exact same-origin Origin header;
neither accepts platform routes, SQL or credentials. No CORS
grants exist. Do not expose it through a tunnel or proxy.
Merriweather and Merriweather Sans Latin subsets are pinned to Fontsource 5.3.0,
with OFL licenses and hashes beside the assets. Other scripts use system fallback;
no CDN is contacted at runtime.
Observable Plot 0.6.17 and D3 7.9.0 are vendored with licenses, source URLs and
SHA-256 hashes in `league_desk/static/vendor/README.md`. Every chart is local. Canonical-version markers say when this desk observed the
canonical version; they do not claim release timestamps or historical game changes.
Marks outside a chart's represented day buckets are omitted. Rating snapshots can
match a selected version through canonical observation or their last round's
observed game association; ratings always remain cumulative.

## Operating and recovering the desk

Keep the foreground `serve` process running to grow the cache and rating history.
Restarting it preserves observations, scan cursors, artifact facts, retry deadlines
and the slow-scan floor. A first run has no historical rating observations; allow
bounded scans to catch up and use each panel's coverage disclosure. A successful
page load does not mean every remote source has finished collecting.

When a scan fails, its last good values remain visible with an error and age.
Leave the collector running for its scheduled retry. Refresh cannot bypass a
rate-limit deadline, failed-source backoff or the slow-scan floor. If login/access
fails, check the User login using the command above, then restart the collector.
If the collector lock is held, stop the other collector you own; removing a lock
file while its process is alive can allow two collectors. A stale file alone does
not hold the operating-system lock.

Use `serve --no-collector` for an offline reading session; scripts, charts and
fonts are local. The browser still polls the local server unless paused. Offline
reading preserves cached errors/ages and does not pretend the data is fresh.

Storage has no automatic retention or compaction policy. Raw public artifacts,
selected request facts and rating observations accumulate; both scan catch-up and
page rendering can slow as retained history grows. Monitor `.runtime/` disk use.
For a backup, stop every collector/server using this cache, then copy the entire
`.runtime/` directory to a private location. Restore only while those processes
are stopped, with the same or a compatible newer schema. A fresh cache loses
local rating history permanently unless a backup exists. Do not share backups.

## Files and checks

`league_desk/cli.py` owns process lifecycle; `api.py` owns authenticated requests;
`collector.py` owns source parsers and polling; `store.py`/`schema.sql` own storage;
`competition.py` parses competition and resumes history scans; `metrics.py` builds
the health strip; `competition_metrics.py` and `game_metrics.py` produce metric
objects and fixed readings; `panels.py` joins dependencies and coverage;
`artifacts.py` ingests public artifacts; `instrumentation.py` validates selected
public log/result facts and `instrument_metrics.py` builds the four instrumentation panels; `board_metrics.py` builds
board/end-reason/timing panels; `board_map.py` builds The board map report (also served by `/board-map`);
`tournament.py` assembles the tournament planner's inputs (served by `/tournament-data`), and
`static/tournament.js`/`static/tournament-worker.js` hold its page widget and statistics; `optimizer_tools.py` imports the existing shared
loader, normalizers and statistics without invoking their CLI/downloaders.
`spending.py` collects cost/request/SQL groups; `attribution.py` validates league
accounting/provider/attempt snapshots and records budget references;
`alerts.py` creates fact-based fingerprints; `attribution_metrics.py` reconciles costs and builds attributed panels; `sql.py` owns fixed SELECTs,
`spend_metrics.py` computes those panels, and `freshness.py` defines their age rules;
`selection.py` defines cached filter choices; `server.py`, `templates/desk.html`
and `templates/fragments.html` render the page. `static/refresh.js` owns browser
refresh and navigation, `static/charts.js` owns Plot marks, and `static/desk.css`
owns presentation. `config.py`
contains cadences and freshness thresholds. `dates.py` handles Pacific dates.

From the repository root:

```sh
uv run --directory ops/league-desk --locked python -m unittest discover -s tests -v
uv run --directory ops/league-desk --locked ruff check league_desk tests
uv run --locked python -m unittest tools.test_ci_scope -v
node ops/league-desk/tests/tournament_check.mjs   # tournament planner statistics (Latin square, fits, power)
```

Tests use invented fixtures, temporary caches, fake clocks/transports and
in-process TestClient. Network transports are denied in the test base class.
The always-run CI test job runs this project's tests and lint. `ops/` is not an
image input and needs no extra image-scope rule. This application is not copied
by `optimizer/install.sh` and does not change the game runtime or public protocol.

## Browser acceptance with invented data

Use the root project's existing Playwright development dependency, not a global
install. Start the network-denied fixture server in a separate terminal:

```sh
uv run --directory ops/league-desk --locked python tests/browser_fixture.py
```

Then run from the root (install Chromium once if needed):

```sh
uv run --locked playwright install chromium
uv run --locked python ops/league-desk/tests/browser_check.py
```

Stop the fixture with Ctrl-C. It uses a temporary cache on port 8661, never the
real runtime. The check covers local assets, lines/bands/cells, responsive layout,
dismiss/undo, fragment swapping, scroll/disclosures, pause, simulated visibility events, history
navigation, delayed responses and failed refreshes. Browser time is controlled;
this is distinct from the live sustained-collector acceptance check.

Implementation follows [Plot pointer input events](https://observablehq.com/plot/interactions/pointer)
and the [browser visibility lifecycle](https://developer.mozilla.org/en-US/docs/Web/API/Page_Visibility_API).
The accepted small synchronous app and native browser APIs remain sufficient; no
new dashboard or client framework dependency is needed.
