#!/usr/bin/env python3
"""Every supply centre we lost: which one, who took it, and what we thought of them beforehand.

    python3 games/webdiplomacy/tools/centre_losses.py DIR... --policy NAME[:vN] [--variant classic-press]
        [--going-in] [--rows] [--json]

Our press agent commits a policy each movement phase (`press_policy` in the seat log's
`press_commit` event: a stance toward other powers, ally, neutral or hostile, and a trust
number for some of them), and the seat log has every private message it sent and received
(`press_out`, `press_in`). The replay shows who owned each supply centre at each movement
phase. This tool puts them together, one column per version of the policy.

Each centre that passed from us to another power is one loss, described five ways:

  the centre           one of our home centres, or one we had gained
  the taker            the power that owned it next
  stance going in      our stance toward the taker at the end of the year BEFORE the loss
                       (the last commit of that year; `unnamed` when the taker had no stance,
                       `no commit` when the agent committed nothing, as in 1901)
  stance that year     the same, from the last commit of the year of the loss. It can be an
                       effect of the attack: an ally that stabs in spring is called hostile
                       by autumn. Read it beside "going in", never alone
  trust going in       the trust number of that earlier commit: `trusted` (0.5 or more),
                       `distrusted` (below 0.5), `no number`
  talks that year      private messages between us and the taker in the year of the loss:
                       `both wrote`, `only we wrote`, `only they wrote`, `silence`

"Talks" is not "a deal". Whether something was agreed, and whether the taker broke it, is in
the words, and this tool does not read them: `press_audit.py` does, one game at a time.
`both wrote` says where to look.

The report has one table per description (count and share of all centres lost), the centres
lost most often, and then the rate table:

  taken in a year, by stance  one "pair-year" is one other power in one game year of one of our
                              seats, under the stance we held toward it. The rate is the share
                              of pair-years in which that power took at least one centre from
                              us. If calling a power an ally were safe, the ally rate would sit
                              well below the neutral one. It uses the stance of that year, or
                              with `--going-in` the stance going in.

`--rows` prints one line per lost centre instead (game, our power, year, centre, taker and the
descriptions above), worst-hit seats together: the list to open games from.

A power with no centres left is not a pair-year. The last autumn's captures are not in the
replay, so the last game year is not counted. Seats whose pod the platform deleted are left out.
Only seats whose log is on disk are read (our own builds, and house bots we own).

These are counts. They show what goes with losing centres, not that a different stance would
have kept them: that takes an A/B. Standard library only.
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
TRUST = ("trusted", "distrusted", "no number", "no commit")
TALKS = ("both wrote", "only we wrote", "only they wrote", "silence")
CENTRE_KINDS = ("home centre", "gained centre")
# (key in a loss row, table heading, the values in print order; None = most common first)
SPLITS = (
    ("stance_before", "our stance toward the taker going in (end of the year before)", STANCES),
    ("stance_that_year", "our stance toward the taker in the year of the loss", STANCES),
    ("trust_before", "the trust we gave the taker going in", TRUST),
    ("talks", "private messages between us and the taker that year", TALKS),
    ("kind", "home centre or gained centre", CENTRE_KINDS),
    ("taker", "the power that took it", None),
    ("centre", "the centre (the ten lost most often)", None),
)


def year_of(turn: int) -> int:
    return 1901 + turn // 2


def policies_by_year(events: list[dict]) -> dict[int, dict]:
    """Game year -> the `press_policy` of the last `press_commit` of that year that carried one."""
    by_year: dict[int, dict] = {}
    for e in events:
        if e.get("event") == "press_commit" and e.get("press_policy") is not None:
            by_year[year_of(int(e["turn"]))] = e["press_policy"]
    return by_year


def stances_by_year(events: list[dict]) -> dict[int, dict[str, str]]:
    """Game year -> {POWER: stance} from the last `press_commit` of that year that carried a policy."""
    return {
        year: {str(p).upper(): str(s).lower() for p, s in (policy.get("stances") or {}).items()}
        for year, policy in policies_by_year(events).items()
    }


def stance_toward(stances: dict[int, dict[str, str]], year: int, power: str) -> str:
    if year not in stances:
        return "no commit"
    stance = stances[year].get(power, "unnamed")
    return stance if stance in STANCES else "unnamed"


def trust_toward(policies: dict[int, dict], year: int, power: str) -> str:
    if year not in policies:
        return "no commit"
    trust = {str(p).upper(): t for p, t in (policies[year].get("trust") or {}).items()}
    if not isinstance(trust.get(power), (int, float)):
        return "no number"
    return "trusted" if trust[power] >= 0.5 else "distrusted"


def talks_by_year(events: list[dict]) -> dict[int, dict[str, set]]:
    """Game year -> {POWER: {"we", "they"}}: who wrote privately to whom, from `press_out` and `press_in`."""
    talks: dict[int, dict[str, set]] = defaultdict(lambda: defaultdict(set))
    for e in events:
        if e.get("event") == "press_out" and e.get("to"):
            talks[year_of(int(e["turn"]))][str(e["to"]).upper()].add("we")
        elif e.get("event") == "press_in" and e.get("frm"):
            talks[year_of(int(e["turn"]))][str(e["frm"]).upper()].add("they")
    return talks


def talks_with(talks: dict[int, dict[str, set]], year: int, power: str) -> str:
    wrote = talks.get(year, {}).get(power, set())
    if wrote == {"we", "they"}:
        return "both wrote"
    return {"we": "only we wrote", "they": "only they wrote"}[next(iter(wrote))] if wrote else "silence"


def centres_lost(phases: list[dict], me: str) -> list[tuple[int, str, str]]:
    """(game year, centre, taker) for every centre that passed from `me` to another power."""
    lost = []
    for before, after in zip(phases, phases[1:]):
        for where, old in before["centers"].items():
            new = after["centers"].get(where)
            if old == me and new not in (None, me):
                lost.append((year_of(before["turn"]), where, new))
    return lost


def centres_taken(phases: list[dict], me: str) -> dict[int, Counter]:
    """Game year -> Counter of the powers that took a centre from `me` in that year."""
    taken: dict[int, Counter] = defaultdict(Counter)
    for year, _, taker in centres_lost(phases, me):
        taken[year][taker] += 1
    return taken


def seat_losses(phases: list[dict], me: str, events: list[dict], homes: dict[str, str]) -> list[dict]:
    """One row per centre this seat lost, with what we thought of the taker (see the module text)."""
    policies, stances, talks = policies_by_year(events), stances_by_year(events), talks_by_year(events)
    return [
        {
            "year": year,
            "centre": centre,
            "kind": "home centre" if homes.get(centre) == me else "gained centre",
            "taker": taker,
            "stance_before": stance_toward(stances, year - 1, taker),
            "stance_that_year": stance_toward(stances, year, taker),
            "trust_before": trust_toward(policies, year - 1, taker),
            "talks": talks_with(talks, year, taker),
        }
        for year, centre, taker in centres_lost(phases, me)
    ]


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


def add(total: dict, part: dict, losses: list[dict] = ()) -> None:
    for key, counter in part.items():
        total.setdefault(key, Counter()).update(counter)
    total["seats"] = total.get("seats", 0) + 1
    total.setdefault("losses", []).extend(losses)


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
                me, events = seat.power.upper(), read_log(game.logs[seat.slot])
                losses = [
                    {"episode": game.episode, "power": me, **loss}
                    for loss in seat_losses(game.phases, me, events, game.homes)
                ]
                add(totals.setdefault(seat.policy, {}), seat_counts(game.phases, me, events, going_in), losses)
    return totals, skipped


def split_table(totals: dict[str, dict], key: str, heading: str, order: tuple | None) -> list[str]:
    versions = sorted(totals)
    counts = {v: Counter(loss[key] for loss in totals[v]["losses"]) for v in versions}
    if order is None:
        overall = sum(counts.values(), Counter())
        order = [value for value, _ in sorted(overall.items(), key=lambda kv: (-kv[1], kv[0]))[:10]]
    lines = [f"## Centres lost, by {heading}", "",
             "| | " + " | ".join(versions) + " |", "|---|" + "---|" * len(versions)]
    for value in order:
        cells = []
        for v in versions:
            n, all_lost = counts[v][value], len(totals[v]["losses"])
            cells.append(f"{n} ({n / all_lost:.0%})" if all_lost else "0")
        lines.append(f"| {value} | " + " | ".join(cells) + " |")
    return lines + [""]


def render(totals: dict[str, dict], skipped: Counter, going_in: bool = False) -> str:
    versions = sorted(totals)
    lines = ["# Centres we lost: which, to whom, and what we thought of them", "",
             "seats read: " + ", ".join(f"{v} {totals[v]['seats']}" for v in versions)
             + (f"; left out: {dict(skipped)}" if skipped else ""),
             "centres lost (per seat): " + ", ".join(
                 f"{v} {len(totals[v]['losses'])} ({len(totals[v]['losses']) / totals[v]['seats']:.2f})"
                 for v in versions), ""]
    for key, heading, order in SPLITS:
        lines += split_table(totals, key, heading, order)
    lines += ["## Pair-years in which that power took a centre from us", "",
              f"| stance toward the power ({'going in' if going_in else 'that year'}) | "
              + " | ".join(versions) + " |", "|---|" + "---|" * len(versions)]
    for stance in STANCES:
        cells = []
        for v in versions:
            hit, n = totals[v]["pair_years_hit"][stance], totals[v]["pair_years"][stance]
            cells.append(f"{hit} of {n} ({hit / n:.1%})" if n else "0 of 0")
        lines.append(f"| {stance} | " + " | ".join(cells) + " |")
    lines += ["", "Counts only: what goes with a loss is not shown to cause it. \"Both wrote\" is talk, not a deal:",
              "`press_audit.py` reads what was agreed, one game at a time (`--rows` lists the games)."]
    return "\n".join(lines) + "\n"


def render_rows(totals: dict[str, dict]) -> str:
    header = ("| version | game | we played | year | centre | taker | stance going in | stance that year "
              "| trust going in | talks that year |")
    lines = [header, "|---|---|---|---|---|---|---|---|---|---|"]
    for version in sorted(totals):
        per_seat = Counter((loss["episode"], loss["power"]) for loss in totals[version]["losses"])
        ordered = sorted(totals[version]["losses"],
                         key=lambda r: (-per_seat[(r["episode"], r["power"])], r["episode"], r["power"], r["year"]))
        for r in ordered:
            lines.append(
                f"| {version} | {r['episode']} | {r['power'].title()} | {r['year']} | {r['centre']} ({r['kind']}) "
                f"| {r['taker'].title()} | {r['stance_before']} | {r['stance_that_year']} | {r['trust_before']} "
                f"| {r['talks']} |")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--policy", required=True, help="NAME for every version, NAME:vN for one")
    ap.add_argument("--variant", default="classic-press")
    ap.add_argument("--going-in", action="store_true",
                    help="pair-year table: use the stance held at the end of the year before, not that year's")
    ap.add_argument("--rows", action="store_true", help="one line per lost centre instead of the tables")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    games, _ = load_games([Path(d) for d in args.dirs], args.variant)
    totals, skipped = by_version(games, policy_matcher(args.policy), args.going_in)
    if not totals:
        print("no seats of that policy with a log on disk", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({"versions": totals, "left_out": skipped}, indent=1))
    else:
        print(render_rows(totals) if args.rows else render(totals, skipped, args.going_in), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
