# The League Desk

A local, read-only operations page for the webDiplomacy leagues. The collector
uses your existing Softmax User login with elevated privileges and saves selected
fields to SQLite. The page reads that cache, never the platform.

**P5 API and public-artifact page:** current memberships, cumulative ratings and
local rating history, submissions, round/game timing, exposure, throughput and
player head-to-head are available alongside the health strip. Charts use local
Observable Plot and D3 bundles. League-attributed source costs, family-wide model
usage, SQL seat estimates, compute unit costs and experience-request history are
available with explicit scope/coverage. Public results and replay facts provide power/policy scores, province contests,
end reasons and observed phase timings. Tournament daily breakdown and game
instrumentation remain unavailable. There is no rating backfill. Range/version filters, local house fonts, rating
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
strip or memberships. Native-week cost/model panels explicitly keep their original
scope. A version-filtered rating is an observed cumulative rating, not a rebuilt
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
- **Coworld** means the current canonical version discovered through the game
  record. Its observation time is not the release time, and does not establish
  which version a version-locked league or an older running game uses.
- **Last 24 h** counts observed completed/failed episodes by completion time and
  shows round/episode coverage. These are retained-listing counts, not proof of
  all games ever requested. Retry attempts remain unknown.
- **Needs attention** checks actual/projected budget overruns, source freshness,
  multiple observed game versions, and verified platform failure streaks. A streak
  must match the current active competing policy; its limit comes from that
  division's settings. Model-error checks use family-wide usage; actual seat
  rejection counts come from SQL. Current-cap comparisons are labelled references.
  The meter is navy
  unless actual spend or projection exceeds the budget, when it is terracotta.
- A failed source retains its last successful values. Age uses the older of
  successful fetch time and source `as_of` when supplied. Failed or over-two-minute
  health data is marked in terracotta. Competition data goes stale after two
  five-minute cadences; old terminal episode listings after two daily cadences.
  The masthead includes all panel ages and missing/stale counts, and uses minutes
  past 120 seconds. Panels show a short source/age line; coverage and a source/age/row-count table
  appear in View values. The Now completion cell puts its longer coverage in a
  separate disclosure. Missing coverage alone does not turn it red.
  Competition panels have a five-minute refresh contract even when a faster round
  source contributes; stale means older than 600 seconds, not 523. Round-duration
  data retains its minute cadence. Failures always mark the panel stale.
  Slow panels use a 30-minute stale threshold, with older chunk/query timestamps
  retained; refreshing one chunk cannot conceal older cached seat/override rows.
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
- Coarse timing uses one fully timestamped completed game nearest the median total:
  created→dispatched, dispatched→running, running→completed. It never adds component
  medians from different games. Detailed lifecycle and phase timing remains absent.
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

- League-versus-experience costs come from a single league-scoped API response,
  split by source with friendly labels and navy bars. The period is the API's native week, all versions; requests
  without this league attribution are outside that comparison. Combined totals
  must reconcile to compute plus estimated LLM before being cached.
- Tournament daily cost history stays explicitly unavailable: the family-wide
  daily route mixes tournament and experience spending. It cannot be compared
  with one league's budget. The Now strip continues to show the actual budget API.
- Model usage is **family-wide**, across both leagues, requests and versions.
  It is observed usage, not configured model identity. Policy/player label counts
  are not stable identities; no name-based join assigns models to standings. Full
  model names appear above source-stacked bars on a shared USD scale, ordered by
  total spend, with one USD axis at the bottom; the values table includes calls,
  errors and failure rate.
- Per-seat estimated cost sums the SQL player-role facts across hour/provider rows
  at episode/slot grain. Their database key is episode/slot/hour/source-system.
  The existing estimate and actual rejection counter remain distinct. Missing
  seats remain unknown, even after a successful query. Current cap is a reference;
  it does not establish an old game's cap or a billed amount. One dot represents
  one seat-game, player rows sort by median spend, and the current cap is labelled.
- Standings LLM/game averages estimated totals for completed games with usage for
  every owned non-filler seat, showing its covered-game denominator. Compute
  unit cost comes from episode details; round means need all listed games covered
  and completed in the selected window. Per-round LLM is not reconciled.
- Experience counts use request creation time and the selected variant ID, across
  all discovered versions. One request may contain multiple episodes. Requester
  labels/emails are private localhost data. Incomplete version/window coverage is
  shown instead of inferring empty history.
- Request completion is completed minus created. Episode queue is dispatched minus
  created; play is completed minus running. These samples have separate counts.
  Episode display names are not joined to request variant IDs; the request link
  supplies that grouping. Missing details and unfinished requests are explicit.
- Override frequency reads only `end_year`, `phase_minutes`,
  `retreat_build_minutes`, `press`, `seed`, and `render_maps` scalar values from
  `request_spec.game_config_overrides`. Notes/rosters/arbitrary values are excluded.
  The denominator is inspected requests, not all requests. Setting `end_year`
  does not prove a shortened game without a version-specific default comparison.

## Public artifacts and board measures

The collector fetches only public `results` and `replay` artifacts for terminal
league games already in the cache. It never fetches game logs, seat logs, policy
ZIPs or trajectories. Experience-request artifacts are outside this collector.
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
- Contests count failed incoming Move orders plus observed owner changes in
  known consecutive history boards. The optimizer's movement/territory helpers
  fold coast children into provinces. First boards establish a baseline; missing
  ownership, duplicate phase entries and the stale Finished board add no changes.
  The denominator is usable, untainted games with known board comparisons. Final
  autumn changes may be absent. The table includes zero provinces; the chart shows
  the six highest and three lowest observed rates. These are counts, not strategy
  or causal findings.
- Phase durations use results `transitions.elapsed_seconds`, collapsing adjacent
  processing-state changes within a turn/phase. Only phases with a following
  transition have durations; pauses remain included. Grouping uses observed replay
  phase configuration when available, otherwise an explicit unknown limit.
  Movement means upstream Diplomacy. Duration below config does not establish
  early finish: the replay keeps a phase's last snapshot, not its initial deadline.
  Ready times, per-phase adjudication and seat health remain unavailable.
- Game-level gamemaster maximums, when present, appear as labelled context beside
  the coarse API timing; they overlap play time and are never added to its stack.

Each artifact has an independent ledger entry in `sources`, keyed by
`artifact_results` or `artifact_replay` plus episode ID. No schema migration or
parallel ledger is needed: attempt/success/due/error fields already implement the
retry contract. Successful data stores `state=ready`, the normalized JSON hash,
parser revision, relative path and derived facts in one transaction. Missing data
is pending; HTTP 404 means not available yet, while auth, corrupt and transport
failures stay explicit. An error preserves last good facts. Results remain useful
when a replay is missing or corrupt; results-only panels do not inherit replay
errors. Successful immutable artifacts never become stale merely because they age;
panels show per-kind coverage and last ingest, with retry failures still visible.

Downloads use the existing public route/file conventions and optimizer loader,
through the repository-relative `optimizer_tools.py` seam. The broader optimizer
fetcher is intentionally not called: it downloads private seat files and its
`.done` marker means any artifact succeeded. Each kind stages its standard JSON
filename separately and promotes it only after successful validation. Gzip is
detected by bytes; HTTP gzip is handled by the transport. Redirects are refused.
A successful artifact is not fetched again; parser revision changes reparse the
hash-verified local file. Errors retry with exponential backoff from a minute to
an hour, respecting the shared persisted rate-limit deadline and Retry-After.
At most four artifact attempts run after normal API groups, stopping between
attempts after twenty seconds. Individual downloads check a thirty-second total
deadline between chunks (bounded HTTP reads may run past it); limits are 64 MiB
of streamed bytes and 128 MiB expanded JSON. Limits live in `config.py`.

## Storage and privacy

Everything mutable is in this project's ignored `.runtime/`: `desk.sqlite3`,
SQLite WAL/SHM sidecars, `collector.lock`, and the public-only `artifacts/` subtree.
Artifact paths use a neutral `round-0000` bucket with globally unique episode IDs;
league/round attribution comes from API cache rows, not the folder name. The directory has mode 0700 and the
main database 0600. Never commit, publish, serve, or upload this directory. It contains
private operational data, including requester labels/emails.

Schema version 2 keeps three tables:

| Table | Meaning |
|---|---|
| `sources` | Independent artifact ledgers/facts, selected-field snapshots, resumable round/submission scans, per-round episode lists, attempt/success/due times and safe errors |
| `control` | Persisted shared rate-limit deadline and coalesced refresh request |
| `observations` | Changed canonical version, league settings and consistent ratings, stamped when observed locally |

Source replacement and observation insertion happen in one short transaction.
The database uses WAL and a five-second busy timeout. Page reads use one read-only
transaction for sources and observations. The new groups reuse
these tables rather than adding unused normalized entities; the schema version
is now 2. Initialization migrates schema 1 by adding the refresh flag without
rewriting snapshots or observations. A newer unsupported schema fails explicitly.
Stop the server/collector and back up the closed cache before upgrading if its
observed history matters; older app versions cannot open schema 2.

The collector allows only these GET paths:

- `/v2/games`, `/v2/leagues` (discovery, without embedded private notes)
- `/v2/coworlds/{coworld_id}` (selected canonical identity only, not its manifest)
- `/v2/budgets`
- `/v2/leagues/{league_id}/settings`
- `/v2/leagues/health`
- `/v2/rounds` (latest round and resumable history)
- `/v2/rounds/{round_id}/episodes`
- `/v2/league-policy-memberships`, `/v2/league-submissions`
- `/v2/divisions/{division_id}/leaderboards` and `/leaderboard/summary`
- `/v2/leagues/{league_id}/commissioner-state`
- `/v2/coworlds/summaries` (version discovery; no manifest bodies)
- `/v2/experience-requests`, `/v2/experience-requests/{request_id}`
- `/v2/episode-requests` (paginated request episode IDs), `/v2/episode-requests/{episode_id}`
- `/v2/episode-requests/{episode_id}/artifacts/results` and `/artifacts/replay` (bounded binary transport)
- `/admin/costs/leagues`, `/admin/llm-coworld-usage`
- `/sql/tables/episode_llm_usage/schema`, `/sql/tables/experience_requests/schema`

The sole platform POST is `/sql/query`, through two named fixed SELECT templates:
seat aggregates and allowlisted request overrides. IDs are validated as UUIDs
before interpolation; a caller cannot supply SQL text. Keyset pages use LIMIT 500
and continue after an exact full page. Repeated/unscoped rows or incompatible
schemas fail explicitly. HTTP 408 splits the ID batch; a single-ID timeout remains
an error. Integer sums are cast to bigint to preserve integer wire types. No
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

Version discovery is daily. Two version request walks advance per collector pass,
in 30-day creation windows back to the version's creation time, then refreshing
seven-day windows. Cursors keep their fixed window bounds across retries. Last
recent-window time remains visible while older windows backfill. The detail loop
reads two due requests per pass, reserving one for a known unfinished request when
available, and eight episode details; large caches therefore need bounded catch-up.
Request episodes use a separate paginated ID listing, not the unpaginated detail's
embedded episode array. Request details can refresh outside the creation window.

Admin cost/model scans and SQL groups reserve a 15-minute minimum between attempts
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
serves pages and fragments with `no-store`. Jinja escapes API labels. The sole
browser POST requires an exact same-origin Origin header and only queues local
collection; it accepts no route, SQL, credentials or scope parameters. No CORS
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

## Files and checks

`league_desk/cli.py` owns process lifecycle; `api.py` owns authenticated requests;
`collector.py` owns source parsers and polling; `store.py`/`schema.sql` own storage;
`competition.py` parses competition and resumes history scans; `metrics.py` builds
the health strip; `competition_metrics.py` and `game_metrics.py` produce metric
objects and fixed readings; `panels.py` joins dependencies and coverage;
`artifacts.py` ingests public artifacts and derives facts; `board_metrics.py` builds
board/end-reason/timing panels; `optimizer_tools.py` imports the existing shared
loader, normalizers and statistics without invoking their CLI/downloaders.
`spending.py` collects cost/request/SQL groups, `sql.py` owns fixed SELECTs,
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
fragment swapping, scroll/disclosures, pause, simulated visibility events, history
navigation, delayed responses and failed refreshes. Browser time is controlled;
this is distinct from the live sustained-collector acceptance check.

Implementation follows [Plot pointer input events](https://observablehq.com/plot/interactions/pointer)
and the [browser visibility lifecycle](https://developer.mozilla.org/en-US/docs/Web/API/Page_Visibility_API).
The accepted small synchronous app and native browser APIs remain sufficient; no
new dashboard or client framework dependency is needed.
