# League Desk development

Read [README.md](README.md) for current behavior, commands and data limits. The
accepted design is `../../docs/designs/league-dashboard-2026-10-12.html`; phase
briefs and verdicts are in `../../tmp/collab/`. Do not implement beyond the
currently authorized phase.

- Keep Python synchronous. Only collector code calls the platform; page handlers
  read SQLite only. Use `CoworldApiClient.from_login` with elevated User access.
- Allowlisted GET requests only in P1. Never mutate the platform. Future SQL
  support must accept only fixed, scoped SELECT templates.
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
