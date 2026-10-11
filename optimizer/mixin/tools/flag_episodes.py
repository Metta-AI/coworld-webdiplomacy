#!/usr/bin/env python3
"""Flag the episodes worth opening: a first cut of the survey binding's table.

    python3 games/webdiplomacy/tools/wd.py seats DIR... | \\
        python3 games/webdiplomacy/tools/flag_episodes.py --policy NAME:vN [--top 3]

Reads `wd.py seats` JSON lines on stdin and prints, for the named policy:
crashes or dropped orders (a seat log with no decision counts as a crash, and so
does a pod the platform deleted mid-game: taint `pod_deleted`),
opponent solos (and who soloed), our early
eliminations (zero centres before the last two years), swings of three or more
centres within one year, and our best and worst games by raw score (not per
power, and not against par: use `wd.py metrics` for that). It does not flag a
failing LLM seat; `wd.py metrics` reports that as taint. Each line carries
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


def seat_flags(seats: list[dict], policy: str) -> tuple[list[dict], int, list[dict]]:
    """(our seats, episodes, flags) for `policy` over `wd.py seats` rows.

    Each flag is `{"flag": one of FLAG_ORDER's per-game names, "episode_id", "power", "detail"}`,
    one per finding, in the order the games were given. The IDE's replay browser reads these.
    """
    games = defaultdict(list)
    for seat in seats:
        games[seat["episode_id"]].append(seat)
    found: list[dict] = []
    ours = []
    for episode_id, game in games.items():
        for seat in (s for s in game if s["policy"] == policy):
            ours.append(seat)

            def flag(name: str, detail: str) -> None:
                found.append({"flag": name, "episode_id": episode_id, "power": seat["power"], "detail": detail})

            log = seat.get("log") or {}
            if "pod_deleted" in (seat.get("taint") or []):
                # No log to count from: the platform deleted the pod, and the seat held from then on.
                flag("crash or dropped orders", "pod deleted mid-game, no seat log")
            elif log.get("exceptions") or log.get("rejected") or "no_decisions" in (seat.get("taint") or []):
                flag("crash or dropped orders", f"exceptions {log.get('exceptions')}, rejected {log.get('rejected')}, "
                                                f"decisions {log.get('decisions')}")
            winner = next((s for s in game if s["solo"] and s["policy"] != policy), None)
            if winner:
                flag("opponent solo", f"{winner['policy']} soloed as {winner['power']}")
            years = sorted(seat["centers_by_year"].items())
            dead = next((y for y, c in years if c == 0), None)
            if dead and len(years) > EARLY_MARGIN and dead <= years[-1 - EARLY_MARGIN][0]:
                flag("eliminated early", f"zero centres from {dead}")
            for (_, before), (year, after) in zip(years, years[1:]):
                if abs(after - before) >= SWING:
                    flag("swing of 3+ centres in a year", f"{before} -> {after} in {year}")
    return ours, len(games), found


def episode_flags(seats: list[dict], policy: str, top: int = 3) -> tuple[int, int, dict[str, list[str]]]:
    """(our seats, episodes, flag name -> printed lines) for `policy` over `wd.py seats` rows."""
    ours, episodes, found = seat_flags(seats, policy)
    flags: dict[str, list[str]] = defaultdict(list)
    for f in found:
        flags[f["flag"]].append(f"{f['episode_id']} as {f['power']}: {f['detail']}")
    ours.sort(key=lambda s: s["score"])
    for seat in ours[:top]:
        flags["worst games"].append(f"{seat['episode_id']} as {seat['power']}: score {seat['score']:.3f}, "
                                    f"{seat['final_centers']} centres")
    for seat in ours[::-1][:top]:
        flags["best games"].append(f"{seat['episode_id']} as {seat['power']}: score {seat['score']:.3f}, "
                                   f"{seat['final_centers']} centres")
    return len(ours), episodes, dict(flags)


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
