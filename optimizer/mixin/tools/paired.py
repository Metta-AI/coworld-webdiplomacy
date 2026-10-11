#!/usr/bin/env python3
"""Paired difference between two policies seated in the same games (the default A/B design).

    python3 games/webdiplomacy/tools/paired.py DIR... --a NAME:vN --b NAME:vM [--keep-tainted] [--json]

Inputs: episode directories (hosted batches from `fetch-artifacts`, or local runs with
`seating.json` labels); see `webdip_episodes.py`. Policies are `name:vN` for hosted
seats or seating labels for local ones.

Per game that seats both A and B (the first seat of each when a policy holds several):
    d = (A's score - par[A's power]) - (B's score - par[B's power])
where par is the mean score at that power over the other seats (neither A nor B) in
all the given directories, falling back to every seat at that power when no other
seat played it. Games where A's or B's seat is tainted, or the game was cancelled or
failed, are dropped and counted (`--keep-tainted` keeps them).

Output: n, mean d (A minus B), its standard error, z = mean / SE, the A-minus-B mean
per power that A played, and a verdict. |z| < 2 is reported as "no result": three
+0.08 leads at z of about 1.4 vanished on replication in the lab. Pairing removes most
of the game-to-game variance, so it needs 2-3x fewer games than separate arms.

Example:
    python3 games/webdiplomacy/tools/paired.py .runtime/artifacts/xreq_abc \\
        --a my-bot:v4 --b my-bot:v3
    {"a": "my-bot:v4", "b": "my-bot:v3", "n": 32, "dropped_tainted": 1, "diff": 0.031,
     "se": 0.024, "z": 1.29, "verdict": "no result (|z| < 2)", ...}
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from webdip_episodes import Seat, load_dirs  # noqa: E402

MIN_ABS_Z = 2.0
# Seat-order balance check: warn when A held the lower roster slot in almost all or almost none
# of the games (a batch with free slots lands near one half).
SEAT_ORDER_MIN_GAMES = 20
SEAT_ORDER_LOW, SEAT_ORDER_HIGH = 0.2, 0.8


def power_par(seats: list[Seat], a: str, b: str) -> dict[str, float]:
    field, every = defaultdict(list), defaultdict(list)
    for s in seats:
        every[s.power].append(s.score)
        if s.policy not in (a, b):
            field[s.power].append(s.score)
    return {p: statistics.mean(field[p] or every[p]) for p in every}


def paired_differences(seats: list[Seat], a: str, b: str, keep_tainted: bool = False):
    """Return (list of (A's power, d, A sat in the lower roster slot), games dropped for taint)."""
    par = power_par(seats, a, b)
    games: dict[str, dict[str, Seat]] = defaultdict(dict)
    for s in sorted(seats, key=lambda s: (s.episode_id, s.slot)):
        if s.policy in (a, b):
            games[s.episode_id].setdefault(s.policy, s)
    diffs, dropped = [], 0
    for by in games.values():
        if a not in by or b not in by:
            continue
        if not keep_tainted and (by[a].taint or by[b].taint):
            dropped += 1
            continue
        d = (by[a].score - par[by[a].power]) - (by[b].score - par[by[b].power])
        diffs.append((by[a].power, d, by[a].slot < by[b].slot))
    return diffs, dropped


def verdict(n: int, z: float | None, a: str, b: str) -> str:
    if n < 2 or z is None:
        return "no result (n < 2)"
    if abs(z) < MIN_ABS_Z:
        return "no result (|z| < 2)"
    return f"{a} ahead" if z > 0 else f"{b} ahead"


def paired_report(seats: list[Seat], a: str, b: str, keep_tainted: bool = False) -> dict:
    diffs, dropped = paired_differences(seats, a, b, keep_tainted)
    values = [d for _, d, _ in diffs]
    a_first = sum(first for _, _, first in diffs)
    n = len(values)
    mean = statistics.mean(values) if values else 0.0
    se = statistics.stdev(values) / math.sqrt(n) if n > 1 else None
    z = mean / se if se else None
    by_power = defaultdict(list)
    for power, d, _ in diffs:
        by_power[power].append(d)
    report = {
        "a": a, "b": b, "n": n, "dropped_tainted": dropped,
        "diff": round(mean, 4), "se": round(se, 4) if se is not None else None,
        "z": round(z, 2) if z is not None else None,
        "verdict": verdict(n, z, a, b),
        "a_in_lower_slot": f"{a_first}/{n}",
        "diff_by_a_power": {p: {"n": len(v), "diff": round(statistics.mean(v), 4),
                                "se": round(statistics.stdev(v) / math.sqrt(len(v)), 4) if len(v) > 1 else None}
                            for p, v in sorted(by_power.items())},
    }
    if n >= SEAT_ORDER_MIN_GAMES and not SEAT_ORDER_LOW <= a_first / n <= SEAT_ORDER_HIGH:
        # Measured 2026-10-10 with identical code: under pinned, rotated powers a fixed seat
        # order alone was worth about +0.09 to the lower slot (test-drive lab, 84 games, z 2.6).
        report["warning"] = (f"seat order is one-sided: {a} sat in the lower roster slot in {a_first} of {n} games. "
                             "If powers were pinned, the result includes a seat-position effect of up to about 0.1; "
                             "re-run with both seat orders (make_request.py --balanced).")
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--a", required=True, help="policy A (NAME:vN or seating label)")
    ap.add_argument("--b", required=True, help="policy B")
    ap.add_argument("--keep-tainted", action="store_true")
    ap.add_argument("--json", action="store_true", help="indented JSON (default: one line)")
    args = ap.parse_args(argv)
    missing = [d for d in args.dirs if not Path(d).is_dir()]
    if missing:
        print(f"no such directory (nothing fetched yet?): {', '.join(missing)}", file=sys.stderr)
        return 2
    seats, _ = load_dirs([Path(d) for d in args.dirs])
    report = paired_report(seats, args.a, args.b, args.keep_tainted)
    print(json.dumps(report, indent=1 if args.json else None))
    return 0 if report["n"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
