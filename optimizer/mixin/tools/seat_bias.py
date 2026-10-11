#!/usr/bin/env python3
"""Does one roster seat outscore another, whoever sits there?

    python3 games/webdiplomacy/tools/wd.py seats DIR... | \\
        python3 games/webdiplomacy/tools/seat_bias.py [--seats 0 1]

Reads `wd.py seats` JSON lines on stdin. For each game it takes the raw score in
the first seat minus the raw score in the second, then prints the mean, its
standard error and z, overall and split by which policy held the first seat.
Use it on a same-code check, or on any paired batch with pinned powers, to see
whether seat position itself is worth points. It only means something when the
two seats hold every power equally often (`make_request.py --balanced`);
otherwise it mostly measures which powers each seat drew. Standard library only.
"""

import argparse
import json
import statistics
import sys
from collections import defaultdict


def summary(values: list[float]) -> str:
    if len(values) < 2:
        return f"n={len(values)}"
    mean = statistics.mean(values)
    se = statistics.stdev(values) / len(values) ** 0.5
    if not se:
        return f"n={len(values)} mean {mean:+.3f}"
    return f"n={len(values)} mean {mean:+.3f} SE {se:.3f} z {mean / se:+.2f}"


def seat_differences(seats: list[dict], first: int, second: int) -> tuple[list[float], dict[str, list[float]]]:
    """Per game: raw score in seat `first` minus seat `second`. Returns (all, by policy holding `first`)."""
    games = defaultdict(dict)
    for seat in seats:
        if not seat.get("taint"):
            games[seat["episode_id"]][seat["slot"]] = seat
    overall, by_holder = [], defaultdict(list)
    for by_slot in games.values():
        if first in by_slot and second in by_slot:
            diff = by_slot[first]["score"] - by_slot[second]["score"]
            overall.append(diff)
            by_holder[by_slot[first]["policy"]].append(diff)
    return overall, dict(by_holder)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seats", type=int, nargs=2, default=[0, 1], metavar=("FIRST", "SECOND"))
    args = ap.parse_args(argv)
    first, second = args.seats
    overall, by_holder = seat_differences([json.loads(line) for line in sys.stdin], first, second)
    print(f"seat {first} minus seat {second}, raw score: {summary(overall)}")
    for policy, values in sorted(by_holder.items()):
        print(f"  with {policy} in seat {first}: {summary(values)}")


if __name__ == "__main__":
    main()
