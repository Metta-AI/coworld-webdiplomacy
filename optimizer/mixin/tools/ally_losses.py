#!/usr/bin/env python3
"""How often a power our press agent called an ally took a supply centre from us.

    python3 games/webdiplomacy/tools/ally_losses.py DIR... --policy NAME[:vN] [--variant classic-press]
        [--going-in] [--json]

Our press agent commits a stance toward other powers each movement phase (`press_policy.stances`
in the seat log's `press_commit` event: ally, neutral or hostile). The replay shows who owned
each supply centre at each movement phase. This tool puts the two together, one column per
version of the policy:

  centres lost, by stance     every centre that passed from us to another power, split by the
                              stance we held toward the taker in that game year (the last
                              commit of the year; `unnamed` when the taker had no stance,
                              `no commit` when the agent committed nothing that year)
  taken in a year, by stance  one "pair-year" is one other power in one game year of one of our
                              seats, under the stance we held toward it. The rate is the share
                              of pair-years in which that power took at least one centre from
                              us. If calling a power an ally were safe, the ally rate would sit
                              well below the neutral one.

The stance of the year of the loss can be an effect of the attack: an ally that stabs in spring
is called hostile by autumn. `--going-in` uses the stance held at the end of the year before
(so 1901 is all `no commit`); read the two together.

A power with no centres left is not a pair-year. The last autumn's captures are not in the
replay, so the last game year is not counted. Seats whose pod the platform deleted are left out.
Only seats whose log is on disk are read (our own builds, and house bots we own).

These are counts. They show whether a stance goes with losing centres, not that a different
stance would have kept them: that takes an A/B. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from opponent_profile import load_games, policy_matcher  # noqa: E402
from webdip_episodes import read_log  # noqa: E402

STANCES = ("ally", "neutral", "hostile", "unnamed", "no commit")


def year_of(turn: int) -> int:
    return 1901 + turn // 2


def stances_by_year(events: list[dict]) -> dict[int, dict[str, str]]:
    """Game year -> {POWER: stance} from the last `press_commit` of that year that carried a policy."""
    by_year: dict[int, dict[str, str]] = {}
    for e in events:
        if e.get("event") == "press_commit" and e.get("press_policy") is not None:
            stances = e["press_policy"].get("stances") or {}
            by_year[year_of(int(e["turn"]))] = {str(p).upper(): str(s).lower() for p, s in stances.items()}
    return by_year


def stance_toward(stances: dict[int, dict[str, str]], year: int, power: str) -> str:
    if year not in stances:
        return "no commit"
    stance = stances[year].get(power, "unnamed")
    return stance if stance in STANCES else "unnamed"


def centres_taken(phases: list[dict], me: str) -> dict[int, Counter]:
    """Game year -> Counter of the powers that took a centre from `me` in that year."""
    taken: dict[int, Counter] = defaultdict(Counter)
    for before, after in zip(phases, phases[1:]):
        for where, old in before["centers"].items():
            new = after["centers"].get(where)
            if old == me and new not in (None, me):
                taken[year_of(before["turn"])][new] += 1
    return taken


def seat_counts(phases: list[dict], me: str, events: list[dict], going_in: bool = False) -> dict:
    """Centres lost and pair-years for one seat, both split by our stance toward the other power.

    With `going_in`, the stance is the one held at the end of the year BEFORE (1901 has none)."""
    stances, taken = stances_by_year(events), centres_taken(phases, me)
    if going_in:
        stances = {year + 1: held for year, held in stances.items()}
    lost, pair_years, pair_years_hit = Counter(), Counter(), Counter()
    years = sorted({year_of(ph["turn"]) for ph in phases[:-1]})
    alive = {year_of(ph["turn"]): set(ph["centers"].values()) for ph in phases}
    for year in years:
        if me not in alive[year]:
            continue
        for power in sorted(alive[year] - {me}):
            stance = stance_toward(stances, year, power)
            pair_years[stance] += 1
            if taken[year][power]:
                pair_years_hit[stance] += 1
                lost[stance] += taken[year][power]
    return {"lost": lost, "pair_years": pair_years, "pair_years_hit": pair_years_hit}


def add(total: dict, part: dict) -> None:
    for key, counter in part.items():
        total.setdefault(key, Counter()).update(counter)
    total["seats"] = total.get("seats", 0) + 1


def by_version(games, matches, going_in: bool = False) -> tuple[dict[str, dict], Counter]:
    totals: dict[str, dict] = {}
    skipped: Counter = Counter()
    for game in games:
        for seat in game.seats:
            if not matches(seat.policy):
                continue
            if "pod_deleted" in seat.taint:
                skipped["pod deleted"] += 1
            elif seat.slot not in game.logs:
                skipped["no log on disk"] += 1
            else:
                counts = seat_counts(game.phases, seat.power.upper(), read_log(game.logs[seat.slot]), going_in)
                add(totals.setdefault(seat.policy, {}), counts)
    return totals, skipped


def render(totals: dict[str, dict], skipped: Counter) -> str:
    versions = sorted(totals)
    lines = ["# Centres lost, by our stance toward the taker", "",
             "seats read: " + ", ".join(f"{v} {totals[v]['seats']}" for v in versions)
             + (f"; left out: {dict(skipped)}" if skipped else ""), "",
             "## Centres lost (share of all centres lost)", "",
             "| stance toward the taker | " + " | ".join(versions) + " |", "|---|" + "---|" * len(versions)]
    for stance in STANCES:
        cells = []
        for v in versions:
            lost, all_lost = totals[v]["lost"][stance], sum(totals[v]["lost"].values())
            cells.append(f"{lost} ({lost / all_lost:.0%})" if all_lost else "0")
        lines.append(f"| {stance} | " + " | ".join(cells) + " |")
    lines += ["", "## Pair-years in which that power took a centre from us", "",
              "| stance toward the power | " + " | ".join(versions) + " |", "|---|" + "---|" * len(versions)]
    for stance in STANCES:
        cells = []
        for v in versions:
            hit, n = totals[v]["pair_years_hit"][stance], totals[v]["pair_years"][stance]
            cells.append(f"{hit} of {n} ({hit / n:.1%})" if n else "0 of 0")
        lines.append(f"| {stance} | " + " | ".join(cells) + " |")
    lines += ["", "Counts only: a stance that goes with losses is not shown to cause them."]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--policy", required=True, help="NAME for every version, NAME:vN for one")
    ap.add_argument("--variant", default="classic-press")
    ap.add_argument("--going-in", action="store_true",
                    help="use the stance held at the end of the year before, not the year of the loss")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    games, _ = load_games([Path(d) for d in args.dirs], args.variant)
    totals, skipped = by_version(games, policy_matcher(args.policy), args.going_in)
    if not totals:
        print("no seats of that policy with a log on disk", file=sys.stderr)
        return 2
    print(json.dumps({"versions": totals, "left_out": skipped}, indent=1) if args.json else render(totals, skipped),
          end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
