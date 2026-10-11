# Version log — castlereagh

Maps every uploaded version of this policy to the one change it carries.
**The row is mandatory before anything else happens after an upload** —
an unlogged version is a hole in the campaign's memory. Honest caveats
("NOT proven better — the A/B was contaminated") are valuable entries.

Validation states: `unvalidated` → `validated` / `refuted` (by a recorded
experiment) → `submitted` (with the decision record appended below the row).

Each upload is one mode (`--policy search|press`); log both modes' uploads as separate rows.

| Version | Policy version id | Uploaded (UTC) | The one change (and its mechanism) | Runtime config | Validation | Notes |
|---|---|---|---|---|---|---|
| v0 | (not uploaded) | — | The starter policy as shipped: the Default search, plus the press harness with its neutral default soul and two reference skills. | `CASTLEREAGH_POLICY=press` (default) or `search` | unvalidated in your field (the golden test pins the search's orders; nothing here was measured against your opponents) | The baseline every later row is compared with. |

## Submission decision records

Appended by `submit` when a version enters a league — the evidence that
justified it, the human's recorded go-ahead, and the rollback plan.
