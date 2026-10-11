#!/usr/bin/env python3
"""Check a claim about orders, units or centres over every game, with the field beside it.

    python3 games/webdiplomacy/tools/board_counts.py DIR... --policy NAME[:vN] --as POWER
        [--order "A VEN - TRI"]... [--owns TRI]... [--unit-at TRI]... [--when S1901-A1902]
        [--split-by POWER] [--variant classic-press] [--episodes FILE] [--rows] [--json]

A profile or a matchup write-up says things like "its Italy orders A VEN - TRI in Spring
1901", "its Turkey owns Sevastopol after 1902" or "our Austria leaves Trieste empty". Three
games read by hand do not show that; this counts it over all of them. Each count is printed
for the policy's seats at POWER and for **the field**: every other policy's seats at the same
power in the games read. A habit the field shares is not this policy's habit.

  --order TEXT   Seats that gave this movement order in the phases of `--when`: in at least one
                 phase, in every phase, and with the order succeeding at least once. TEXT is the
                 order as the tools print it (`A VEN - TRI`, `F ANK - BLA`, `A BUL S BLA - RUM`,
                 `A MUN H`; no coasts). `*` matches anything: `"* - TRI"` is any move into
                 Trieste, `"* S * - HOL"` any support for a move into Holland.
  --owns PROV    Seats whose power owned the supply centre after each year's autumn, as a table
                 by year. For a home centre this is "still holds it"; for another centre "has
                 taken it". `--when` does not apply.
  --unit-at PROV Seats with one of their own units in the province after each phase of `--when`.
                 "Leaves Trieste empty" is the complement.

`--when` takes one phase (`S1901`, `A1902`), a range (`S1901-A1902`), a year (`1902`: both
seasons) or a range of years (`1901-1903`). Without it, `--order` and `--unit-at` cover the
whole game, which is rarely what a claim means: give it.

`--split-by POWER` splits the policy's counts by which policy held that other power in the
game ("only beside one Austria?"). `--rows` prints one line per seat of the policy with a
replay link (`/replays/<episode id>?turn=T`, the first phase of `--when`). `--episodes FILE`
reads only the games of a saved `opponent_profile.py` or `matchups.py` run, so the counts
line up with the numbers a write-up quotes.

Limits. The replay does not show who owned which centre after the game's last autumn, so
`--owns` stops one year early. An order that was given and failed still counts as given.
Seats whose pod the platform deleted are left out (the bot was gone) and counted. A count
on fewer than 16 seats is an observation, not a rate; eval batches often replay one seating,
so "8 of 8" may be one table eight times (`opponent_profile.py` prints `tables`). Counts only:
scores, pars, SEs and z come from `matchups.py`. Standard library only.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from opponent_profile import Game, family, load_games, policy_matcher, read_episode_list
from press_audit import turn_label
from webdip_episodes import POWERS, Seat

POWER_NAMES = tuple(POWERS.values())


def parse_when(text: str | None) -> tuple[int, int] | None:
    """`S1901`, `A1902`, `S1901-A1902`, `1902` or `1901-1903` -> (first turn, last turn). Turn 0 is Spring 1901."""
    if not text:
        return None
    ends = []
    for part in text.split("-"):
        match = re.fullmatch(r"([SA]?)(\d{4})", part.strip().upper())
        if not match:
            raise ValueError(f"cannot read --when {text!r}: use S1901, A1902, S1901-A1902, 1902 or 1901-1903")
        season, year = match.group(1), int(match.group(2))
        first = 2 * (year - 1901) + (1 if season == "A" else 0)
        ends.append((first, first if season else first + 1))
    if len(ends) > 2:
        raise ValueError(f"cannot read --when {text!r}: at most one dash")
    return ends[0][0], ends[-1][1]


def in_range(turn: int, when: tuple[int, int] | None) -> bool:
    return when is None or when[0] <= turn <= when[1]


def seat_checks(game: Game, seat: Seat, orders: list[str], owns: list[str], unit_at: list[str],
                when: tuple[int, int] | None) -> dict:
    """What one seat did for each requested check."""
    me = seat.power.upper()
    phases = [p for p in game.phases if in_range(p["turn"], when)]
    out: dict = {"orders": {}, "owns": {}, "unit_at": {}}
    for pattern in orders:
        given = succeeded = with_units = 0
        for phase in phases:
            mine = [o for o in phase["orders"] if o["power"] == me]
            hits = [o for o in mine if fnmatch.fnmatchcase(o["text"], pattern)]
            with_units += bool(mine)
            given += bool(hits)
            succeeded += any(o["success"] for o in hits if o["type"] != "hold")
        out["orders"][pattern] = {"phases": with_units, "given": given, "succeeded": succeeded}
    for province in owns:
        # The board after an autumn is the next phase's starting board; the last autumn has none.
        out["owns"][province] = {str(1901 + p["turn"] // 2): p["centers_end"].get(province) == me
                                 for p in game.phases if p["turn"] % 2 == 1 and p.get("end_known", True)}
    for province in unit_at:
        out["unit_at"][province] = {
            turn_label(p["turn"]): any(u["at"] == province and u["power"] == me for u in p["units_end"])
            for p in phases if p.get("end_known", True)}
    return out


def _tally(rows: list[dict], orders: list[str], owns: list[str], unit_at: list[str]) -> dict:
    out: dict = {"seats": len(rows), "orders": {}, "owns": {}, "unit_at": {}}
    for pattern in orders:
        checks = [r["checks"]["orders"][pattern] for r in rows]
        out["orders"][pattern] = {
            "seats_with_units": sum(c["phases"] > 0 for c in checks),
            "given_once": sum(c["given"] > 0 for c in checks),
            "given_every_phase": sum(c["phases"] > 0 and c["given"] == c["phases"] for c in checks),
            "succeeded_once": sum(c["succeeded"] > 0 for c in checks),
        }
    for key, names in (("owns", owns), ("unit_at", unit_at)):
        for province in names:
            yes, of = Counter(), Counter()
            for r in rows:
                for label, flag in r["checks"][key][province].items():
                    of[label] += 1
                    yes[label] += flag
            out[key][province] = {label: {"yes": yes[label], "of": of[label]} for label in of}
    return out


def count(games: list[Game], policy: str, power: str, orders: list[str], owns: list[str], unit_at: list[str],
          when: tuple[int, int] | None = None, split_by: str | None = None) -> dict:
    is_policy = policy_matcher(policy)
    rows: dict[str, list[dict]] = defaultdict(list)
    dead: Counter = Counter()
    for game in games:
        beside = next((s.policy for s in game.seats if split_by and s.power == split_by), None)
        for seat in game.seats:
            if seat.power != power:
                continue
            who = "policy" if is_policy(seat.policy) else "field"
            if "pod_deleted" in seat.taint:
                dead[who] += 1
                continue
            first = when[0] if when else 0
            rows[who].append({"episode": game.episode, "policy": seat.policy, "score": seat.score,
                              "final_centers": seat.final_centers, "beside": family(beside) if beside else None,
                              "link": f"/replays/{game.episode}?turn={first}",
                              "checks": seat_checks(game, seat, orders, owns, unit_at, when)})
    result = {"policy": policy, "power": power, "when": when, "split_by": split_by, "games": len(games),
              "pod_deleted_seats": dict(dead),
              "policy_counts": _tally(rows["policy"], orders, owns, unit_at),
              "field_counts": _tally(rows["field"], orders, owns, unit_at),
              "rows": sorted(rows["policy"], key=lambda r: r["episode"])}
    if split_by:
        groups: dict[str, list[dict]] = defaultdict(list)
        for row in rows["policy"]:
            groups[row["beside"] or "?"].append(row)
        result["split"] = {name: _tally(group, orders, owns, unit_at) for name, group in sorted(groups.items())}
    return result


def _when_text(when: tuple[int, int] | None) -> str:
    if when is None:
        return "the whole game"
    return turn_label(when[0]) if when[0] == when[1] else f"{turn_label(when[0])} to {turn_label(when[1])}"


def _of(yes: int, of: int) -> str:
    return f"{yes} of {of}"


def _labelled(cells: dict) -> str:
    return ", ".join(f"{label} {_of(c['yes'], c['of'])}" for label, c in cells.items()) or "no phase in range"


def _group_lines(name: str, tally: dict) -> list[str]:
    lines = []
    for pattern, c in tally["orders"].items():
        lines.append(f"- {name}, `{pattern}`: given in at least one phase by "
                     f"{_of(c['given_once'], c['seats_with_units'])} seats, in every phase by "
                     f"{c['given_every_phase']}, succeeded at least once for {c['succeeded_once']}")
    for province, cells in tally["owns"].items():
        lines.append(f"- {name}, owns {province} after: {_labelled(cells)}")
    for province, cells in tally["unit_at"].items():
        lines.append(f"- {name}, own unit in {province} after: {_labelled(cells)}")
    return lines


def render(r: dict, rows: bool = False) -> str:
    lines = [f"# {r['policy']} as {r['power']}: {r['policy_counts']['seats']} seats, the field "
             f"{r['field_counts']['seats']} seats, in {r['games']} games read; orders and units in "
             f"{_when_text(r['when'])}"]
    if r["pod_deleted_seats"]:
        lines.append("seats left out because their pod was deleted: "
                     + ", ".join(f"{who} {n}" for who, n in sorted(r["pod_deleted_seats"].items())))
    lines += [""] + _group_lines("policy", r["policy_counts"]) + _group_lines("field", r["field_counts"])
    for name, tally in (r.get("split") or {}).items():
        lines += ["", f"## Policy seats beside {name} as {r['split_by']} ({tally['seats']} seats)", ""]
        lines += _group_lines("policy", tally)
    if rows:
        lines += ["", "## Policy seats", ""]
        for row in r["rows"]:
            found = [f"`{p}` {c['given']}/{c['phases']} phases" + (f", ok {c['succeeded']}" if c["given"] else "")
                     for p, c in row["checks"]["orders"].items()]
            found += [f"owns {p}: " + ("".join("Y" if flag else "." for flag in cells.values()) or "-")
                      for p, cells in row["checks"]["owns"].items()]
            found += [f"unit in {p}: " + ("".join("Y" if flag else "." for flag in cells.values()) or "-")
                      for p, cells in row["checks"]["unit_at"].items()]
            beside = f" beside {row['beside']}" if row["beside"] else ""
            lines.append(f"- {row['episode']} {row['policy']}{beside}, score {row['score']:.3f}, "
                         f"{row['final_centers']} centres: {'; '.join(found)} [{row['link']}]")
    lines += ["", "Counts only. Under 16 seats a count is an observation, not a rate."]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dirs", nargs="+", metavar="DIR")
    ap.add_argument("--policy", required=True, help="NAME (every version) or NAME:vN; ours or an opponent")
    ap.add_argument("--as", dest="power", required=True, choices=POWER_NAMES, help="the power the policy played")
    ap.add_argument("--order", action="append", default=[], metavar="TEXT",
                    help="a movement order; `*` matches anything")
    ap.add_argument("--owns", action="append", default=[], metavar="PROV", help="a supply centre, for example TRI")
    ap.add_argument("--unit-at", action="append", default=[], metavar="PROV", help="a province, for example TRI")
    ap.add_argument("--when", help="S1901, A1902, S1901-A1902, 1902 or 1901-1903")
    ap.add_argument("--split-by", choices=POWER_NAMES, metavar="POWER", help="split by who held this other power")
    ap.add_argument("--variant", help="only this variant, for example classic-press or classic-gunboat")
    ap.add_argument("--episodes", metavar="FILE", help="only the episode ids in FILE (a saved run, or one id per line)")
    ap.add_argument("--rows", action="store_true", help="one line per seat of the policy, with a replay link")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if not (args.order or args.owns or args.unit_at):
        ap.error("give at least one of --order, --owns, --unit-at")
    try:
        when = parse_when(args.when)
    except ValueError as error:
        ap.error(str(error))
    only = read_episode_list(Path(args.episodes)) if args.episodes else None
    games, _ = load_games([Path(d) for d in args.dirs], args.variant, only)
    provinces = [p.upper() for p in args.owns], [p.upper() for p in args.unit_at]
    result = count(games, args.policy, args.power, args.order, provinces[0], provinces[1], when, args.split_by)
    if not result["policy_counts"]["seats"]:
        print(f"{args.policy} has no live seat as {args.power} below the given directories", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=1) if args.json else render(result, args.rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
