#!/usr/bin/env python3
"""Centre change per game year, by policy: where in the game a policy gains or loses.

    python3 games/webdiplomacy/tools/wd.py seats DIR... | python3 games/webdiplomacy/tools/year_deltas.py

Reads `wd.py seats` JSON lines on stdin. For each policy prints the mean change in
supply centres during each year (centres at the end of year Y minus the end of Y-1;
1901 is measured from the power's starting count). The last column of the game is
the final year: a policy that plays the last Autumn for position instead of centres
shows a weaker final-year gain than its earlier years. Tainted seats are skipped.
Standard library only.
"""

import argparse
import json
import sys
from collections import defaultdict

START = {"Russia": 4}  # every other power starts with 3


def year_deltas(seats: list[dict]) -> dict[str, dict[str, list[int]]]:
    """policy -> year -> centre changes during that year (1901 is measured from the starting count)."""
    deltas: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for seat in seats:
        if seat.get("taint"):
            continue
        previous = START.get(seat["power"], 3)
        for year, centers in sorted(seat["centers_by_year"].items()):
            deltas[seat["policy"]][year].append(centers - previous)
            previous = centers
    return deltas


def main(argv=None) -> None:
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)
    deltas = year_deltas([json.loads(line) for line in sys.stdin])
    years = sorted({y for by_year in deltas.values() for y in by_year})
    print("| policy | seats | " + " | ".join(years) + " |")
    print("|---|---|" + "---|" * len(years))
    for policy, by_year in sorted(deltas.items()):
        seats = max(len(v) for v in by_year.values())
        cells = [f"{sum(by_year[y]) / len(by_year[y]):+.2f}" if by_year[y] else "" for y in years]
        print(f"| {policy} | {seats} | " + " | ".join(cells) + " |")


if __name__ == "__main__":
    main()
