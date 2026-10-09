# Version log — <policy name>

Maps every uploaded version of this policy to the one change it carries.
**The row is mandatory before anything else happens after an upload** —
an unlogged version is a hole in the campaign's memory. Honest caveats
("NOT proven better — the A/B was contaminated") are valuable entries.

Validation states: `unvalidated` → `validated` / `refuted` (by a recorded
experiment) → `submitted` (with the decision record appended below the row).

| Version | Policy version id | Uploaded (UTC) | The one change (and its mechanism) | Runtime config | Validation | Notes |
|---|---|---|---|---|---|---|
| v1 | pv_… | YYYY-MM-DD HH:MM | … | … | unvalidated | … |

## Submission decision records

Appended by `submit` when a version enters a league — the evidence that
justified it, the human's recorded go-ahead, and the rollback plan.
