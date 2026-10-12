#!/usr/bin/env python3
"""How much one policy holds, beside the field, and what in its own press policy goes with the holds.

    python3 games/webdiplomacy/tools/holds.py DIR... --policy NAME[:vN] [--variant classic-press]
        [--episodes FILE] [--alone] [--ours OTHERNAME]... [--stopped-phases 4] [--json]

A hold is a unit ordered to stay where it is. A policy that holds far more than the other
seats at the same power is passive, frozen by its own press layer, or dead. This tool counts
it over every game, for our policy or for an opponent (the orders are public). Sections:

  by version and power   Holds as a share of all movement-phase orders, for each version of the
                         policy, beside the field: every other policy's seats at the same
                         power in the same games. In a paired A/B both versions are rows, so
                         this is the mechanism check for a change that should free units.
  by game year           The same share per year, for the policy, for the policy without its
                         stopped seats, and for the field.
  stopped seats          Seats whose every unit held in each of their last N movement phases
                         (default 4, two game years), with the season the run began and what
                         the seat log says. Orders cannot tell a dead bot from a locked
                         position; the log can.
  press policy           Only for seats whose log is on disk and carries the reference
                         policy's `press_policy` (our own press builds). Per movement phase:
                         how many of the holds the log had in `require_orders`, the hold share
                         split by what the committed policy did (pinned under half of the units
                         or half and more; forbade a province or none; no policy committed, so
                         the search floor played; no decision line at all for the phase, which
                         means the bot was not running), the same for the last movement phase,
                         and the decision trace's `press_commits` and any counter whose name
                         ends in `_refused` (a guard you add to the press layer can log one,
                         for example `press_<rule>_refused`).

Seats whose pod the platform deleted (taint `pod_deleted`) hold because the bot is gone. They
are left out of every share, for the policy and for the field, and counted in the header. A
field seat's taint is known only when its log is on disk.

`--alone` keeps only games with exactly one seat of the policy (any version): the view for
"how do we play", without paired runs. If you also uploaded under another name, give it with
`--ours OTHERNAME` (repeatable, as in `matchups.py`): `--alone` then also leaves out the games
that seat it. That is all `--ours` does here; without `--alone` such a seat stays in the field
rows. `--episodes FILE` reads only the listed games (a saved
`matchups.py` or `opponent_profile.py` run, or one id per line), so the counts line up with a
write-up. Press and gunboat are different games: give `--variant`. To compare a press build
with the same search with press off, run the tool once per variant and policy name.

These are counts. They show where holds come from, not that holding costs score: that takes
a paired A/B. Scores, pars, SEs and z come from `matchups.py` and `paired.py`. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from opponent_profile import Game, family, load_games, policy_matcher, read_episode_list
from press_audit import turn_label
from webdip_episodes import Seat, read_log

POWER_ORDER = ("England", "France", "Germany", "Italy", "Austria", "Turkey", "Russia")


def is_guard_counter(key: str) -> bool:
    """`press_commits`, or a refusal counter a guard in the press layer logs in the decision trace."""
    return key == "press_commits" or key.endswith("_refused")


def plain(text: str) -> str:
    """An order text without coasts or the convoy marker, so a log line and a replay line compare."""
    return re.sub(r"/[A-Z]{2}", "", text).replace(" VIA", "").strip()


def seat_phases(game: Game, seat: Seat) -> list[dict]:
    """One row per movement phase in which the seat had units: turn, its orders, its holds."""
    me = seat.power.upper()
    rows = []
    for phase in game.phases:
        orders = [o for o in phase["orders"] if o["power"] == me]
        if orders:
            rows.append({"turn": phase["turn"], "orders": orders, "holds": [o for o in orders if o["type"] == "hold"]})
    return rows


def trailing_all_hold(rows: list[dict]) -> tuple[int, int | None]:
    """(movement phases in a row, up to the last, in which every unit held; the turn the run began)."""
    run, start = 0, None
    for row in reversed(rows):
        if len(row["holds"]) != len(row["orders"]):
            break
        run, start = run + 1, row["turn"]
    return run, start


def log_note(game: Game, seat: Seat) -> str:
    if seat.slot not in game.logs:
        return "no log on disk"
    if "pod_deleted" in seat.taint:
        return "pod deleted: the bot was gone"
    if seat.log:
        return (f"log: {seat.log.get('decisions', 0)} decisions, {seat.log.get('exceptions', 0)} exceptions, "
                f"{seat.log.get('llm_failed', 0)} of {seat.log.get('llm_calls', 0)} LLM calls failed")
    return "log has no JSON rows"


def committed_by_turn(log_path: str) -> tuple[dict[int, dict | None], Counter]:
    """turn -> the press policy the seat's log committed that movement phase (None: none), and the
    guards' refusal counters summed over the game."""
    committed: dict[int, dict | None] = {}
    guards: Counter = Counter()
    for row in read_log(Path(log_path)):
        if row.get("event") != "decision" or row.get("phase") != "Diplomacy" or "press_policy" not in row:
            continue
        policy = row["press_policy"]
        committed[int(row["turn"])] = policy if isinstance(policy, dict) else None
        for key, count in (row.get("trace") or {}).items():
            if is_guard_counter(key):
                guards[key] += int(count or 0)
    return committed, guards


NO_DECISION = "no decision line for the phase"


def constraint_group(policy: dict | None | str, units: int) -> str:
    if policy == NO_DECISION:
        return NO_DECISION
    if policy is None:
        return "no policy committed (the search floor played)"
    pinned = len(policy.get("require_orders") or [])
    forbids = "forbids a province" if policy.get("forbid_moves_into") else "forbids nothing"
    return ("pins half or more" if 2 * pinned >= units else "pins under half") + ", " + forbids


def _add(cell: Counter, orders: int, holds: int) -> None:
    cell["orders"] += orders
    cell["holds"] += holds


def measure(games: list[Game], policy: str, alone: bool = False, stopped_phases: int = 4,
            also_ours: tuple[str, ...] = ()) -> dict:
    is_policy = policy_matcher(policy)
    ours_by_name = [policy_matcher(family(name)) for name in (policy, *also_ours)]

    def in_family(name: str) -> bool:
        return any(matches(name) for matches in ours_by_name)

    mix: dict[tuple[str, str], Counter] = defaultdict(Counter)  # (who, power) -> orders, holds, seats, ...
    by_year: dict[tuple[str, int], Counter] = defaultdict(Counter)
    press: dict[str, dict] = {}
    stopped, dead, used = [], Counter(), 0
    for game in games:
        ours = [s for s in game.seats if is_policy(s.policy)]
        if not ours or (alone and sum(in_family(s.policy) for s in game.seats) != 1):
            continue
        used += 1
        for seat in game.seats:
            who = seat.policy if is_policy(seat.policy) else "field"
            if "pod_deleted" in seat.taint:
                dead[who] += 1
                continue
            rows = seat_phases(game, seat)
            run, start = trailing_all_hold(rows)
            is_stopped = run >= stopped_phases
            cell = mix[(who, seat.power)]
            cell["seats"] += 1
            cell["phases"] += len(rows)
            cell["all_hold_phases"] += sum(len(r["holds"]) == len(r["orders"]) for r in rows)
            cell["stopped"] += is_stopped
            _add(cell, sum(len(r["orders"]) for r in rows), sum(len(r["holds"]) for r in rows))
            labels = ["field"] if who == "field" else ["policy"] + ([] if is_stopped else ["policy, not stopped"])
            for row in rows:
                for label in labels:
                    _add(by_year[(label, 1901 + row["turn"] // 2)], len(row["orders"]), len(row["holds"]))
            if who == "field":
                continue
            if is_stopped:
                stopped.append({"episode": game.episode, "policy": seat.policy, "power": seat.power,
                                "began": turn_label(start), "phases": run, "of": len(rows), "score": seat.score,
                                "final_centers": seat.final_centers, "taint": list(seat.taint),
                                "log": log_note(game, seat)})
            if seat.slot in game.logs:
                committed, guards = committed_by_turn(game.logs[seat.slot])
                if committed:
                    _press_counts(press.setdefault(seat.policy, _empty_press()), rows, committed, guards)
    return {
        "policy": policy, "alone": alone, "also_ours": sorted(family(name) for name in also_ours), "games": used,
        "stopped_phases": stopped_phases,
        "pod_deleted_seats": dict(dead),
        "by_power": [_share_row(who, power, mix[(who, power)]) for who, power in _keys(mix)],
        "overall": [_share_row(who, "all", _total(mix, who)) for who in _groups(mix)],
        "by_year": [{"who": who, "year": year, **_share(cell)} for (who, year), cell in sorted(by_year.items())],
        "stopped_seats": sorted(stopped, key=lambda s: (s["power"], s["episode"])),
        "press_policy": {version: _press_out(p) for version, p in sorted(press.items())},
    }


def _empty_press() -> dict:
    return {"seats": 0, "phases": 0, "orders": 0, "holds": 0, "holds_required": 0, "orders_required": 0,
            "guards": Counter(), "groups": defaultdict(Counter), "last_phase": defaultdict(Counter)}


def _press_counts(p: dict, rows: list[dict], committed: dict, guards: Counter) -> None:
    p["seats"] += 1
    p["guards"].update(guards)
    for i, row in enumerate(rows):
        policy = committed.get(row["turn"], NO_DECISION)
        required = {plain(text) for text in (policy.get("require_orders") or [])} if isinstance(policy, dict) else set()
        orders, holds = len(row["orders"]), len(row["holds"])
        p["phases"] += 1
        p["orders"] += orders
        p["holds"] += holds
        p["orders_required"] += sum(plain(o["text"]) in required for o in row["orders"])
        p["holds_required"] += sum(plain(o["text"]) in required for o in row["holds"])
        group = constraint_group(policy, orders)
        for split in [p["groups"]] + ([p["last_phase"]] if i == len(rows) - 1 else []):
            split[group]["phases"] += 1
            _add(split[group], orders, holds)


def _share(cell: Counter) -> dict:
    return {"orders": cell["orders"], "holds": cell["holds"],
            "hold_share": round(cell["holds"] / cell["orders"], 4) if cell["orders"] else None}


def _share_row(who: str, power: str, cell: Counter) -> dict:
    return {"who": who, "power": power, "seats": cell["seats"], **_share(cell), "phases": cell["phases"],
            "all_hold_phases": cell["all_hold_phases"], "stopped_seats": cell["stopped"]}


def _groups(mix: dict) -> list[str]:
    return sorted({who for who, _ in mix if who != "field"}) + (["field"] if any(w == "field" for w, _ in mix) else [])


def _keys(mix: dict) -> list[tuple[str, str]]:
    return [(who, power) for power in POWER_ORDER for who in _groups(mix) if (who, power) in mix]


def _total(mix: dict, who: str) -> Counter:
    total: Counter = Counter()
    for (w, _), cell in mix.items():
        if w == who:
            total.update(cell)
    return total


def _press_out(p: dict) -> dict:
    def split(groups: dict) -> list[dict]:
        return [{"group": g, "phases": c["phases"], **_share(c)} for g, c in sorted(groups.items())]

    return {"seats_with_a_policy_log": p["seats"], "phases": p["phases"], "orders": p["orders"],
            "orders_required": p["orders_required"], "holds": p["holds"], "holds_required": p["holds_required"],
            "guards": dict(p["guards"]), "by_constraint": split(p["groups"]), "last_phase": split(p["last_phase"])}


def _pct(share: float | None) -> str:
    return f"{share:.0%}" if share is not None else "-"


def render(r: dict) -> str:
    alone = " with one seat of the policy" + "".join(f" or {name}" for name in r["also_ours"]) if r["alone"] else ""
    lines = [f"# Holds: {r['policy']}, {r['games']} games{alone}"]
    if r["pod_deleted_seats"]:
        lines.append("seats left out because their pod was deleted: "
                     + ", ".join(f"{who} {n}" for who, n in sorted(r["pod_deleted_seats"].items())))
    lines += ["", "## Hold share of movement orders, by version and power", "",
              "| power | who | seats | orders | holds | hold share | all-hold phases | stopped seats |",
              "|---|---|---|---|---|---|---|---|"]
    for row in r["by_power"] + r["overall"]:
        lines.append(f"| {row['power']} | {row['who']} | {row['seats']} | {row['orders']} | {row['holds']} | "
                     f"{_pct(row['hold_share'])} | {row['all_hold_phases']} of {row['phases']} | "
                     f"{row['stopped_seats']} of {row['seats']} |")
    years = sorted({row["year"] for row in r["by_year"]})
    lines += ["", "## Hold share by game year", "", "| who | " + " | ".join(str(y) for y in years) + " |",
              "|---|" + "---|" * len(years)]
    for who in ("policy", "policy, not stopped", "field"):
        cells = {row["year"]: row for row in r["by_year"] if row["who"] == who}
        if cells:
            lines.append(f"| {who} | " + " | ".join(_pct(cells[y]["hold_share"]) if y in cells else "-"
                                                     for y in years) + " |")
    lines += ["", f"## Stopped seats (every unit held in each of the last {r['stopped_phases']} movement phases)", ""]
    for s in r["stopped_seats"]:
        lines.append(f"- {s['power']} {s['policy']} {s['episode']}: all hold from {s['began']} ({s['phases']} of its "
                     f"{s['of']} movement phases), score {s['score']:.3f}, {s['final_centers']} centres; {s['log']}")
    if not r["stopped_seats"]:
        lines.append("none")
    for version, p in r["press_policy"].items():
        lines += ["", f"## What the press layer committed: {version} ({p['seats_with_a_policy_log']} seats with a "
                      "policy in their log)", "",
                  f"- orders {p['orders']}, of them in `require_orders` {p['orders_required']} "
                  f"({_pct(p['orders_required'] / p['orders'] if p['orders'] else None)})",
                  f"- holds {p['holds']} ({_pct(p['holds'] / p['orders'] if p['orders'] else None)}), of them in "
                  f"`require_orders` {p['holds_required']}",
                  "- guards: " + (", ".join(f"{k} {v}" for k, v in sorted(p["guards"].items())) or "no counters")]
        for title, key in (("Hold share by what the committed policy did", "by_constraint"),
                           ("The game's last movement phase", "last_phase")):
            lines += ["", f"### {title}", "", "| committed policy | phases | orders | holds | hold share |",
                      "|---|---|---|---|---|"]
            for g in p[key]:
                lines.append(f"| {g['group']} | {g['phases']} | {g['orders']} | {g['holds']} | "
                             f"{_pct(g['hold_share'])} |")
    lines += ["", "Counts only: they show where holds come from, not what they cost. Scores come from matchups.py."]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dirs", nargs="+", metavar="DIR")
    ap.add_argument("--policy", required=True, help="NAME (every version) or NAME:vN; ours or an opponent")
    ap.add_argument("--variant", help="only this variant, for example classic-press or classic-gunboat")
    ap.add_argument("--episodes", metavar="FILE", help="only the episode ids in FILE (a saved matchups.py or "
                    "opponent_profile.py run, or one id per line)")
    ap.add_argument("--alone", action="store_true", help="only games with exactly one seat of the policy")
    ap.add_argument("--ours", action="append", default=[], metavar="OTHERNAME",
                    help="another policy name that is also ours (repeatable): --alone leaves out games that seat it")
    ap.add_argument("--stopped-phases", type=int, default=4, metavar="N")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    only = read_episode_list(Path(args.episodes)) if args.episodes else None
    games, _ = load_games([Path(d) for d in args.dirs], args.variant, only)
    result = measure(games, args.policy, args.alone, args.stopped_phases, tuple(args.ours))
    if not result["games"]:
        print(f"no game seats {args.policy} below the given directories (with these filters)", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=1) if args.json else render(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
