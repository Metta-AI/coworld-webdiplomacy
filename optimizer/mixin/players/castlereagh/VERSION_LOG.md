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
| v0 | (not uploaded) | — | Adapted from webdiplomacy_lab Castlereagh at lab commit `1c2d81fa`. See "v0 details" below. | `CASTLEREAGH_POLICY=search` (default) or `press`; base coworld-webdiplomacy `b4aca731` | unvalidated (golden 334/334 bit-identical to the lab's Kissinger/level-0 search; local episodes only) | Press layer is an experiment framework, not a proven gain: in the lab, press arms scored 0.124–0.126 per seat vs silent Kissinger 0.172–0.176 in the same field. |

## v0 details

**Kept (search core, behaviour unchanged):** SearchBot with DumbBot seeds, single/pair/convoy
joint alternatives and coordinate ascent against 16 sampled opponent plans; the level-1
opponent model and the competent-opponent belief; projected-centre evaluation with risk and
the (off) implicit-diplomacy term; the fast adjudicator and the convoy approximation;
DumbBot for seeds, retreats, builds and opponent samples; the golden test (golden.py +
golden.json, 334 decisions). Defaults = the lab's `kissinger` personality.

**Changed:**
- Nim adjudicator dropped; `fastadj.adjudicate` runs the lab's pure-Python reference
  `Adjudicator`. Golden stays 334/334: no decision changed.
- `diplomacy` package dropped. The default path never used it (convoy approximation on);
  its only default-path role was name lookup, now a static Classic table in `dipmap.py`.
  `SEARCH_CONVOY_APPROX=0` / `SEARCH_FAST_ADJ=0` and the package fallback are gone.
- `players.api` / `players.legal_orders` vendored (unchanged) so the package and its tests
  run without a coworld checkout.
- Modes are `CASTLEREAGH_POLICY=search|press`; the personality roster is gone.
- Press layer rebuilt as four modules (service, floor, driver, knowledge). One event-driven
  wake (phase start + every burst of new press, 5 s debounce, ≤ 20 wakes, lock 12 s before the
  deadline) replaces open/negotiate/commit wakes. Knowledge is notes + raw press log +
  referee facts from adjudicated orders; profiles, claims ledger and plan.md are gone.
  Prompts say "Default" instead of "Kissinger"; the briefing reads `WEBDIP_END_YEAR` and
  `WEBDIP_SCORING`. Per-model sidecar quirks moved from personalities to `config.MODEL_QUIRKS`.
  Limits raised (30 calls / 120 s per wake, 6000 max tokens).
- In press mode the floor uses the gunboat RNG key, so press-off play is identical to `search`.

**Dropped:** Nash, the learned value function (`valuefn.py`, `value_weights.json`),
lookahead/rollouts and build search, restarts, triples, level-2 opponents, mixed selection,
evolution/arena/field tooling, profile and check scripts, 15 filler personalities, the
other souls and the opponent-profiles skill.

## Submission decision records

Appended by `submit` when a version enters a league — the evidence that
justified it, the human's recorded go-ahead, and the rollback plan.
