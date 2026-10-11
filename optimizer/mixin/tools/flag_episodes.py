#!/usr/bin/env python3
"""Flag the episodes worth opening: a first cut of the survey binding's table.

    python3 games/webdiplomacy/tools/wd.py seats DIR... | \\
        python3 games/webdiplomacy/tools/flag_episodes.py --policy NAME:vN [--top 3]

Reads `wd.py seats` JSON lines on stdin and prints, for the named policy:
crashes or dropped orders, opponent solos (and who soloed), our early
eliminations (zero centres before the last two years), swings of three or more
centres within one year, and our best and worst games by raw score (not per
power, and not against par: use `wd.py metrics` for that). It does not flag a
failing LLM seat; `wd.py metrics` reports those as taint. Each line carries
the episode id to pass to `coworld replay-open <id> --hosted`. Standard library only.
"""

import argparse
import json
import sys
from collections import defaultdict

FLAG_ORDER = ("crash or dropped orders", "opponent solo", "eliminated early",
              "swing of 3+ centres in a year", "worst games", "best games")
SWING = 3            # centres gained or lost within one year
EARLY_MARGIN = 2     # "early" = eliminated more than this many years before the game's last year


def episode_flags(seats: list[dict], policy: str, top: int = 3) -> tuple[int, int, dict[str, list[str]]]:
    """(our seats, episodes, flag name -> lines) for `policy` over `wd.py seats` rows."""
    games = defaultdict(list)
    for seat in seats:
        games[seat["episode_id"]].append(seat)
    flags: dict[str, list[str]] = defaultdict(list)
    ours = []
    for episode_id, game in games.items():
        for seat in (s for s in game if s["policy"] == policy):
            ours.append(seat)
            where = f"{episode_id} as {seat['power']}"
            log = seat.get("log") or {}
            if log.get("exceptions") or log.get("rejected") or "no_decisions" in (seat.get("taint") or []):
                flags["crash or dropped orders"].append(
                    f"{where}: exceptions {log.get('exceptions')}, rejected {log.get('rejected')}, "
                    f"decisions {log.get('decisions')}")
            winner = next((s for s in game if s["solo"] and s["policy"] != policy), None)
            if winner:
                flags["opponent solo"].append(f"{where}: {winner['policy']} soloed as {winner['power']}")
            years = sorted(seat["centers_by_year"].items())
            dead = next((y for y, c in years if c == 0), None)
            if dead and len(years) > EARLY_MARGIN and dead <= years[-1 - EARLY_MARGIN][0]:
                flags["eliminated early"].append(f"{where}: zero centres from {dead}")
            for (_, before), (year, after) in zip(years, years[1:]):
                if abs(after - before) >= SWING:
                    flags["swing of 3+ centres in a year"].append(f"{where}: {before} -> {after} in {year}")
    ours.sort(key=lambda s: s["score"])
    for seat in ours[:top]:
        flags["worst games"].append(f"{seat['episode_id']} as {seat['power']}: score {seat['score']:.3f}, "
                                    f"{seat['final_centers']} centres")
    for seat in ours[::-1][:top]:
        flags["best games"].append(f"{seat['episode_id']} as {seat['power']}: score {seat['score']:.3f}, "
                                   f"{seat['final_centers']} centres")
    return len(ours), len(games), dict(flags)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--policy", required=True)
    ap.add_argument("--top", type=int, default=3, help="rows per flag (default 3)")
    args = ap.parse_args(argv)

    ours, episodes, flags = episode_flags([json.loads(line) for line in sys.stdin], args.policy, args.top)
    print(f"{args.policy}: {ours} seats in {episodes} episodes")
    for name in FLAG_ORDER:
        rows = flags.get(name, [])
        print(f"\n{name}: {len(rows)}")
        for row in rows[:args.top]:
            print(f"  {row}")


if __name__ == "__main__":
    main()
