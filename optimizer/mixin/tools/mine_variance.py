#!/usr/bin/env python3
"""Rank what goes with a policy's own good and bad games (hypothesis fuel, not evidence).

    python3 games/webdiplomacy/tools/wd.py seats DIR... | \\
        python3 games/webdiplomacy/tools/mine_variance.py --policy NAME:vN [--top 12]

Reads `wd.py seats` JSON lines on stdin. For every seat of the named policy it
builds a few behaviour features (order mix from the decision trace, failed-order
rate, times dislodged, centres after 1901 and 1902, builds), removes the power's
mean from both the feature and the final score, and prints the features ranked
by the size of their correlation with score. It also prints the same features'
means for every other policy, so "what does the strongest opponent do
differently" is one glance.

These are correlations inside one policy's games. A feature can go with winning
because it causes it, because winning causes it (large powers issue more
supports), or by chance: with a dozen features, one will look interesting at
random. Use the top rows to pick a mechanism to test with an experiment, never
as a result. Needs about 100 seats to say anything. Standard library only.
"""

import argparse
import json
import statistics
import sys
from collections import defaultdict

ORDER_TYPES = ("Move", "Hold", "Support move", "Support hold", "Convoy")


def features(seat: dict) -> dict[str, float] | None:
    trace = (seat.get("log") or {}).get("trace") or {}
    total = sum(trace.get(t, 0) for t in ORDER_TYPES)
    if not total or not seat.get("orders"):
        return None
    years = seat["centers_by_year"]
    out = {f"share of orders: {t}": trace.get(t, 0) / total for t in ORDER_TYPES}
    out["failed-order rate"] = seat["orders_failed"] / seat["orders"]
    out["times dislodged"] = float(seat["dislodged"])
    out["centres after 1901"] = float(years.get("1901", 0))
    out["centres after 1902"] = float(years.get("1902", 0))
    fleets, armies = trace.get("Build Fleet", 0), trace.get("Build Army", 0)
    out["fleet share of builds"] = fleets / max(1, fleets + armies)
    out["search gain per decision"] = (trace.get("search_score", 0) - trace.get("search_seed_score", 0)) / max(1, total)
    return out


def demean_by_power(rows: list[tuple[str, float]]) -> list[float]:
    by_power = defaultdict(list)
    for power, value in rows:
        by_power[power].append(value)
    means = {p: statistics.mean(v) for p, v in by_power.items()}
    return [value - means[power] for power, value in rows]


def correlation(xs: list[float], ys: list[float]) -> float:
    if len(xs) < 3 or statistics.pstdev(xs) == 0 or statistics.pstdev(ys) == 0:
        return 0.0
    return statistics.correlation(xs, ys)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--policy", required=True)
    ap.add_argument("--top", type=int, default=12)
    args = ap.parse_args(argv)

    ours, others = [], defaultdict(list)
    for line in sys.stdin:
        seat = json.loads(line)
        if seat.get("taint"):
            continue
        feats = features(seat)
        if feats is None:
            continue
        if seat["policy"] == args.policy:
            ours.append((seat["power"], seat["score"], feats))
        else:
            others[seat["policy"]].append(feats)
    if len(ours) < 30:
        sys.exit(f"only {len(ours)} usable seats for {args.policy}; need about 100 to say anything")

    scores = demean_by_power([(power, score) for power, score, _ in ours])
    names = list(ours[0][2])
    ranked = []
    for name in names:
        values = demean_by_power([(power, feats[name]) for power, _, feats in ours])
        ranked.append((correlation(values, scores), name))
    ranked.sort(key=lambda r: -abs(r[0]))

    noise = 2 / len(ours) ** 0.5  # |r| below this is indistinguishable from zero at about z = 2
    print(f"{args.policy}: {len(ours)} seats; correlations with final score, power removed "
          f"(|r| under {noise:.2f} is noise)\n")
    columns = sorted(others, key=lambda p: -len(others[p]))[:5]
    print("| feature | r with our score | our mean | " + " | ".join(columns) + " |")
    print("|---|---|---|" + "---|" * len(columns))
    for r, name in ranked[:args.top]:
        mine = statistics.mean(feats[name] for _, _, feats in ours)
        theirs = [f"{statistics.mean(f[name] for f in others[p]):.3f}" for p in columns]
        flag = "" if abs(r) >= noise else " (noise)"
        print(f"| {name} | {r:+.2f}{flag} | {mine:.3f} | " + " | ".join(theirs) + " |")


if __name__ == "__main__":
    main()
