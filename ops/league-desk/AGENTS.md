# League Desk development

Read [README.md](README.md) for current behavior, commands and data limits. The
accepted design is `../../docs/designs/league-dashboard-2026-10-12.html`; phase
briefs and verdicts are in `../../tmp/collab/`. Do not implement beyond the
currently authorized phase.

- Local `POST /refresh` only queues a coalesced signal and requires the exact Origin.
  Page/fragment GETs stay cache-only; slow floors and failure backoff cannot be forced.
- Keep Python synchronous. Only collector code calls the platform; page handlers
  read SQLite only. Use `CoworldApiClient.from_login` with elevated User access.
- Allowlisted GETs and fixed, scoped SELECT templates through `POST /sql/query`
  only. Never accept SQL text from a caller or mutate the platform.
- Slow cost/model/SQL attempts reserve their 15-minute floor before network I/O.
  Do not bypass that floor on errors, restarts or manual refreshes.
- SQL seat facts are unique by episode/slot/hour/provider; aggregate once at seat
  grain and replace snapshots. Missing rows are unknown, not zero usage.
- Model scans cover the entire family; costs cover league-attributed sources.
  Keep these scope exceptions visible and do not join identity by display label.
- Cache selected fields, not raw responses or manifests. Keep credentials,
  requester information, real policy names and operational values out of fixtures,
  docs, logs and commits. Tests use invented fixtures and deny network access.
- Mutable data stays in ignored `.runtime/`. No arbitrary cache path or bind host
  from browser input. Jinja autoescape stays enabled; no external runtime assets.
- Match the local unittest style and 120-column E/F/I ruff rules. Run the README
  checks. Add tables and views only when an implemented panel needs them.
- Do not edit shared optimizer tools, install copies or the upstream submodule.
  This project is not part of the optimizer template or game image.
- Keep unknown values distinct from zero. Never infer health from absent logs,
  model-free policies from missing usage, or per-version MMR from cumulative ratings.
- Keep this README current; root README is embedded in the game manifest and does
  not need edits for this dashboard. CI's always-run test job checks this project.

- P5 public artifacts use independent `artifact_results` / `artifact_replay`
  source ledgers. Only the collector downloads/parses; the server reads compact
  facts. Ready immutable files are not polled again or expired by age.
- Keep the two artifact routes separate from arbitrary GETs; no redirects, seat
  logs, policy ZIPs or trajectories. Validate/decompress within configured bounds,
  stage before promotion, and retain last good facts on failure.
- `optimizer_tools.py` is the only reuse seam. Check scores before the shared
  loader (it defaults missing scores to zero). Preserve game clustering, the
  five-game color floor and the stale Finished-board exclusion. Do not infer
  Ready/deadline outcomes from replay snapshots or phase config alone.
