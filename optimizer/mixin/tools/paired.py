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

Output: n, mean d (A minus B), its standard error, the paired SD (`sd`, the number
`sizing.py --sd` wants), z = mean / SE, and a verdict. Two per-power tables:
`vs_par_by_power` compares A and B at the SAME power (each one's mean score vs par
there; unpaired SE; the table to judge "is the candidate worse as Austria" from), and
`pair_diff_when_a_plays` is the mean of d over the games where A held that power. The
second is NOT a per-power effect: B holds a different power in each of those games, so
identical code can read far below zero at one power and far above it at the next. |z| < 2 is
reported as "no result". Pairing removes most of the game-to-game variance, so it needs fewer
games than separate arms (`sizing.py` with and without `--separate` gives both counts).

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
from webdip_episodes import Seat, load_dirs, other_seat_taint  # noqa: E402

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
    """Return (list of (A's power, d, A sat in the lower roster slot), games dropped for taint, ids of games kept)."""
    par = power_par(seats, a, b)
    games: dict[str, dict[str, Seat]] = defaultdict(dict)
    for s in sorted(seats, key=lambda s: (s.episode_id, s.slot)):
        if s.policy in (a, b):
            games[s.episode_id].setdefault(s.policy, s)
    diffs, dropped, kept = [], 0, set()
    for episode, by in games.items():
        if a not in by or b not in by:
            continue
        if not keep_tainted and (by[a].taint or by[b].taint):
            dropped += 1
            continue
        d = (by[a].score - par[by[a].power]) - (by[b].score - par[by[b].power])
        diffs.append((by[a].power, d, by[a].slot < by[b].slot))
        kept.add(episode)
    return diffs, dropped, kept


def vs_par_by_power(seats: list[Seat], a: str, b: str, keep_tainted: bool = False) -> dict[str, dict]:
    """Per power: A's mean score vs par AT THAT POWER, B's AT THE SAME POWER, and the difference.

    This is the per-power read of an A/B. The two means come from different games (in one game
    A and B hold different powers), so the SE is the unpaired one and each cell needs many games."""
    par = power_par(seats, a, b)
    games: dict[str, dict[str, Seat]] = defaultdict(dict)
    for s in sorted(seats, key=lambda s: (s.episode_id, s.slot)):
        if s.policy in (a, b):
            games[s.episode_id].setdefault(s.policy, s)
    cells: dict[str, dict[str, list[float]]] = defaultdict(lambda: {"a": [], "b": []})
    for by in games.values():
        if a not in by or b not in by or (not keep_tainted and (by[a].taint or by[b].taint)):
            continue
        cells[by[a].power]["a"].append(by[a].score - par[by[a].power])
        cells[by[b].power]["b"].append(by[b].score - par[by[b].power])
    out = {}
    for power, cell in sorted(cells.items()):
        if not cell["a"] or not cell["b"]:
            continue
        diff = statistics.mean(cell["a"]) - statistics.mean(cell["b"])
        se = None
        if len(cell["a"]) > 1 and len(cell["b"]) > 1:
            se = math.sqrt(statistics.variance(cell["a"]) / len(cell["a"])
                           + statistics.variance(cell["b"]) / len(cell["b"]))
        out[power] = {"n_a": len(cell["a"]), "n_b": len(cell["b"]),
                      "a_vs_par": round(statistics.mean(cell["a"]), 4),
                      "b_vs_par": round(statistics.mean(cell["b"]), 4),
                      "diff": round(diff, 4), "se": round(se, 4) if se else None,
                      "z": round(diff / se, 2) if se else None}
    return out


def verdict(n: int, z: float | None, a: str, b: str) -> str:
    if n < 2 or z is None:
        return "no result (n < 2)"
    if abs(z) < MIN_ABS_Z:
        return "no result (|z| < 2)"
    return f"{a} ahead" if z > 0 else f"{b} ahead"


def paired_report(seats: list[Seat], a: str, b: str, keep_tainted: bool = False) -> dict:
    diffs, dropped, kept = paired_differences(seats, a, b, keep_tainted)
    others = other_seat_taint([s for s in seats if s.episode_id in kept], lambda s: s.policy in (a, b))
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
        # Games counted here in which a seat of neither policy was tainted (a crashed opponent).
        "other_seats_tainted": others,
        "diff": round(mean, 4), "se": round(se, 4) if se is not None else None,
        "z": round(z, 2) if z is not None else None,
        "verdict": verdict(n, z, a, b),
        "a_in_lower_slot": f"{a_first}/{n}",
        "sd": round(statistics.stdev(values), 4) if n > 1 else None,
        "vs_par_by_power": vs_par_by_power(seats, a, b, keep_tainted),
        # Not a per-power effect: in each game B holds a DIFFERENT power, so a cell is "A vs par
        # at this power, minus B vs par at whatever B held", and identical code can read far
        # from zero here. Use `vs_par_by_power` to judge a power.
        "pair_diff_when_a_plays": {p: {"n": len(v), "diff": round(statistics.mean(v), 4),
                                       "se": round(statistics.stdev(v) / math.sqrt(len(v)), 4) if len(v) > 1 else None}
                                   for p, v in sorted(by_power.items())},
    }
    if n >= SEAT_ORDER_MIN_GAMES and not SEAT_ORDER_LOW <= a_first / n <= SEAT_ORDER_HIGH:
        # Under pinned, rotated powers a fixed seat order alone can read as a difference
        # between two uploads of identical code (see make_request.py).
        report["warning"] = (f"seat order is one-sided: {a} sat in the lower roster slot in {a_first} of {n} games. "
                             "If powers were pinned, the result includes a seat-position effect; "
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
