# The League Desk

A local, read-only operations page for the webDiplomacy leagues. The collector
uses your existing Softmax User login with elevated privileges and saves selected
fields to SQLite. The page reads that cache, never the platform.

**P1 foundation:** current canonical version, league interval, budget and latest
listed round are available. Every other panel has a named data source and an
explicit empty state. Ratings, full episode history, cost/usage scans, experience
requests and artifact ingest are not implemented yet. There is no rating backfill.

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

An empty cache shows the empty page. P1 has a League selector and a **View cache**
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
- **Next round** displays the collected interval. An exact next slot, due time
  and game counts are unavailable from the current collection.
- **Budget today** uses the API's spend, projection, limit and reset timestamp;
  it counts tournament spending only. It does not assume reset at local midnight.
- **Coworld** means the current canonical version discovered through the game
  record. Its observation time is not the release time, and does not establish
  which version a version-locked league or an older running game uses.
- **Last 24 h** has no game counts yet. The health route's recent round summaries
  cannot establish episode, retry or failure totals.
- **Needs attention** currently checks actual/projected budget overruns and
  source freshness only. Missing model/seat/qualification checks are stated.
- A failed source retains its last successful values. Age uses the older of
  successful fetch time and source `as_of` when supplied. Failed or over-two-minute
  health data is marked in terracotta. The masthead reports missing sources too.
- All display dates use America/Los_Angeles with PDT/PST, including API reset times.

## Storage and privacy

Everything mutable is in this project's ignored `.runtime/`: `desk.sqlite3`,
SQLite WAL/SHM sidecars, and `collector.lock`. The directory has mode 0700 and the
main database 0600. Never commit, publish, serve, or upload this directory. It may
contain private operational data as later collection groups are added.

Schema version 1 deliberately has only three tables:

| Table | Meaning |
|---|---|
| `sources` | Latest selected-field JSON per source/scope, attempt/success/due times, failure count and safe error |
| `control` | Persisted shared rate-limit deadline |
| `observations` | Changed canonical version and league settings, stamped when observed locally |

Source replacement and observation insertion happen in one short transaction.
The database uses WAL and a five-second busy timeout. Page reads use read-only
connections. A newer unsupported schema fails initialization explicitly; there
are no migrations beyond initializing version 1 yet. Back up the closed cache
before changing schema versions if its observed history matters.

The collector allows only these GET paths:

- `/v2/games`, `/v2/leagues` (discovery, without embedded private notes)
- `/v2/coworlds/{coworld_id}` (selected canonical identity only, not its manifest)
- `/v2/budgets`
- `/v2/leagues/{league_id}/settings`
- `/v2/leagues/health`
- `/v2/rounds` (latest listed round per league)

There is no platform POST support in P1. Later SQL enrichment will need a narrow
read-only SELECT interface. No arbitrary route, SQL or URL comes from the browser.

Polls occur no more often than every 60 seconds per source, with bounded HTTP
connect/read timeouts. Discovery follows cursor pages up to a fixed bound;
round collection intentionally reads only its first row. The transport supports
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
Observable Plot, bundled fonts and interactive chart rendering arrive with the
later presentation work, not this foundation.

## Files and checks

`league_desk/cli.py` owns process lifecycle; `api.py` owns authenticated requests;
`collector.py` owns source parsers and polling; `store.py`/`schema.sql` own storage;
`metrics.py` builds the health strip; `panels.py` lists the other empty panels;
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
