"""Shared test helpers: fixture paths and a writer for small synthetic episodes."""

import json
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def write_episode(ep: Path, scores, countries, centers, outcome="drawn", seating=None, logs=None, status=None):
    """Write a minimal local-layout episode (results.json, optional seating, seat logs, episode row).

    `centers[slot]` is that slot's final supply-centre count; `logs[slot]` a list of event dicts."""
    ep.mkdir(parents=True, exist_ok=True)
    members = [{"countryID": str(c), "supplyCenterNo": str(n)} for c, n in zip(countries, centers)]
    results = {"scores": scores, "countries": countries, "members": members, "outcome": outcome,
               "reason": "end_year", "final_state": {"turn": "4", "phase": "Finished"}}
    (ep / "results.json").write_text(json.dumps(results))
    if seating:
        (ep / "seating.json").write_text(json.dumps(seating))
    if status:
        (ep / "episode.json").write_text(json.dumps({"id": ep.name, "status": status, "participants": []}))
    for slot, rows in (logs or {}).items():
        (ep / "logs").mkdir(exist_ok=True)
        (ep / "logs" / f"policy_agent_{slot}.log").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return ep
