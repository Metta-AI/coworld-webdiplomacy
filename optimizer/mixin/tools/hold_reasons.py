#!/usr/bin/env python3
"""Why our press build's units hold: who chose each hold, where the unit stood, and how boxed in it was.

    python3 games/webdiplomacy/tools/hold_reasons.py DIR... --policy NAME[:vN] [--variant classic-press] [--json]

`holds.py` says how much a policy holds and how that goes with pinning. This tool splits the
holds themselves, one column per version, over movement phases where the seat's log has a
committed press policy:

  who chose the hold      `fixed by the agent`: the hold is in the policy's `require_orders`.
                          The rest were left to the search, split by where the unit stood: on a
                          supply centre we own (guarding it), on another power's centre
                          (waiting to capture it in autumn), or elsewhere.
  by forbidden provinces  hold share of all orders, by how many provinces the policy's
                          `forbid_moves_into` listed (0, 1, 2, 3, 4 or more)
  by allies named         the same, by how many powers the policy called an ally (0 to 3 or more)

Seats whose pod the platform deleted are left out. Only seats whose log is on disk are read.
These are counts: a long forbidden list that goes with holds is not shown to cause them.
Standard library only.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from holds import plain  # noqa: E402
from opponent_profile import load_games, policy_matcher  # noqa: E402
from webdip_episodes import read_log  # noqa: E402

KINDS = ("fixed by the agent", "left to the search, on our own centre",
         "left to the search, on another power's centre", "left to the search, elsewhere")
FORBID_CAP, ALLY_CAP = 4, 3


def hold_kind(order: dict, fixed: set[str], centers: dict[str, str], me: str) -> str:
    """Which of KINDS one hold order is. `fixed` holds the policy's `require_orders`, made plain."""
    if plain(order["text"]) in fixed:
        return KINDS[0]
    owner = centers.get(order["at"])
    return KINDS[1] if owner == me else KINDS[2] if owner else KINDS[3]


def phase_counts(orders: list[dict], policy: dict, centers: dict[str, str], me: str) -> dict:
    """The counts of one movement phase: our orders, our holds by kind, and the policy's two sizes."""
    fixed = {plain(text) for text in policy.get("require_orders") or []}
    stances = [str(stance).lower() for stance in (policy.get("stances") or {}).values()]
    holds = [o for o in orders if o["type"] == "hold"]
    return {"orders": len(orders), "holds": len(holds),
            "kinds": Counter(hold_kind(o, fixed, centers, me) for o in holds),
            "forbidden": min(len(policy.get("forbid_moves_into") or []), FORBID_CAP),
            "allies": min(stances.count("ally"), ALLY_CAP)}


def new_total() -> dict:
    return {"seats": 0, "orders": 0, "holds": 0, "kinds": Counter(),
            "by_forbidden": {n: [0, 0] for n in range(FORBID_CAP + 1)},
            "by_allies": {n: [0, 0] for n in range(ALLY_CAP + 1)}}


def add(total: dict, counts: dict) -> None:
    total["orders"] += counts["orders"]
    total["holds"] += counts["holds"]
    total["kinds"].update(counts["kinds"])
    for key, size in (("by_forbidden", counts["forbidden"]), ("by_allies", counts["allies"])):
        total[key][size][0] += counts["orders"]
        total[key][size][1] += counts["holds"]


def by_version(games, matches) -> dict[str, dict]:
    totals: dict[str, dict] = {}
    for game in games:
        for seat in game.seats:
            if not matches(seat.policy) or "pod_deleted" in seat.taint or seat.slot not in game.logs:
                continue
            me = seat.power.upper()
            commits = {int(e["turn"]): e for e in read_log(game.logs[seat.slot]) if e.get("event") == "press_commit"}
            total = totals.setdefault(seat.policy, new_total())
            total["seats"] += 1
            for phase in game.phases:
                mine = [o for o in phase["orders"] if o["power"] == me]
                policy = (commits.get(phase["turn"]) or {}).get("press_policy")
                if mine and policy is not None:
                    add(total, phase_counts(mine, policy, phase["centers"], me))
    return totals


def _share(holds: int, orders: int) -> str:
    return f"{holds / orders:.0%} of {orders}" if orders else "no orders"


def render(totals: dict[str, dict]) -> str:
    versions = sorted(totals)
    head = " | ".join(versions)
    rule = "|---|" + "---|" * len(versions)
    lines = ["# Why units hold", "",
             "seats read: " + ", ".join(f"{v} {totals[v]['seats']}" for v in versions), "",
             "## Who chose the hold (share of all orders in committed phases)", "",
             f"| | {head} |", rule,
             "| orders | " + " | ".join(str(totals[v]["orders"]) for v in versions) + " |",
             "| holds | " + " | ".join(f"{totals[v]['holds']} ({totals[v]['holds'] / totals[v]['orders']:.0%})"
                                       for v in versions) + " |"]
    for kind in KINDS:
        lines.append(f"| {kind} | " + " | ".join(
            f"{totals[v]['kinds'][kind]} ({totals[v]['kinds'][kind] / totals[v]['orders']:.0%})"
            for v in versions) + " |")
    for title, key, cap in (("provinces forbidden", "by_forbidden", FORBID_CAP),
                            ("allies named", "by_allies", ALLY_CAP)):
        lines += ["", f"## Hold share by {title} (share of that many orders)", "", f"| {title} | {head} |", rule]
        for size in range(cap + 1):
            label = f"{size} or more" if size == cap else str(size)
            lines.append(f"| {label} | " + " | ".join(
                _share(totals[v][key][size][1], totals[v][key][size][0]) for v in versions) + " |")
    lines += ["", "Counts only: they show what goes with holds, not what causes them."]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--policy", required=True, help="NAME for every version, NAME:vN for one")
    ap.add_argument("--variant", default="classic-press")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    games, _ = load_games([Path(d) for d in args.dirs], args.variant)
    totals = by_version(games, policy_matcher(args.policy))
    if not totals:
        print("no seats of that policy with a log on disk", file=sys.stderr)
        return 2
    print(json.dumps(totals, indent=1) if args.json else render(totals), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
