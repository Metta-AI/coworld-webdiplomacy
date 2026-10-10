#!/usr/bin/env python3
"""webDiplomacy A/B of two separate batches, by power (adapter for the vendored `ab_stats`).

    python3 games/webdiplomacy/tools/compare.py BASE_DIR CAND_DIR --baseline NAME:vN --candidate NAME:vM \\
        [--target score_vs_par] [--keep-tainted] [--json OUT.json]

Use this for separate arms (each batch seats one copy of its policy against the same
pinned opponents, fired in the same time window). When both policies sit in the same
games, use `paired.py` instead: it is 2-3x more sensitive. BASE_DIR and CAND_DIR may be
the same directory; seats are picked by policy.

Inputs: episode directories (see `webdip_episodes.py`). One observation = one target
seat. Groups: `all` plus each of the seven powers, because country is shuffled per
episode and power strength dominates raw score.

Taint first: an episode whose target seat is tainted (rejected orders, exception,
failing LLM), or that was cancelled, failed, or has no results.json, is dropped
before any mean and counted in `taint_rate` (an episode-level metric, lower is
better). A large asymmetry in taint between arms is itself a finding.

Metrics:
  score_vs_par        score minus par; par = mean score at that power over the non-target
                      seats of BOTH batches (one shared field, so a lucky draw of strong
                      powers does not look like a better policy). Default target.
  score_mean          raw draw share (sum-of-squares score)
  final_centers_mean  from results.json
  survival_rate, solo_rate
  taint_rate          per episode

Statistics (ab_stats): Welch t for means, Fisher exact for rates, Benjamini-Yekutieli
across every reported test. A verdict needs adjusted p < 0.05, |z| >= 2 and at least
30 seats per side; anything else is "no result", which is not evidence of equality.
Priors: per-seat SD is about 0.12-0.18, so 16 games per arm only detects effects of
about 0.08 or more, and about 150 per arm resolves 0.04.

Example:
    python3 games/webdiplomacy/tools/compare.py .runtime/artifacts/xreq_base .runtime/artifacts/xreq_cand \\
        --baseline my-bot:v3 --candidate my-bot:v4
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ab_stats  # noqa: E402
from webdip_episodes import POWERS, Seat, load_dirs  # noqa: E402

METRICS = [
    ("score_vs_par", True, "mean", None),
    ("score_mean", True, "mean", None),
    ("final_centers_mean", True, "mean", None),
    ("survival_rate", True, "rate", None),
    ("solo_rate", True, "rate", None),
    ("taint_rate", False, "rate", "episodes"),
]
GROUPS = ["all", *POWERS.values()]
DROP_STATUSES = {"failed", "error", "cancelled"}


def load_batch(root: Path, policy: str, keep_tainted: bool = False):
    """(target seats kept, field seats, per-episode taint records) for one batch."""
    seats, statuses = load_dirs([root])
    by_episode: dict[str, list[Seat]] = {}
    for s in seats:
        by_episode.setdefault(s.episode_id, []).append(s)
    kept, field, episodes = [], [], []
    for st in statuses:
        ep_seats = by_episode.get(st["episode_id"], [])
        target = [s for s in ep_seats if s.policy == policy]
        if not target and "results" not in st["missing"]:
            continue  # an episode without this policy is not part of this arm
        tainted = ("results" in st["missing"] or st["episode_status"] in DROP_STATUSES
                   or any(s.taint for s in target))
        episodes.append({"episode_id": st["episode_id"], "taint": tainted})
        if tainted and not keep_tainted:
            continue
        kept += [s for s in target if s.final_centers is not None]
        field += [s for s in ep_seats if s.policy != policy]
    return kept, field, episodes


def shared_par(*fields: list[Seat]) -> dict[str, float]:
    groups: dict[str, list[float]] = {}
    for field in fields:
        for s in field:
            groups.setdefault(s.power, []).append(s.score)
    return {p: statistics.mean(v) for p, v in groups.items()}


def values(recs, key, par):
    if key == "score_vs_par":
        return [r.score - par[r.power] for r in recs if r.power in par]
    if key == "score_mean":
        return [r.score for r in recs]
    if key == "final_centers_mean":
        return [float(r.final_centers) for r in recs]
    if key == "survival_rate":
        return [float(bool(r.survived)) for r in recs]
    if key == "solo_rate":
        return [float(r.solo) for r in recs]
    if key == "taint_rate":
        return [float(r["taint"]) for r in recs]
    raise KeyError(key)


def by_group(recs):
    out = {g: [] for g in GROUPS}
    for r in recs:
        out["all"].append(r)
        out[r.power].append(r)
    return out


def compare(base_dir: Path, cand_dir: Path, baseline: str, candidate: str, keep_tainted: bool = False):
    base_recs, base_field, base_eps = load_batch(base_dir, baseline, keep_tainted)
    cand_recs, cand_field, cand_eps = load_batch(cand_dir, candidate, keep_tainted)
    par = shared_par(base_field, cand_field)
    base, cand = by_group(base_recs), by_group(cand_recs)
    base["episodes"], cand["episodes"] = base_eps, cand_eps

    def metric_value(recs, key):
        vals = values(recs, key, par)
        return (statistics.mean(vals), len(vals)) if vals else None

    def value_fn(recs, key):
        return values(recs, key, par)

    deltas = ab_stats.build_deltas(base, cand, METRICS, metric_value, value_fn, GROUPS)
    return base, cand, deltas


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("baseline_dir")
    ap.add_argument("candidate_dir")
    ap.add_argument("--baseline", required=True, help="baseline policy NAME:vN (or seating label)")
    ap.add_argument("--candidate", required=True, help="candidate policy NAME:vM (or seating label)")
    ap.add_argument("--target", default="score_vs_par")
    ap.add_argument("--keep-tainted", action="store_true")
    ap.add_argument("--json", help="also write the neutral JSON contract here")
    args = ap.parse_args(argv)
    base, cand, deltas = compare(Path(args.baseline_dir), Path(args.candidate_dir),
                                 args.baseline, args.candidate, args.keep_tainted)
    if not base["all"] or not cand["all"]:
        print(f"no target seats: baseline {len(base['all'])}, candidate {len(cand['all'])}", file=sys.stderr)
        return 2
    for name, groups in (("baseline", base), ("candidate", cand)):
        eps = groups["episodes"]
        print(f"{name}: {len(eps)} episodes, {sum(e['taint'] for e in eps)} tainted"
              + (" (kept)" if args.keep_tainted else " (dropped)"))
    print(ab_stats.render_markdown(args.baseline, args.candidate, base, cand, deltas, args.target, GROUPS, METRICS))
    if args.json:
        Path(args.json).write_text(json.dumps(
            ab_stats.emit_json(args.baseline, args.candidate, args.target, deltas), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
