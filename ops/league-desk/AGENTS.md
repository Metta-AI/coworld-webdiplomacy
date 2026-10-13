# League Desk development

Read [README.md](README.md) for current behavior, commands and data limits. The
accepted design is `../../docs/designs/league-dashboard-2026-10-12.html`; phase
briefs and verdicts are in `../../tmp/collab/`. Do not implement beyond the
currently authorized phase.

- Local `POST /refresh` only queues a coalesced signal; `/alerts/{fingerprint}`
  persists dismiss/undo. Both require the exact Origin.
  Page/fragment GETs stay cache-only; slow floors and failure backoff cannot be forced.
- Keep Python synchronous. Only collector code calls the platform; page handlers
  read SQLite only except the two explicit local POST actions. Use `CoworldApiClient.from_login` with elevated User access.
- Allowlisted GETs and fixed, scoped SELECT templates through `POST /sql/query`
  only. Never accept SQL text from a caller or mutate the platform.
- Slow cost/model/SQL attempts reserve their 15-minute floor before network I/O.
  Do not bypass that floor on errors, restarts or manual refreshes.
- Freshness follows per-row episode/detail schedules. Immutable overrides use newest
  pass age plus selected-request inspection coverage, never oldest chunk age. Request
  lists follow the bounded version rotation; canonical walks get priority and retain
  the ten-minute stale threshold. Errors and missed schedules must remain visible.
- SQL seat facts are unique by episode/slot/hour/provider; aggregate once at seat
  grain and replace snapshots. Missing rows are unknown, not zero usage.
- Daily cost SQL is league/source/Pacific-day scoped and replaces its whole 30-day
  snapshot (including 48-hour corrections). Reconcile exact rolling-seven-day
  contributions per source/component against the API; show mismatches above $0.01.
- Provider/attempt SQL uses the league's seven-day game-creation cohort. Join seats
  by episode/slot and player/policy-version IDs, never display labels. Keep provider
  failure and attempt failure/refusal denominators distinct. No observed provider
  calls does not establish model-free policies; raw event retention may be limited.
- Exactly five named SQL templates are allowed. Attribution uses bounded integer
  windows and validated keyset cursors. Full aggregate pages and incomplete walks
  fail explicitly. Attempt 408s split disjoint creation windows, down to one day;
  terminal errors retain last good data and the 15-minute retry floor.
- Daily cost has no version filter; the model panel/alerts use the fixed seven-day
  league cohort. Standings models and seat spend intersect it with range/version.
  Budget lines use recorded daily observations only. Do not infer old budgets.
- Cache selected fields, not raw responses or manifests. Keep credentials,
  requester information, real policy names and operational values out of fixtures,
  docs, logs and commits. Tests use invented fixtures and deny network access.
- Alert dismissals persist in SQLite. Model fingerprints include model, league,
  affected policy versions and latest Pacific failure day; mixed-version and
  stale-source fingerprints use their version/source sets. Never suppress a new fact set.
- Experimental live runs must use an explicit separate scratch Store, retaining
  copied rate limits and due times. Do not write test failures to the shared cache.
- Mutable dashboard data stays in ignored `.runtime/`. No arbitrary cache path or bind host
  from browser input. Jinja autoescape stays enabled; no external runtime assets.
- Match the local unittest style and 120-column E/F/I ruff rules. Run the README
  checks. Add tables and views only when an implemented panel needs them.
- Do not edit shared optimizer tools, install copies or the upstream submodule.
  This project is not part of the optimizer template or game image.
- Keep unknown values distinct from zero. Never infer health from absent logs,
  model-free policies from missing usage, or per-version MMR from cumulative ratings.
- Keep this README current; root README is embedded in the game manifest and does
  not need edits for this dashboard. CI's always-run test job checks this project.

- Public artifacts use independent `artifact_results` / `artifact_replay` / `artifact_logs`
  source ledgers. Only the collector downloads/parses; the server reads compact
  facts. Ready immutable files are not polled again or expired by age.
- Keep the three public artifact routes separate from arbitrary GETs; no redirects, seat
  logs, policy ZIPs or trajectories. Validate/decompress within configured bounds,
  stage before promotion, and retain last good facts on failure.
- `optimizer_tools.py` is the only reuse seam. Check scores before the shared
  loader (it defaults missing scores to zero). Preserve game clustering, the
  five-game color floor and the stale Finished-board exclusion. Do not infer
  Ready/deadline outcomes from replay snapshots or phase config alone.

- Terminal 0.7.12+ game logs are parsed only in memory. Cache selected seat_activity
  and timing facts, never raw logs. Missing final lines retry; interrupted profiles
  may lack activity. Older versions are uncovered, never zero.
- Ready/Saved shares use observed deadline minus phase start, with medians within
  each game before across-game medians. Exclude null seats and final/incomplete
  phases from never-Ready/no-Saved denominators. Five-game chart floor applies.
- Connection events are not pod-loss evidence. API requests include browser and
  archive traffic, and cancelled counts remain unknown. Stage medians are separate,
  not additive; API pod-start boundaries can overlap container initialization.
