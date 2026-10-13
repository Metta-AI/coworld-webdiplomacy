# The League Desk

A local, read-only operations page for the webDiplomacy leagues. The collector
uses your existing Softmax User login with elevated privileges and saves selected
fields to SQLite. The page reads that cache, never the platform.

**P3 competition, spending and requests:** current memberships, cumulative ratings and
local rating history, submissions, round/game timing, exposure, throughput and
player head-to-head are available alongside the health strip. Charts use local
Observable Plot and D3 bundles. League-attributed source costs, family-wide model
usage, SQL seat estimates, compute unit costs and experience-request history are
available with explicit scope/coverage. Tournament daily breakdown and artifacts
remain unavailable. There is no rating backfill. Full presentation, filters and
automatic refresh are a later phase.

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

An empty cache shows the empty page. The page has a League selector and a **View cache**
button, which reloads the page without polling the platform. It has no automatic
browser refresh, range/version filters, or manual collection button yet. Ages
are measured at page load. The collector runs independently of the browser.

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
  past 120 seconds. Panels show a short source/age line; coverage and component
  freshness appear in View values. Missing coverage alone does not turn it red.
  Competition panels have a five-minute refresh contract even when a faster round
  source contributes; stale means older than 600 seconds, not 523. Round-duration
  data retains its minute cadence. Failures always mark the panel stale.
  Slow panels use a 30-minute stale threshold, with older chunk/query timestamps
  retained; refreshing one chunk cannot conceal older cached seat/override rows.
- All display dates use America/Los_Angeles with PDT/PST, including API reset times.

## Competition and game measures

Game panels use the last seven days, all versions; completed-game measures use
completion time. Memberships and standings are current, and rating history covers
all locally observed updates. Each panel has a reading generated from the same
values as its chart and expandable table. Missing source data and incomplete scans
remain visible even when some values are available.

- Ratings belong to players within divisions, not policy versions. Intervals use
  μ ± 3σ on a shared, unclipped scale; MMR is the platform rating. They remain
  cumulative across versions. Canonical observations are not release timestamps.
- Each rating view is bracketed by summary-generation reads, and all views by
  commissioner-state generation reads. Racing reads retry once, then retain the
  previous snapshot. History starts at first collection, inserts only changed
  observations, and breaks lines on missed polls, multi-round jumps or observed
  decreases in rounds played. Resets without an observable decrease are not proven.
- A 24-hour rating delta needs a baseline within ten minutes of the requested
  baseline time in the same uninterrupted segment; the actual time is displayed.
  Missing baselines stay unknown. Last-20 observed points are prepared for the
  later table-sparkline presentation; there is no invented round-by-round history.
- Submissions count distinct IDs by Pacific creation day. Prior-week comparisons
  require exhaustion of the API listing. This does not recover deleted history;
  partial rolling-window days and incomplete scans are labelled.
- Seat exposure includes fillers. Eligible zero-game rows require a completed
  round, its recorded entrant roster and a complete episode listing. The scheduler
  target is labelled current, never applied retroactively. Submission waiting
  means no game observed for that policy in the window, not proof it never played.
- Round duration is completed minus created (upstream started may be null).
  Skips are excluded and unfinished rounds are censored. Historical interval
  comparisons use settings observed before creation; earlier intervals are unknown.
- Game duration is running to completed, grouped by completion day/version. Median
  and p90 use linear interpolation. Failures stay separate in throughput; end
  reasons await artifacts. Version differences are associations, not causal claims.
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
  split by source. The period is the API's native week, all versions; requests
  without this league attribution are outside that comparison. Combined totals
  must reconcile to compute plus estimated LLM before being cached.
- Tournament daily cost history stays explicitly unavailable: the family-wide
  daily route mixes tournament and experience spending. It cannot be compared
  with one league's budget. The Now strip continues to show the actual budget API.
- Model usage is **family-wide**, across both leagues, requests and versions.
  It is observed usage, not configured model identity. Policy/player label counts
  are not stable identities; no name-based join assigns models to standings.
- Per-seat estimated cost sums the SQL player-role facts across hour/provider rows
  at episode/slot grain. Their database key is episode/slot/hour/source-system.
  The existing estimate and actual rejection counter remain distinct. Missing
  seats remain unknown, even after a successful query. Current cap is a reference;
  it does not establish an old game's cap or a billed amount.
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

## Storage and privacy

Everything mutable is in this project's ignored `.runtime/`: `desk.sqlite3`,
SQLite WAL/SHM sidecars, and `collector.lock`. The directory has mode 0700 and the
main database 0600. Never commit, publish, serve, or upload this directory. It contains
private operational data, including requester labels/emails.

Schema version 1 deliberately has only three tables:

| Table | Meaning |
|---|---|
| `sources` | Selected-field snapshots, resumable round/submission scans, per-round episode lists, attempt/success/due times and safe errors |
| `control` | Persisted shared rate-limit deadline |
| `observations` | Changed canonical version, league settings and consistent ratings, stamped when observed locally |

Source replacement and observation insertion happen in one short transaction.
The database uses WAL and a five-second busy timeout. Page reads use one read-only
transaction for sources and observations. The new groups reuse
these tables rather than adding unused normalized entities; the schema version
and existing P1 cache remain compatible. A newer unsupported schema fails
initialization explicitly; there are no migrations beyond initializing version 1 yet. Back up the closed cache
before changing schema versions if its observed history matters.

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
together. The page discloses when slow groups are eligible again. There is still
no browser-triggered poll until the refresh phase.

HTTP connect/read timeouts are bounded. The transport supports
object cursors and `X-Next-Cursor` list headers, rejects repeated/incomplete pages,
and preserves successful data when a new scan fails. It disables redirects,
uses login headers in memory, and handles `x-ratelimit-retry-after` itself rather
than allowing the SDK's inner transport to retry before the persisted deadline.
Other transient failures back off up to about 15 minutes. A slow request or
backoff can make a source older than its normal cadence.

The server accepts loopback Host names only, including on static routes, and
serves page responses with `no-store`. Jinja escapes API labels. There are no
browser write routes or CORS grants. Do not expose it through a tunnel or proxy.
Fonts currently fall back to locally installed/system fonts; no CDN is contacted.
Observable Plot 0.6.17 and D3 7.9.0 are vendored with licenses, source URLs and
SHA-256 hashes in `league_desk/static/vendor/README.md`. Initial charts are local;
fonts, small multiples, hover selection and refresh arrive in the presentation phase.

## Files and checks

`league_desk/cli.py` owns process lifecycle; `api.py` owns authenticated requests;
`collector.py` owns source parsers and polling; `store.py`/`schema.sql` own storage;
`competition.py` parses competition and resumes history scans; `metrics.py` builds
the health strip; `competition_metrics.py` and `game_metrics.py` produce metric
objects and fixed readings; `panels.py` joins dependencies and coverage;
`spending.py` collects cost/request/SQL groups, `sql.py` owns fixed SELECTs,
`spend_metrics.py` computes those panels, and `freshness.py` defines their age rules;
`server.py`, `templates/desk.html` and `static/desk.css` render the page. `config.py`
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
