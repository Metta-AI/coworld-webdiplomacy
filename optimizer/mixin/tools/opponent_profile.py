#!/usr/bin/env python3
"""Measure what one opponent policy actually does, from the public orders in replays.

    python3 games/webdiplomacy/tools/opponent_profile.py DIR... --opponent NAME[:vN]
        [--versus OURPOLICY[:vN]] [--variant classic-press] [--out PREFIX] [--episodes FILE] [--json]
    python3 games/webdiplomacy/tools/opponent_profile.py DIR... --game EPISODE_ID [--powers Turkey,Russia]
        [--years 1901-1903] [--logs] [--versus OURPOLICY[:vN] [--decisions]]

DIR is any directory holding episodes (see `webdip_episodes.py`). Every power's adjudicated
orders are public, so a rival can be profiled without its logs. The tool counts; the
opponent-profile skill says how to read the counts, which games to open and how to write
the profile down. `--opponent NAME` pools every version of NAME (the header lists them);
`NAME:vN` takes one version. Exit 2 when the opponent has no seat in DIR. Press and gunboat
are different games (press, a different last year): profile one variant at a time with
`--variant` (the ids `matchups.py` uses). Without it every variant is pooled and the header
says so.

`--out PREFIX` also saves the text (PREFIX.md) and the JSON (PREFIX.json, with `episodes`, the opponent's games, and
`episodes_read`, every game the run read, the field's included). `--episodes
FILE` reads only the listed games (a saved PREFIX.json, a saved `matchups.py --json`, or one id
per line), so a profile can be repeated, or lined up with a matchups run, while more games are
still being fetched; par and the field are then those games only.

`--game` prints one game's adjudicated orders phase by phase (all powers, or only those named),
with each order's result, retreats, builds and disbands, the centres that changed hands, each
seat's centre count by year and, with `--logs`, the path of each seat log on disk: the way to
read a game without the IDE. EPISODE_ID may be a unique prefix (`ereq_0cd0b789`). `--versus
OURPOLICY` marks our seats "(ours)" in the seat list and on their order lines. `--decisions
--versus OURPOLICY` adds, under each phase, what our own shown seats' logs say they committed
that turn: stances, trust and required orders from the reference policy's `press_policy` (no
press text). Only seats of OURPOLICY are printed, whatever logs are on disk (an account that
owns the house bots downloads every seat's log; a rival's private plan is not ours to read
into a write-up). The header names the shown seats whose logs were left out. Without
`--versus` nothing is printed and the header says why. A search build logs nothing of the kind.

A seat is one game of one power. Everything is reported **per power the opponent played**,
with the number of seats (n) beside it: the seven powers start from different boards, so
pooling them hides more than it shows. Only the order mix is also pooled. Cancelled, failed
and timed-out episodes are dropped and counted, and an episode found twice under DIR is read
once. Games where the opponent held two or more seats ("twin games") are kept and counted:
each seat is one row. Games where one of OUR seats is tainted are kept too (the opponent's
orders are still its orders), so the game count can be higher than `matchups.py`'s, which
drops them; take scores against us from `matchups.py`, not from here.

Definitions (turn 0 is Spring 1901; "year Y" means after the autumn of Y):

  opening          The opponent's full order set in Spring 1901, and in Autumn 1901. A name is
                   printed when the Spring set contains every order of a well-known opening
                   (the table `OPENINGS`); the raw orders are always printed beside it.
  distinct         Opening diversity: the number of different Spring 1901 order sets over the n
                   games at one power. Spring 1901 is the only phase that starts from the same
                   board in every game, so it is the cleanest test of scripted play. 1 of n says
                   the opening did not vary in these games (the press, the seed and the other
                   seats did); it says nothing about later phases. Orders are printed without
                   coasts, as `press_audit.py` writes them.
  order mix        Share of adjudicated movement-phase orders by type. "For another power" =
                   supports whose supported unit belongs to a different power, as a share of
                   all supports. "Failed" = moves, supports and convoys that did not succeed
                   (bounced move, cut support, broken convoy), as a share of ALL movement orders,
                   holds included (so it is not "the share of moves that bounce"). Upstream
                   marks every hold `success: false`; a hold is never counted as failed here.
  hostile act      In one movement phase, a move into, or a support for a move into, a province
                   where power Q has a unit, or a supply centre Q owns, at the start of that
                   phase (the rule of `press_audit.py`'s `attacks` predicate; supporting Q's own
                   move does not count). One exception: moving into a centre it owns itself, or
                   one of its own home centres, is taking back its own and is not counted.
                   "Centre" restricts it to supply centres Q owns.
  first target     In one game, the power (or powers, on a tie) the opponent's first hostile
                   act of the game was aimed at. "In reply" counts the games where that power
                   had already made a hostile act on the opponent in an earlier turn: there
                   the opponent was answering, not choosing a target.
  held to the end  A seat whose every unit held in each of its last 4 or more movement phases:
                   a stalled or dead bot, or a locked position. Orders cannot tell which; such
                   games are counted in the header and marked in "Episodes to open".
  takes / loses    Supply centres that changed owner between two consecutive movement-phase
                   boards. The replay does not show who owned which centre after the game's
                   LAST autumn (only the final counts, in results.json), so the last year's
                   captures are missing from these two columns and from "home centre lost".
  trajectory       Mean supply centres after each year, beside the mean for every other policy's
                   seats at the same power in the same DIRs (the field).
  par              Mean score (or final centres) of every other policy's seats at that power
                   in the same DIRs.
  top of board     Most final centres in the game, ties included.
  eliminated       Zero final centres; the year is the first with zero.
  home centre lost A home supply centre owned by another power on some board; the year is the
                   first.
  builds           Build orders in winter phases; "fleets" is the fleet share. Disbands are
                   counted separately.
  public press     Messages the power sent to everyone. Private press between other powers is
                   not in the data, so a silent row does not mean the policy does not negotiate.

With `--versus OURPOLICY`, for every game where both sat, and for every pair (their seat, our
seat): who made the first hostile act between the two, whether our power was their first
target, supports each gave the other's units, centres each took from the other, and our score
beside the field par at our power ("our vs par": our score minus the mean score of every
seat that is not ours at that power, over all DIRs), split by whether the two powers
are neighbours (`NEIGHBOURS`: powers that usually fight over shared neutrals from 1901).
Ahead, behind and level count PAIRS (a game with two of our seats is two pairs), and par here
counts every seat that is not ours, so both differ a little from `matchups.py`, which counts
games and leaves every version of our policy out of par: quote `matchups.py` for a verdict and
this section for what happened pair by pair. The JSON's `versus.pairs` has one row per pair.
The split describes these games; it mixes in which powers were drawn and who else sat at the
table, so it is a lead to check in replays, not an effect of the opponent.

"Episodes to open" lists, for each pattern, the games that show it best, as IDE links
(`/replays/<episode id>?phase=N`; N indexes the last replay frame's `history.phases`).
A link marked `[its seat tainted]` or `[another seat tainted]` is a game where a seat log
shows a taint (a crash, failing LLM calls, a deleted pod): that seat played its fallback or
nothing, so read the game with care. `[held to the end]` marks a seat that only held at the end.

The header also says which directory the games were found under (`sources`), which powers the opponent never
played, and `tables`: per power, how many different seatings (which policy held which power)
its games had. One table in every game means its neighbours never changed, and every count
at that power describes play against those neighbours only.

For your own instrument (in `instruments/`):

    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    from opponent_profile import load_games, policy_matcher, seat_facts
    games, dropped = load_games([Path("games/webdiplomacy/.runtime/artifacts")], "classic-press")
    for game in games:
        for seat in game.seats:
            if policy_matcher("some-policy")(seat.policy):
                facts = seat_facts(game, seat)

`read_episode_list(Path(".../saved.json"))` gives the `only=` set of a saved run.
`seat_facts` returns one dict per seat: episode, source, policy, power, slot, score,
final_centers, solo, top, eliminated_year, centers_by_year, taint, other_taint, table,
dislodged, openings {turn: [order text]}, orders {type: count}, orders_total, orders_failed,
supports, supports_other, supports_given {POWER: count}, first_hostile {POWER: turn},
first_centre_attack {POWER: turn}, first_targets [POWER], taken_from, lost_to {POWER|neutral:
count}, first_taken_from {POWER|neutral: turn}, captured [province], home_lost_year,
builds {army, fleet, disband}, press_messages, press_by_year, phase_index {turn: index into
history.phases}, idle_end (movement phases in a row, up to the last, with every unit holding),
units_at_end, spring_1901 [order text], rival_solo. `replying_to` [POWER] is added by
`mark_replies(facts)` once it has the facts of every seat in the game, keyed any way. Mind the case: `power` and
`table` use "Turkey"; every key written POWER above, and the powers in `game.phases`, are
upper case ("TURKEY"). `game.phases` is one dict per
movement phase: `turn`, `label`, `index`, `orders` (each `power`, `unit`, `at`, `type` of hold |
move | support_move | support_hold | convoy, `to`, `src`, `text`, `success` (null for a hold), `dislodged`), and the
boards `units` / `centers` at its start and `units_end` / `centers_end` after it (`units` is a
list of {power, unit, at}; `centers` maps province to owner). `game.logs[slot]` is the path of a
seat log on disk; `seat.log` is the loader's summary of it, not its rows. `game.between` maps a
`history.phases` index to that retreat or build phase's orders as (POWER, text) pairs, for
example ("ITALY", "retreat TRI - VIE"), ("FRANCE", "build army PAR").

What orders alone cannot show: why an order was given, what was agreed in private, whether
a move into a friend's province was arranged, and whether a hold is a plan or a crashed bot
(when its seat log is readable the header counts tainted seats; a log that says only "No logs
collected for pod" is a pod that died: the loader's taint `pod_deleted`). An LLM opponent varies from
game to game; a pattern in 3 of 4 games at one power is an observation, not a rule. Means
and rates on fewer than 16 seats at a power (the lab's floor) are directional only. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from matchups import read_episode_list, stat, variant_of
from press_audit import ABBREVIATION, movement_phases, province, public_press, turn_label
from webdip_episodes import (
    EPISODE_TAINTS,
    POWERS,
    REPLAY_NAMES,
    Seat,
    episode_dirs,
    first_existing,
    load_episode,
    read_json_file,
    read_log,
    seat_log_paths,
)

DIRECTIONAL_BELOW = 16  # seats at one power below which means and rates are directional (the lab's floor)
ORDER_KINDS = ("move", "hold", "support_move", "support_hold", "convoy")
START_CENTERS = {"Russia": 4}  # every other power starts with 3

# Powers that usually contest shared neutral centres or borders from 1901.
NEIGHBOURS = {
    "England": {"France", "Germany", "Russia"},
    "France": {"England", "Germany", "Italy"},
    "Germany": {"England", "France", "Austria", "Russia"},
    "Italy": {"France", "Austria", "Turkey"},
    "Austria": {"Germany", "Italy", "Russia", "Turkey"},
    "Turkey": {"Italy", "Austria", "Russia"},
    "Russia": {"England", "Germany", "Austria", "Turkey"},
}

# Well-known Spring 1901 openings: a name applies when every listed order was given. Names
# follow common usage (the Diplomacy opening libraries); the raw orders are always printed too.
OPENINGS = {
    "England": [
        ("Churchill opening (north, army to Edinburgh)", ("F LON - NTH", "F EDI - NWG", "A LVP - EDI")),
        ("Yorkshire opening (north, army to Yorkshire)", ("F LON - NTH", "F EDI - NWG", "A LVP - YOR")),
        ("Southern opening (fleet to the Channel)", ("F LON - ENG", "F EDI - NTH")),
    ],
    "France": [
        ("Maginot opening", ("F BRE - MAO", "A PAR - BUR", "A MAR S PAR - BUR")),
        ("Burgundy opening", ("F BRE - MAO", "A PAR - BUR", "A MAR - SPA")),
        ("Picardy opening", ("F BRE - MAO", "A PAR - PIC", "A MAR - SPA")),
        ("Gascony opening", ("F BRE - MAO", "A PAR - GAS", "A MAR - SPA")),
        ("English attack (fleet to the Channel)", ("F BRE - ENG",)),
    ],
    "Germany": [
        ("Blitzkrieg, Danish variation", ("F KIE - DEN", "A BER - KIE", "A MUN - RUH")),
        ("Blitzkrieg, Dutch variation", ("F KIE - HOL", "A BER - KIE", "A MUN - RUH")),
        ("Burgundy attack", ("A MUN - BUR",)),
    ],
    "Italy": [
        ("Lepanto opening", ("F NAP - ION", "A ROM - APU", "A VEN H")),
        ("Tyrolian attack", ("A VEN - TYR", "A ROM - VEN", "F NAP - ION")),
        ("Attack on Trieste", ("A VEN - TRI",)),
    ],
    "Austria": [
        ("Southern Hedgehog", ("F TRI - VEN", "A VIE - GAL", "A BUD - SER")),
        ("Balkan Gambit, Galician variation", ("F TRI - ALB", "A BUD - SER", "A VIE - GAL")),
        ("Balkan Gambit, Trieste variation", ("F TRI - ALB", "A BUD - SER", "A VIE - TRI")),
        ("Balkan Gambit, Budapest variation", ("F TRI - ALB", "A BUD - SER", "A VIE - BUD")),
    ],
    "Turkey": [
        ("Russian attack", ("F ANK - BLA", "A CON - BUL", "A SMY - ARM")),
        ("Byzantine opening", ("F ANK - BLA", "A CON - BUL", "A SMY - CON")),
        ("Fleet to Constantinople", ("F ANK - CON", "A CON - BUL")),
    ],
    "Russia": [
        ("Southern system", ("F SEV - BLA", "A MOS - UKR", "A WAR - GAL", "F STP - BOT")),
        ("Northern system (army to St Petersburg)", ("A MOS - STP",)),
        ("Ukraine system", ("A WAR - UKR", "A MOS - SEV")),
    ],
}

LIMITS = [
    "Orders show what was done, never why: an arranged move into a friend's province still counts as hostile.",
    "The last autumn's captures are not in the replay; 'takes', 'loses' and 'home centre lost' stop one year early.",
    "Only public press is counted. Private press between other powers is not readable.",
    f"Means and rates on fewer than {DIRECTIONAL_BELOW} seats are directional only. LLM opponents vary game to game.",
    "With one table in every game at a power, its play there is its play against those neighbours only.",
    "A profile describes these versions in these games. Date it, name the versions, and re-run after a version bump.",
]


# ---------- loading ----------


@dataclass
class Game:
    episode: str  # the episode directory name: the IDE's episode id
    variant: str  # classic-press, classic-gunboat, ... (matchups.variant_of)
    source: str  # the batch directory the episode was found in
    seats: list[Seat]
    phases: list[dict]  # press_audit.movement_phases(), each with `index` into history.phases
    builds: dict[str, Counter]  # POWER -> Counter of "Build Army" | "Build Fleet" | "Destroy"
    press: list[dict]  # public messages (raw upstream rows)
    homes: dict[str, str]  # home supply centre -> POWER
    between: dict[int, list[tuple[str, str]]]  # history.phases index -> (POWER, retreat/build/disband text)
    logs: dict[int, str]  # slot -> seat log path, for the seats whose log is on disk


def load_game(ep: Path, source: str = "") -> tuple[Game | None, str | None]:
    """(game, None), or (None, why it was left out)."""
    seats, status = load_episode(ep)
    if not seats or "replay" in status["missing"]:
        return None, "no results or no replay"
    if set(seats[0].taint) & EPISODE_TAINTS:
        return None, "cancelled, failed or timed out"
    replay = read_json_file(first_existing(ep, REPLAY_NAMES))
    last = replay[-1]
    try:
        phases = movement_phases(replay)
    except KeyError:  # a trimmed or older replay without the full upstream order rows
        return None, "replay without full order rows"
    index = {ph["turn"]: i for i, ph in enumerate(last["history"]["phases"]) if ph["phase"] == "Diplomacy"}
    for phase in phases:
        phase["index"] = index[phase["turn"]]
    builds: dict[str, Counter] = defaultdict(Counter)
    name = {t["id"]: province(ABBREVIATION[t["name"]]) for t in last["variant"]["territories"]}
    between: dict[int, list[tuple[str, str]]] = {}
    for i, ph in enumerate(last["history"]["phases"]):
        if ph["phase"] not in ("Retreats", "Builds"):
            continue
        for order in ph.get("orders") or []:
            power = POWERS[order["countryID"]].upper()
            if ph["phase"] == "Builds":
                builds[power][order["type"]] += 1
            text = f"{order['type'].lower()} {name[order['terrID']]}"
            text += f" - {name[order['toTerrID']]}" if order.get("toTerrID") else ""
            between.setdefault(i, []).append((power, text))
    starting = phases[0]["centers"] if phases else {}
    homes = {where: owner for where, owner in starting.items()}
    logs = {slot: str(path) for slot, path in seat_log_paths(ep).items()}
    return (
        Game(ep.name, variant_of(ep), source, seats, phases, dict(builds), public_press(replay), homes, between, logs),
        None,
    )


def load_games(
    roots: list[Path], variant: str | None = None, only: set[str] | None = None
) -> tuple[list[Game], Counter]:
    """Every clean episode below `roots` (of one variant, and only the ids in `only`, when given),
    and why the rest were left out."""
    games, dropped, seen = [], Counter(), set()
    for root in roots:
        for ep in episode_dirs(root):
            if ep.name in seen:
                continue
            seen.add(ep.name)
            if only is not None and ep.name not in only:
                continue
            if variant and variant_of(ep) != variant:
                dropped[f"not {variant}"] += 1
                continue
            # `<batch>/<request>/<episode>` below the root: the batch names the source.
            below = ep.relative_to(root).parts
            game, why = load_game(ep, below[0] if len(below) >= 3 else root.name)
            if game is None:
                dropped[why] += 1
            else:
                games.append(game)
    return games, dropped


def policy_matcher(spec: str):
    """`NAME` matches every version of NAME; `NAME:vN` only that version."""
    if re.search(r":v[^:]*$", spec):
        return lambda policy: policy == spec
    return lambda policy: policy == spec or policy.startswith(spec + ":v")


def family(policy: str) -> str:
    """'name:v3' -> 'name'."""
    return re.sub(r":v[^:]*$", "", policy)


def slug(policy: str) -> str:
    """'Some-Bot:v2' -> 'some-bot': the report file name."""
    name = policy.split(":v")[0].lower()
    return re.sub(r"[^a-z0-9]+", "-", name).strip("-")


def report_path(profile: dict) -> str:
    """Where the profile goes in the lab: one file per opponent and league.

    `<slug>.md` for the main league (classic-press, and when variants are pooled);
    `<slug>-gunboat.md` and the like for another variant, so the two do not overwrite each other."""
    variants = list(profile["variants"])
    suffix = ""
    if len(variants) == 1 and variants[0] != "classic-press":
        suffix = "-" + variants[0].removeprefix("classic-")
    return f"reports/opponents/{profile['slug']}{suffix}.md"


def has_press_audit(episode: str) -> bool:
    """True when the press-audit skill has already checked this game (`.runtime/press/<id>/audit.json`)."""
    return (Path(__file__).resolve().parents[1] / ".runtime" / "press" / episode / "audit.json").exists()


def replay_link(episode: str, phase_index: int | None = None) -> str:
    return f"/replays/{episode}" + (f"?phase={phase_index}" if phase_index is not None else "")


# ---------- one seat's facts ----------


def opening_name(power: str, orders: list[str]) -> str | None:
    given = set(orders)
    return next((name for name, needed in OPENINGS.get(power, []) if set(needed) <= given), None)


def result_facts(game: Game, seat: Seat) -> dict:
    """The result of one seat (cheap): what the field rows need for par and the trajectory."""
    years = sorted(seat.centers_by_year.items())
    top = max((s.final_centers or 0) for s in game.seats)
    me = seat.power.upper()
    spring = game.phases[0] if game.phases and game.phases[0]["turn"] == 0 else {"orders": []}
    return {
        "spring_1901": sorted(o["text"] for o in spring["orders"] if o["power"] == me),
        "rival_solo": any(s.solo for s in game.seats if s is not seat),
        "episode": game.episode,
        "source": game.source,
        "policy": seat.policy,
        "power": seat.power,
        "slot": seat.slot,
        "score": seat.score,
        "final_centers": seat.final_centers,
        "solo": seat.solo,
        "top": bool(seat.final_centers) and seat.final_centers == top,
        "eliminated_year": next((y for y, c in years if c == 0), None) if seat.final_centers == 0 else None,
        "centers_by_year": dict(years),
        "taint": list(seat.taint),
        "other_taint": any(s.taint for s in game.seats if family(s.policy) != family(seat.policy)),
        # Who held which power: games with the same table gave this seat the same neighbours.
        "table": " ".join(sorted(f"{s.power}={family(s.policy)}" for s in game.seats)),
        "dislodged": seat.dislodged,
    }


def hostile_to(order: dict, me: str, owner_at: dict, centers: dict, my_homes: set) -> tuple[str | None, str | None]:
    """(the power whose unit, the power whose supply centre) a move or move-support is aimed at.

    The rule of `press_audit.py`'s `attacks` predicate (a move into, or support of a move into, a
    province holding another power's unit or a supply centre it owns; supporting that power's own
    move does not count), with one exception: going into a centre this power owns, or one of its
    own home centres, is taking back its own and is not counted against the unit standing there."""
    where = order["to"]
    spared = owner_at.get(order["src"]) if order["type"] == "support_move" else None
    unit_owner, centre_owner = owner_at.get(where), centers.get(where)
    own_ground = centre_owner == me or where in my_homes
    unit_victim = unit_owner if unit_owner not in (None, me, spared) and not own_ground else None
    centre_victim = centre_owner if centre_owner not in (None, me, spared) and not own_ground else None
    return unit_victim, centre_victim


IDLE_PHASES = 4  # a seat whose units all held in its last this-many movement phases is flagged


def seat_facts(game: Game, seat: Seat) -> dict:
    """Everything measured for one seat in one game. Powers inside are upper-case names."""
    me = seat.power.upper()
    my_homes = {where for where, owner in game.homes.items() if owner == me}
    idle_run = 0  # movement phases in a row, up to the last, where every one of its units held
    kinds, supports, supports_other, failed, total = Counter(), 0, 0, 0, 0
    openings: dict[int, list[str]] = {}
    first_hostile: dict[str, int] = {}
    first_centre_attack: dict[str, int] = {}
    supports_given: Counter = Counter()
    phase_index = {}
    for phase in game.phases:
        turn = phase["turn"]
        phase_index[turn] = phase["index"]
        mine = [o for o in phase["orders"] if o["power"] == me]
        if turn in (0, 1):
            openings[turn] = sorted(o["text"] for o in mine)
        owner_at = {u["at"]: u["power"] for u in phase["units"]}
        if mine:
            idle_run = idle_run + 1 if all(o["type"] == "hold" for o in mine) else 0
        for order in mine:
            kinds[order["type"]] += 1
            total += 1
            failed += order["type"] != "hold" and not order["success"]
            if order["type"] in ("support_move", "support_hold"):
                supports += 1
                supported = owner_at.get(order["src"] if order["type"] == "support_move" else order["to"])
                if supported and supported != me:
                    supports_other += 1
                    supports_given[supported] += 1
            if order["type"] in ("move", "support_move"):
                unit_victim, centre_victim = hostile_to(order, me, owner_at, phase["centers"], my_homes)
                for victim in {unit_victim, centre_victim} - {None}:
                    first_hostile.setdefault(victim, turn)
                if centre_victim:
                    first_centre_attack.setdefault(centre_victim, turn)

    taken_from, lost_to, captured = Counter(), Counter(), []
    first_taken_from: dict[str, int] = {}  # POWER -> turn of the autumn it first took a centre from them
    home_lost_year = None
    for before, after in zip(game.phases, game.phases[1:]):
        year = 1901 + before["turn"] // 2
        for where in set(before["centers"]) | set(after["centers"]):
            old, new = before["centers"].get(where), after["centers"].get(where)
            if old == new:
                continue
            if new == me:
                taken_from[old or "neutral"] += 1
                first_taken_from.setdefault(old or "neutral", before["turn"])
                captured.append(where)
            elif old == me:
                lost_to[new or "neutral"] += 1
                if game.homes.get(where) == me and home_lost_year is None:
                    home_lost_year = year

    builds = game.builds.get(me, Counter())
    sent = [m for m in game.press if POWERS.get(m.get("fromCountryID"), "").upper() == me]
    hostile_turns = sorted(set(first_hostile.values()))
    return {
        **result_facts(game, seat),
        "openings": openings,
        "orders": dict(kinds),
        "orders_total": total,
        "orders_failed": failed,
        "supports": supports,
        "supports_other": supports_other,
        "supports_given": dict(supports_given),
        "idle_end": idle_run,
        "units_at_end": len([o for o in game.phases[-1]["orders"] if o["power"] == me]) if game.phases else 0,
        "first_hostile": first_hostile,
        "first_centre_attack": first_centre_attack,
        "first_targets": [q for q, t in first_hostile.items() if t == hostile_turns[0]] if hostile_turns else [],
        "taken_from": dict(taken_from),
        "first_taken_from": first_taken_from,
        "lost_to": dict(lost_to),
        "captured": sorted(set(captured)),
        "home_lost_year": home_lost_year,
        "builds": {"army": builds["Build Army"], "fleet": builds["Build Fleet"], "disband": builds["Destroy"]},
        "press_messages": len(sent),
        "press_by_year": dict(Counter(1901 + m["turn"] // 2 for m in sent)),
        "phase_index": phase_index,
    }


# ---------- aggregation ----------


def _mean(values) -> float | None:
    values = [v for v in values if v is not None]
    return round(statistics.mean(values), 4) if values else None


def _se(observations) -> float | None:
    """The standard error of the mean of `(episode, value)` observations, clustered by game as
    everywhere in the lab (`matchups.stat`): two seats of one policy in a game, or our one score
    paired with each of its two seats, are not independent draws. None with fewer than two games."""
    return stat(list(observations))["se"]


def _median(values) -> float | None:
    values = [v for v in values if v is not None]
    return statistics.median_low(values) if values else None


def _season(turn: int | None) -> str | None:
    return turn_label(turn) if turn is not None else None


def order_mix(rows: list[dict]) -> dict:
    total = sum(r["orders_total"] for r in rows)
    supports = sum(r["supports"] for r in rows)
    kinds = Counter()
    for r in rows:
        kinds.update(r["orders"])
    return {
        "orders": total,
        **{kind: round(kinds[kind] / total, 3) if total else None for kind in ORDER_KINDS},
        "supports": supports,
        "supports_for_another_power": round(sum(r["supports_other"] for r in rows) / supports, 3) if supports else None,
        "failed": round(sum(r["orders_failed"] for r in rows) / total, 3) if total else None,
    }


def opening_table(rows: list[dict], turn: int, power: str, field: list[dict] | None = None) -> list[dict]:
    """Order sets seen at one turn, most common first, each with the episodes that show it.

    With `field` (the other policies' seats at this power), each Spring 1901 set also says how
    many of them played the same set: an opening the whole field shares is not this opponent's."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        if turn in r["openings"]:
            groups[tuple(r["openings"][turn])].append(r)
    table = []
    for orders, group in sorted(groups.items(), key=lambda item: (-len(item[1]), item[0])):
        table.append(
            {
                "name": opening_name(power, list(orders)) if turn == 0 else None,
                "orders": list(orders),
                "n": len(group),
                "episodes": [r["episode"] for r in group],
                **(
                    {"field_same": sum(f["spring_1901"] == list(orders) for f in field), "field_n": len(field)}
                    if field is not None and turn == 0
                    else {}
                ),
            }
        )
    return table


def mark_replies(facts: dict) -> None:
    """Add `replying_to` to every seat: the powers that had made a hostile act on it in an earlier turn
    than its own first hostile act on them."""
    by_game: dict[str, dict[str, dict]] = defaultdict(dict)
    for fact in facts.values():
        by_game[fact["episode"]][fact["power"].upper()] = fact
    for fact in facts.values():
        me, table = fact["power"].upper(), by_game[fact["episode"]]
        fact["replying_to"] = [
            other for other, turn in fact["first_hostile"].items()
            if other in table and table[other]["first_hostile"].get(me, turn) < turn
        ]


def hostility(rows: list[dict]) -> dict:
    """Per other power: games with a hostile act, when it first came, and how often it came first."""
    out = {}
    for other in (p.upper() for p in POWERS.values()):
        any_turns = [r["first_hostile"][other] for r in rows if other in r["first_hostile"]]
        centre_turns = [r["first_centre_attack"][other] for r in rows if other in r["first_centre_attack"]]
        if not any_turns:
            continue
        out[other.title()] = {
            "games": len(any_turns),
            "median_first": _season(_median(any_turns)),
            "first_target_games": sum(other in r["first_targets"] for r in rows),
            "first_target_in_reply": sum(other in r["first_targets"] and other in r["replying_to"] for r in rows),
            "centre_games": len(centre_turns),
            "median_first_centre": _season(_median(centre_turns)),
        }
    return dict(sorted(out.items(), key=lambda item: (-item[1]["first_target_games"], -item[1]["games"])))


def _sum_counters(rows: list[dict], key: str) -> dict:
    total = Counter()
    for r in rows:
        total.update(r[key])
    return {k.title(): v for k, v in total.most_common()}


def trajectory(rows: list[dict], field: list[dict]) -> dict:
    out = {}
    for year in sorted({y for r in rows for y in r["centers_by_year"]}):
        mine = [r["centers_by_year"][year] for r in rows if year in r["centers_by_year"]]
        theirs = [r["centers_by_year"][year] for r in field if year in r["centers_by_year"]]
        out[year] = {"mean": _mean(mine), "n": len(mine), "field_mean": _mean(theirs), "field_n": len(theirs)}
    return out


def episodes_to_open(rows: list[dict]) -> dict[str, list[str]]:
    """For one power: the games that best show each pattern, as IDE links."""
    if not rows:
        return {}
    by_episode = {r["episode"]: r for r in rows}

    def marked_link(episode: str, phase_index: int | None = None) -> str:
        """The link, marked when a seat log in that game shows a crash or a failing LLM."""
        row = by_episode[episode]
        mark = " [its seat tainted]" if row["taint"] else " [another seat tainted]" if row["other_taint"] else ""
        mark += " [held to the end]" if row["idle_end"] >= IDLE_PHASES else ""
        return replay_link(episode, phase_index) + mark

    picks: dict[str, list[str]] = {}
    spring = opening_table(rows, 0, rows[0]["power"])
    if spring:
        picks["usual opening"] = [marked_link(e, 0) for e in spring[0]["episodes"][:2]]
        if len(spring) > 1:
            picks["unusual opening"] = [marked_link(spring[-1]["episodes"][0], 0)]
    attacked = [(min(r["first_hostile"].values()), r) for r in rows if r["first_hostile"]]
    if attacked:
        turn, r = min(attacked, key=lambda item: (item[0], item[1]["episode"]))
        picks[f"earliest attack ({turn_label(turn)} on {', '.join(q.title() for q in r['first_targets'])})"] = [
            marked_link(r["episode"], r["phase_index"].get(turn))
        ]
    targets = Counter(q for r in rows for q in r["first_targets"])
    if targets:
        (usual, most), *rest = targets.most_common()
        tied = [q.title() for q, count in rest if count == most]
        misfits = sorted((r for r in rows if usual not in r["first_targets"]), key=lambda r: r["episode"])
        if misfits:
            r = misfits[0]
            turn = min(r["first_hostile"].values()) if r["first_hostile"] else None
            aimed = ", ".join(q.title() for q in r["first_targets"]) or "nobody"
            usual_text = usual.title() + (f", tied with {', '.join(tied)}" if tied else "")
            label = (f"one of the {len(misfits)} games that do not fit the usual first target ({usual_text}); "
                     f"in this one it is first on {aimed}")
            picks[label] = [marked_link(r["episode"], r["phase_index"].get(turn))]
    best = max(rows, key=lambda r: (r["score"], r["episode"]))
    worst = min(rows, key=lambda r: (r["score"], r["episode"]))
    label = f"its best game (score {best['score']:.3f}, {best['final_centers']} centres)"
    picks[label] = [marked_link(best["episode"])]
    if worst is not best:
        label = f"its worst game (score {worst['score']:.3f}, {worst['final_centers']} centres"
        label += "; a rival soloed, which zeroes every other seat" if worst["rival_solo"] else ""
        lost = worst["home_lost_year"]
        turn = (lost - 1901) * 2 + 1 if lost else None  # the autumn its first home centre fell
        label += "; opens at the autumn its first home centre fell)" if lost else ")"
        picks[label] = [marked_link(worst["episode"], worst["phase_index"].get(turn))]
    return picks


def power_profile(power: str, rows: list[dict], field: list[dict]) -> dict:
    n = len(rows)
    par_score, par_centers = _mean(r["score"] for r in field), _mean(r["final_centers"] for r in field)
    gaps = [(r["episode"], r["score"] - par_score) for r in rows] if par_score is not None else []
    spring = opening_table(rows, 0, power, field)
    builds = Counter()
    for r in rows:
        builds.update(r["builds"])
    made = builds["army"] + builds["fleet"]
    eliminated = [r["eliminated_year"] for r in rows if r["final_centers"] == 0]
    home_lost = [r["home_lost_year"] for r in rows if r["home_lost_year"]]
    captured = Counter(where for r in rows for where in r["captured"])
    return {
        "n": n,
        "directional_only": n < DIRECTIONAL_BELOW,
        "tables": len({r["table"] for r in rows}),
        "score": _mean(r["score"] for r in rows),
        "par_score": par_score,
        "field_n": len(field),
        "score_vs_par": _mean(gap for _, gap in gaps),
        "score_vs_par_se": _se(gaps),
        "final_centers": _mean(r["final_centers"] for r in rows),
        "par_final_centers": par_centers,
        "solo": sum(r["solo"] for r in rows),
        "top_of_board": sum(r["top"] for r in rows),
        "eliminated": len(eliminated),
        "eliminated_median_year": _median(eliminated),
        "home_centre_lost": len(home_lost),
        "home_centre_lost_median_year": _median(home_lost),
        "field_home_centre_lost": sum(bool(r["home_lost_year"]) for r in field),
        "dislodged_per_game": _mean(r["dislodged"] for r in rows),
        "field_dislodged_per_game": _mean(r["dislodged"] for r in field),
        "field_order_mix": order_mix(field),
        "held_to_the_end": sum(r["idle_end"] >= IDLE_PHASES for r in rows),
        "distinct_spring_openings": len(spring),
        "spring_1901": spring,
        "autumn_1901": opening_table(rows, 1, power),
        "order_mix": order_mix(rows),
        "hostility": hostility(rows),
        "never_hostile_games": sum(not r["first_hostile"] for r in rows),
        "takes_from": _sum_counters(rows, "taken_from"),
        "loses_to": _sum_counters(rows, "lost_to"),
        "captured": {where: count for where, count in captured.most_common(8)},
        "centers_by_year": trajectory(rows, field),
        "builds": {"builds": made, "fleet_share": round(builds["fleet"] / made, 3) if made else None,
                   "disbands": builds["disband"]},
        "press": {
            "games_with_messages": sum(r["press_messages"] > 0 for r in rows),
            "messages_per_game": _mean(r["press_messages"] for r in rows),
            "by_year": dict(sorted(sum((Counter(r["press_by_year"]) for r in rows), Counter()).items())),
        },
        "episodes_to_open": episodes_to_open(rows),
    }


def versus_profile(games: list[Game], facts: dict, is_opponent, is_ours, top: int = 3) -> dict:
    """How the opponent treated our seats, over every (their seat, our seat) pair in a shared game."""
    ours_all = [f for f in facts.values() if is_ours(f["policy"])]
    field = [f for f in facts.values() if not is_ours(f["policy"])]
    par = {p: _mean(f["score"] for f in field if f["power"] == p) for p in POWERS.values()}
    pairs = []
    for game in games:
        seats = [facts[(game.episode, s.slot)] for s in game.seats]
        for them in (f for f in seats if is_opponent(f["policy"])):
            for us in (f for f in seats if is_ours(f["policy"]) and f is not them):
                theirs = them["first_hostile"].get(us["power"].upper())
                mine = us["first_hostile"].get(them["power"].upper())
                if theirs is None and mine is None:
                    first = "neither"
                elif mine is None or (theirs is not None and theirs < mine):
                    first = "them"
                elif theirs is None or mine < theirs:
                    first = "us"
                else:
                    first = "same turn"
                turn = min(t for t in (theirs, mine) if t is not None) if first != "neither" else None
                captures = [t for t in (them["first_taken_from"].get(us["power"].upper()),
                                        us["first_taken_from"].get(them["power"].upper())) if t is not None]
                capture_turn = min(captures) if captures else None
                opens_at = capture_turn if capture_turn is not None else turn
                pairs.append(
                    {
                        "episode": game.episode,
                        "their_power": them["power"],
                        "our_power": us["power"],
                        "neighbours": us["power"] in NEIGHBOURS[them["power"]],
                        "first_hostile_by": first,
                        "first_hostile_turn": turn,
                        "first_capture_turn": capture_turn,
                        # Open where a centre first changed hands between the two; failing that, at the
                        # first hostile act (which may be no more than a bounce).
                        "link": replay_link(game.episode, us["phase_index"].get(opens_at)),
                        "we_were_first_target": us["power"].upper() in them["first_targets"],
                        "their_supports_of_us": them["supports_given"].get(us["power"].upper(), 0),
                        "our_supports_of_them": us["supports_given"].get(them["power"].upper(), 0),
                        "they_took_from_us": them["taken_from"].get(us["power"].upper(), 0),
                        "we_took_from_them": us["taken_from"].get(them["power"].upper(), 0),
                        "our_score": us["score"],
                        "our_vs_par": round(us["score"] - par[us["power"]], 4) if par[us["power"]] is not None
                        else None,
                        "our_final_centers": us["final_centers"],
                        "their_score": them["score"],
                        "ours_minus_theirs": round(us["score"] - them["score"], 4),
                        "table": us["table"],
                        "several_of_ours": sum(is_ours(f["policy"]) for f in seats) > 1,
                        "tainted": bool(us["taint"] or them["taint"] or us["other_taint"]),
                        "it_soloed": them["solo"],
                        "its_seat_stalled": them["idle_end"] >= IDLE_PHASES,
                        "our_seat_stalled": us["idle_end"] >= IDLE_PHASES,
                        "our_seat_tainted": bool(us["taint"]),
                        "audited": has_press_audit(game.episode),
                    }
                )

    def summary(rows: list[dict]) -> dict:
        return {
            "pairs": len(rows),
            "tables": len({r["table"] for r in rows}),
            "ahead": sum(r["ours_minus_theirs"] > 0 for r in rows),
            "behind": sum(r["ours_minus_theirs"] < 0 for r in rows),
            "tied": sum(r["ours_minus_theirs"] == 0 for r in rows),
            "ours_minus_theirs": _mean(r["ours_minus_theirs"] for r in rows),
            "first_hostile_by": dict(Counter(r["first_hostile_by"] for r in rows).most_common()),
            "we_were_first_target": sum(r["we_were_first_target"] for r in rows),
            "median_first_hostile": _season(_median(r["first_hostile_turn"] for r in rows)),
            "pairs_where_they_supported_us": sum(r["their_supports_of_us"] > 0 for r in rows),
            "pairs_where_we_supported_them": sum(r["our_supports_of_them"] > 0 for r in rows),
            "centres_they_took_from_us": sum(r["they_took_from_us"] for r in rows),
            "centres_we_took_from_them": sum(r["we_took_from_them"] for r in rows),
            "our_score": _mean(r["our_score"] for r in rows),
            "our_vs_par": _mean(r["our_vs_par"] for r in rows),
            "our_vs_par_se": _se((r["episode"], r["our_vs_par"]) for r in rows if r["our_vs_par"] is not None),
            "their_score": _mean(r["their_score"] for r in rows),
        }

    by_powers: dict[tuple, list[dict]] = defaultdict(list)
    for r in pairs:
        by_powers[(r["their_power"], r["our_power"])].append(r)
    # The same pair with another policy in our seat: is the gap ours, or anyone's at that power?
    others_at: dict[tuple, Counter] = defaultdict(Counter)
    for game in games:
        seats = [facts[(game.episode, s.slot)] for s in game.seats]
        for them in (f for f in seats if is_opponent(f["policy"])):
            for other in (f for f in seats if not is_opponent(f["policy"]) and not is_ours(f["policy"])):
                gap = other["score"] - them["score"]
                others_at[(them["power"], other["power"])]["ahead" if gap > 0 else "behind" if gap < 0 else "tied"] += 1
    shared = {r["episode"] for r in pairs}
    # The games that say most about this opponent are those where the two fought: rank those by
    # our score minus its score. Without enough of them, fall back to every pair.
    # Neighbours that fought come first: a late brush between powers at opposite ends of the map
    # says little.
    # A game our own seat did not play (dead pod, or holding to the end) says nothing about the opponent.
    live = [r for r in pairs if not r["our_seat_stalled"] and not r["our_seat_tainted"]]
    pools = [
        ("neighbouring pairs with a hostile act between the two, our dead or stalled seats left out",
         [r for r in live if r["neighbours"] and r["first_hostile_turn"] is not None]),
        ("pairs with a hostile act between the two, our dead or stalled seats left out",
         [r for r in live if r["first_hostile_turn"] is not None]),
        ("all pairs", pairs),
    ]
    ranked_among, pool = next((name, rows) for name, rows in pools if len(rows) >= 2 * top or rows is pairs)
    ranked = sorted(pool, key=lambda r: (r["ours_minus_theirs"], r["episode"]))
    return {
        "our_versions": dict(Counter(f["policy"] for f in ours_all if f["episode"] in shared).most_common()),
        "games_with_two_of_ours": sum(
            count > 1 for count in Counter(f["episode"] for f in ours_all if f["episode"] in shared).values()
        ),
        "games_together": len({r["episode"] for r in pairs}),
        "our_seats_in_all_dirs": len(ours_all),
        "all": summary(pairs),
        "neighbours": summary([r for r in pairs if r["neighbours"]]),
        "not_neighbours": summary([r for r in pairs if not r["neighbours"]]),
        "tainted_games": summary([r for r in pairs if r["tainted"]]),
        "pairs": pairs,
        "one_of_ours": summary([r for r in pairs if not r["several_of_ours"]]),
        "several_of_ours": summary([r for r in pairs if r["several_of_ours"]]),
        "ranked_among": ranked_among,
        "by_powers": [
            {"their_power": theirs, "our_power": ours, "neighbours": ours in NEIGHBOURS[theirs], **summary(rows),
             "other_policies_at_our_power": {k: others_at[(theirs, ours)][k] for k in ("ahead", "behind", "tied")}}
            for (theirs, ours), rows in sorted(
                by_powers.items(), key=lambda item: (item[0][1] not in NEIGHBOURS[item[0][0]], -len(item[1]))
            )
        ],
        "our_worst_games": ranked[:top],
        "our_best_games": ranked[::-1][:top],
    }


def build_profile(games: list[Game], dropped: Counter, opponent: str, versus: str | None = None) -> dict:
    is_opponent = policy_matcher(opponent)
    is_ours = policy_matcher(versus) if versus else (lambda policy: False)
    facts = {(game.episode, seat.slot): seat_facts(game, seat) for game in games for seat in game.seats}
    mark_replies(facts)
    rows = [f for f in facts.values() if is_opponent(f["policy"])]
    if not rows:
        return {"error": f"no seat of {opponent}", "policies": sorted({f["policy"] for f in facts.values()})}
    field = [f for f in facts.values() if not is_opponent(f["policy"])]
    per_game = Counter(r["episode"] for r in rows)
    par = {p: _mean(f["score"] for f in field if f["power"] == p) for p in POWERS.values()}
    gaps = [(r["episode"], r["score"] - par[r["power"]]) for r in rows if par[r["power"]] is not None]
    builds = Counter()
    for r in rows:
        builds.update(r["builds"])
    made = builds["army"] + builds["fleet"]
    beside_taint = [r for r in rows if r["other_taint"]]
    profile = {
        "opponent": opponent,
        "slug": slug(opponent),
        "versions": dict(Counter(r["policy"] for r in rows).most_common()),
        "seats": len(rows),
        "games": len(per_game),
        "read_at": time.strftime("%Y-%m-%d %H:%M %Z", time.localtime()),
        "variants": dict(Counter(g.variant for g in games if g.episode in per_game).most_common()),
        "sources": dict(Counter(g.source for g in games if g.episode in per_game).most_common()),
        "not_seen_as": [p for p in POWERS.values() if not any(r["power"] == p for r in rows)],
        "episodes_dropped": dict(dropped),
        "twin_games": sum(count > 1 for count in per_game.values()),
        "tainted_seats": dict(Counter(t for r in rows for t in r["taint"])),
        "tainted_and_eliminated": sum(r["taint"] == ["exception"] and r["final_centers"] == 0 for r in rows),
        "tainted_seat_episodes": [
            {"episode": r["episode"], "power": r["power"], "taint": r["taint"]} for r in rows if r["taint"]
        ],
        "held_to_the_end": [
            {"episode": r["episode"], "power": r["power"], "phases": r["idle_end"], "units": r["units_at_end"]}
            for r in rows if r["idle_end"] >= IDLE_PHASES
        ],
        "another_seat_tainted": {
            "seats": len(beside_taint),
            "score_there": _mean(r["score"] for r in beside_taint),
            "score_elsewhere": _mean(r["score"] for r in rows if not r["other_taint"]),
        },
        "games_with_any_public_press": sum(bool(g.press) for g in games if g.episode in per_game),
        "overall": {
            "score": _mean(r["score"] for r in rows),
            "score_vs_par": _mean(gap for _, gap in gaps),
            "score_vs_par_se": _se(gaps),
            "solo": sum(r["solo"] for r in rows),
            "top_of_board": sum(r["top"] for r in rows),
            "eliminated": sum(r["final_centers"] == 0 for r in rows),
            "dislodged_per_game": _mean(r["dislodged"] for r in rows),
            "order_mix": order_mix(rows),
            "builds": {"builds": made, "fleet_share": round(builds["fleet"] / made, 3) if made else None,
                       "disbands": builds["disband"]},
        },
        "episodes": sorted(per_game),
        "episodes_read": sorted(game.episode for game in games),
        "by_power": {
            power: power_profile(power, [r for r in rows if r["power"] == power],
                                 [f for f in field if f["power"] == power])
            for power in POWERS.values()
            if any(r["power"] == power for r in rows)
        },
        "limits": LIMITS,
    }
    if versus:
        profile["versus"] = {"policy": versus, **versus_profile(games, facts, is_opponent, is_ours)}
    return profile


# ---------- text ----------


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{100 * value:.0f}%"


def _num(value: float | None, digits: int = 3) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def _signed(value: float | None, se: float | None = None) -> str:
    if value is None:
        return "-"
    return f"{value:+.3f}" + (f" ± {se:.3f} SE" if se is not None else "")


def _of(count: int, n: int) -> str:
    return f"{count}/{n}"


def _mix_line(mix: dict) -> str:
    return (
        f"move {_pct(mix['move'])} | hold {_pct(mix['hold'])} | support move {_pct(mix['support_move'])} | "
        f"support hold {_pct(mix['support_hold'])} | convoy {_pct(mix['convoy'])} of {mix['orders']} orders; "
        f"{_pct(mix['supports_for_another_power'])} of {mix['supports']} supports were for another power's unit; "
        f"failed {_pct(mix['failed'])}"
    )


def _others(counts: dict) -> str:
    """ahead-behind-level for other policies in our seat, or "-" when none sat there."""
    return "-".join(str(v) for v in counts.values()) if any(counts.values()) else "-"


def _versus_line(label: str, s: dict) -> str:
    if not s["pairs"]:
        return f"- {label}: no pairs"
    first = ", ".join(f"{who} {count}" for who, count in s["first_hostile_by"].items())
    when = f" (median {s['median_first_hostile']})" if s["median_first_hostile"] else ""
    return (
        f"- {label} (n={s['pairs']} pairs, {s['tables']} tables): we finished ahead of it in {s['ahead']}, "
        f"behind in {s['behind']}, level in {s['tied']} (mean ours minus its {_signed(s['ours_minus_theirs'])}); "
        f"first hostile act by: {first}{when}; "
        f"we were its first target in {_of(s['we_were_first_target'], s['pairs'])}; "
        f"it supported our units in {_of(s['pairs_where_they_supported_us'], s['pairs'])}, "
        f"we supported its units in {_of(s['pairs_where_we_supported_them'], s['pairs'])}; "
        f"centres it took from us {s['centres_they_took_from_us']}, we took from it {s['centres_we_took_from_them']}; "
        f"our score {_num(s['our_score'])} "
        f"(vs field par at our power {_signed(s['our_vs_par'], s['our_vs_par_se'])}); "
        f"its score {_num(s['their_score'])}"
    )


def _beside_taint_line(t: dict, seats: int) -> str:
    if not t["seats"]:
        return "seats in a game where another policy's seat was tainted: none"
    return (
        f"seats in a game where another policy's seat was tainted (crash, failing LLM or dead pod: that seat "
        f"played a fallback or nothing): {_of(t['seats'], seats)}; its score there {_num(t['score_there'])}, "
        f"elsewhere {_num(t['score_elsewhere'])}"
    )


def render(p: dict) -> str:
    o = p["overall"]
    versions = ", ".join(f"{name} ({count})" for name, count in p["versions"].items())
    lines = [
        f"# {p['opponent']}: {p['seats']} seats in {p['games']} games",
        f"versions: {versions}; read {p['read_at']}",
        "sources: " + ", ".join(f"{name} ({count} game{'' if count == 1 else 's'})"
                                for name, count in p["sources"].items()),
        "variants: " + ", ".join(f"{name} ({count} games)" for name, count in p["variants"].items())
        + (" — POOLED: press and gunboat are different games; pass --variant" if len(p["variants"]) > 1 else ""),
        f"dropped episodes: {p['episodes_dropped'] or 'none'}; twin games (it held two or more seats): "
        f"{p['twin_games']}; games where anyone sent public press: "
        f"{_of(p['games_with_any_public_press'], p['games'])} (its own messages: see Public press)",
        f"its tainted seats (from its seat log, when readable): {p['tainted_seats'] or 'none'}"
        + "".join(f"; {t['episode']} as {t['power']} ({', '.join(t['taint'])})" for t in p["tainted_seat_episodes"][:6])
        + (" … (all in the JSON)" if len(p["tainted_seat_episodes"]) > 6 else "")
        + (f". {p['tainted_and_eliminated']} with only `exception` ended with no centres: a bot that throws once "
           "its last unit is gone was still itself while it had units" if p["tainted_and_eliminated"] else ""),
        _beside_taint_line(p["another_seat_tainted"], p["seats"]),
        f"seats that only held in their last {IDLE_PHASES} or more movement phases (a stalled or dead bot, or a "
        f"locked position): {_of(len(p['held_to_the_end']), p['seats'])}"
        + "".join(f"; {h['episode']} as {h['power']} ({h['phases']} phases, {h['units']} unit"
                  f"{'' if h['units'] == 1 else 's'})" for h in p["held_to_the_end"][:6])
        + (" … (all in the JSON)" if len(p["held_to_the_end"]) > 6 else ""),
        ("never seen as: " + ", ".join(p["not_seen_as"])) if p["not_seen_as"] else "seen as every power",
        f"score {_num(o['score'])} (vs same-batch field par at the same power "
        f"{_signed(o['score_vs_par'], o['score_vs_par_se'])}) | solo {_of(o['solo'], p['seats'])} | "
        f"top of board {_of(o['top_of_board'], p['seats'])} | eliminated {_of(o['eliminated'], p['seats'])} | "
        f"dislodged {_num(o['dislodged_per_game'], 1)} times a game",
        f"order mix: {_mix_line(o['order_mix'])}",
        f"builds: {_pct(o['builds']['fleet_share'])} fleets of {o['builds']['builds']} builds; "
        f"{o['builds']['disbands']} disbands",
        "",
        "## Results by power",
        "",
        "| as | n | tables | score | par | vs par | final SCs | par SCs | solo | top | eliminated (median year) "
        "| home centre lost (median year) | dislodged a game |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    thin = False
    for power, v in p["by_power"].items():
        n = v["n"]
        thin = thin or v["directional_only"]
        elim = _of(v["eliminated"], n) + (f" ({v['eliminated_median_year']:.0f})" if v["eliminated"] else "")
        home = _of(v["home_centre_lost"], n)
        home += f" ({v['home_centre_lost_median_year']:.0f})" if v["home_centre_lost"] else ""
        home += f"; field {_of(v['field_home_centre_lost'], v['field_n'])}"
        lines.append(
            f"| {power} | {n}{'*' if v['directional_only'] else ''} | {v['tables']} | {_num(v['score'])} "
            f"| {_num(v['par_score'])} "
            f"| {_signed(v['score_vs_par'], v['score_vs_par_se'])} | {_num(v['final_centers'], 1)} "
            f"| {_num(v['par_final_centers'], 1)} | {_of(v['solo'], n)} | {_of(v['top_of_board'], n)} | {elim} "
            f"| {home} | {_num(v['dislodged_per_game'], 1)}; field {_num(v['field_dislodged_per_game'], 1)} |"
        )
    if thin:
        lines.append(f"\\* fewer than {DIRECTIONAL_BELOW} seats: means and rates are directional only; "
                     "a count such as 8 of 8 stands as what happened in those games.")
    lines.append("field = every other policy's seats at that power in these games' directories. "
                 "tables = different seatings (which policy held which power) over the n games; 1 means the same "
                 "neighbours every game.")

    lines += ["", "## Openings", "",
              "Spring 1901 starts from the same board every game, so the number of distinct order sets there is",
              "the test of scripted play. Autumn 1901 depends on what the neighbours did. An opening most of the",
              "field also plays is a shared default, not something particular to this opponent.",
              ""]
    for power, v in p["by_power"].items():
        n = v["n"]
        lines.append(f"**{power}** (n={n}): {v['distinct_spring_openings']} distinct Spring 1901 order sets")
        for row in v["spring_1901"][:4]:
            name = f"{row['name']}: " if row["name"] else ""
            shared = f"; of the field's {row['field_n']} seats at {power}, {row['field_same']} play the same set"
            lines.append(f"- {_of(row['n'], n)} {name}{'; '.join(row['orders'])} (e.g. {row['episodes'][0]}{shared})")
        if len(v["spring_1901"]) > 4:
            lines.append(f"- … {len(v['spring_1901']) - 4} more, see --json")
        autumn = v["autumn_1901"]
        if autumn:
            lines.append(f"- Autumn 1901: {len(autumn)} distinct; most common {_of(autumn[0]['n'], n)}: "
                         f"{'; '.join(autumn[0]['orders'])}")
        lines.append("")

    lines += ["## Whom it attacks", "",
              "Games with a hostile act on each power (median season of its first one in those games; the earliest",
              "of all is under Episodes to open); \"first\" counts the games",
              "where that power was its first target, and \"in reply\" how many of those came after that power had",
              "already made a hostile act on it. Two powers hit in the same first turn both count as first, so the",
              "\"first\" counts can add up to more than n. Centre = hostile acts aimed at a supply centre that power",
              "owns.",
              "",
              "| as | n | never hostile | targets, most often first |", "|---|---|---|---|"]
    for power, v in p["by_power"].items():
        cells = [
            f"{other} first {_of(h['first_target_games'], v['n'])}"
            + (f" ({h['first_target_in_reply']} in reply)" if h["first_target_in_reply"] else "")
            + f", ever {_of(h['games'], v['n'])} "
            f"(median first {h['median_first']}); centre {_of(h['centre_games'], v['n'])}"
            + (f" (median first {h['median_first_centre']})" if h["centre_games"] else "")
            for other, h in v["hostility"].items()
        ]
        lines.append(f"| {power} | {v['n']} | {_of(v['never_hostile_games'], v['n'])} | {'<br>'.join(cells) or '-'} |")

    lines += ["", "## Centres taken and lost", "",
              "Summed over the n games; the game's last autumn is not included (see Limits).", "",
              "| as | n | takes from | loses to | centres it takes (games) | builds: fleets "
              "| order mix: this opponent (the field at that power) |",
              "|---|---|---|---|---|---|---|"]
    for power, v in p["by_power"].items():
        takes = ", ".join(f"{k} {c}" for k, c in v["takes_from"].items()) or "-"
        loses = ", ".join(f"{k} {c}" for k, c in v["loses_to"].items()) or "-"
        held = ", ".join(f"{k} {c}" for k, c in v["captured"].items()) or "-"
        mix, par = v["order_mix"], v["field_order_mix"]
        lines.append(
            f"| {power} | {v['n']} | {takes} | {loses} | {held} "
            f"| {_pct(v['builds']['fleet_share'])} of {v['builds']['builds']} "
            f"| move {_pct(mix['move'])} ({_pct(par['move'])}), hold {_pct(mix['hold'])} ({_pct(par['hold'])}), "
            f"support {_pct(_add(mix))} ({_pct(_add(par))}), failed {_pct(mix['failed'])} ({_pct(par['failed'])}) |"
        )

    years = sorted({y for v in p["by_power"].values() for y in v["centers_by_year"]})
    lines += ["", "## Centre trajectory", "",
              "Mean supply centres after each year: this opponent / every other policy at the same power.", "",
              "| as | n | " + " | ".join(str(y) for y in years) + " |", "|---|---|" + "---|" * len(years)]
    for power, v in p["by_power"].items():
        cells = []
        for year in years:
            cell = v["centers_by_year"].get(year)
            cells.append(f"{_num(cell['mean'], 1)} / {_num(cell['field_mean'], 1)}" if cell else "")
        lines.append(f"| {power} | {v['n']} | " + " | ".join(cells) + " |")

    if p["games_with_any_public_press"]:
        lines += ["", "## Public press", "", "| as | n | games with a public message | messages a game | by year |",
                  "|---|---|---|---|---|"]
        for power, v in p["by_power"].items():
            press = v["press"]
            by_year = ", ".join(f"{year}: {count}" for year, count in press["by_year"].items()) or "-"
            lines.append(f"| {power} | {v['n']} | {_of(press['games_with_messages'], v['n'])} "
                         f"| {_num(press['messages_per_game'], 1)} | {by_year} |")

    if "versus" in p:
        vs = p["versus"]
        lines += ["", f"## Versus {vs['policy']}", "",
                  "our versions in the games together: "
                  + ", ".join(f"{k} ({n} seats)" for k, n in vs["our_versions"].items()),
                  f"{vs['games_together']} games together, {vs['games_with_two_of_ours']} of them with two or more "
                  "of our seats (a paired game: both sides meet a different table from a league game). A pair is "
                  "one of its seats with one of ours. \"Vs par\" is our score minus the mean score of every seat "
                  "that is not ours at the same power. These lines describe the games; the power draw and the "
                  "rest of the table are mixed in, and a first hostile act can be a bounce: open the phase. "
                  "Scores against us with a verdict: matchups.py --policy <ours> --opponent <it>.", "",
                  _versus_line("all pairs", vs["all"]),
                  _versus_line("neighbouring powers", vs["neighbours"]),
                  _versus_line("not neighbours", vs["not_neighbours"]),
                  *([_versus_line("games with one of our seats", vs["one_of_ours"]),
                     _versus_line("games with two or more of our seats (paired runs)", vs["several_of_ours"])]
                    if vs["several_of_ours"]["pairs"] else []),
                  *([f"- of these, pairs in a game where some seat is tainted (crash, failing LLM or dead pod): "
                     f"{vs['tainted_games']['pairs']}; we finished ahead of it in {vs['tainted_games']['ahead']}, "
                     f"behind in {vs['tainted_games']['behind']}"] if vs["tainted_games"]["pairs"] else []),
                  "", "Every power pair, neighbours first. \"tables\" is how many different seatings the pairs come "
                  "from: pairs from one table are near copies of one game. \"Other policies at our power\" is the "
                  "same count for its seats at that power beside any policy that is neither ours nor its own, in "
                  "these games: when they are behind it as often as we are, the gap is not about us.", "",
                  "| it plays | we play | neighbours | pairs | tables | ahead-behind-level "
                  "| other policies at our power, ahead-behind-level | ours minus its "
                  "| first hostile act by | centres it took / we took | our score | our vs par |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for row in vs["by_powers"]:
            first = ", ".join(f"{who} {count}" for who, count in row["first_hostile_by"].items())
            lines.append(f"| {row['their_power']} | {row['our_power']} | {'yes' if row['neighbours'] else 'no'} "
                         f"| {row['pairs']} | {row['tables']} | {row['ahead']}-{row['behind']}-{row['tied']} "
                         f"| {_others(row['other_policies_at_our_power'])} "
                         f"| {_signed(row['ours_minus_theirs'])} | {first} "
                         f"| {row['centres_they_took_from_us']} / {row['centres_we_took_from_them']} "
                         f"| {_num(row['our_score'])} | {_signed(row['our_vs_par'], row['our_vs_par_se'])} |")
        picks = (("Our worst games with it", "our_worst_games"), ("Our best games with it", "our_best_games"))
        for title, key in picks:
            lines += ["", f"{title} (by our score minus its score, among {vs['ranked_among']}):"]
            for r in vs[key]:
                if r["first_hostile_turn"] is None:
                    when = "the two never made a hostile act on each other: look for the cause elsewhere"
                else:
                    when = (f"first hostile act by {r['first_hostile_by']} in {turn_label(r['first_hostile_turn'])}; "
                            f"it took {r['they_took_from_us']} from us, we took {r['we_took_from_them']}")
                    when += (f"; the link opens at {turn_label(r['first_capture_turn'])}, when a centre first "
                             "changed hands between the two" if r["first_capture_turn"] is not None
                             else "; the link opens at that first act")
                marks = (" [a seat in this game is tainted]" if r["tainted"] else "") + (
                    " [press audit on disk]" if r["audited"] else "") + (
                    " [it soloed: every other seat scores 0]" if r["it_soloed"] else "") + (
                    " [its seat held to the end]" if r["its_seat_stalled"] else "") + (
                    " [OUR seat held to the end]" if r["our_seat_stalled"] else "")
                vs_par = f"{r['our_vs_par']:+.3f}" if r["our_vs_par"] is not None else "-"
                lines.append(f"- {r['link']}{marks} we {r['our_power']} (score {r['our_score']:.3f}, "
                             f"vs par {vs_par}, {r['our_final_centers']} centres), "
                             f"it {r['their_power']} (score {r['their_score']:.3f}); {when}")

    lines += ["", "## Episodes to open", ""]
    for power, v in p["by_power"].items():
        for label, links in v["episodes_to_open"].items():
            lines.append(f"- {power}, {label}: {' '.join(links)}")
    lines += ["", "## Limits", ""] + [f"- {limit}" for limit in p["limits"]]
    lines += ["", f"Write the profile to games/webdiplomacy/{report_path(p)} "
                  "(the opponent-profile skill has the format)."]
    return "\n".join(lines)


def _add(mix: dict) -> float | None:
    if mix["support_move"] is None:
        return None
    return mix["support_move"] + mix["support_hold"]


def logged_decisions(game: Game, wanted: set[str], is_ours) -> dict[int, list[str]]:
    """turn -> lines saying what each of our shown seats' own logs committed that movement turn."""
    out: dict[int, list[str]] = defaultdict(list)
    for seat in sorted(game.seats, key=lambda s: s.power):
        if seat.power.upper() not in wanted or seat.slot not in game.logs or not is_ours(seat.policy):
            continue
        for row in read_log(Path(game.logs[seat.slot])):
            policy = row.get("press_policy")
            if row.get("event") != "decision" or row.get("phase") != "Diplomacy" or not isinstance(policy, dict):
                continue
            kept = {k: policy[k] for k in ("stances", "trust", "require_orders") if policy.get(k)}
            if kept:
                out[int(row["turn"])].append(f"{seat.power} committed (its log): {json.dumps(kept)}")
    return out


def render_game(game: Game, powers: list[str] | None = None, years: tuple[int, int] | None = None,
                logs: bool = False, decisions: bool = False, ours: str | None = None) -> str:
    """One game's adjudicated movement orders, phase by phase, with results and centre counts.

    `ours` (a policy name) marks our seats "(ours)"; `decisions` prints log lines only for its seats."""
    seats = sorted(game.seats, key=lambda s: s.power)
    wanted = {p.upper() for p in powers} if powers else {s.power.upper() for s in seats}
    our_powers = {s.power.upper() for s in seats if ours and policy_matcher(ours)(s.policy)}

    def label(power: str) -> str:
        return power.title() + (" (ours)" if power.upper() in our_powers else "")

    lines = [f"# {game.episode} ({game.variant}, {game.source})", ""]
    for seat in seats:
        by_year = " ".join(f"{year}:{count}" for year, count in sorted(seat.centers_by_year.items()))
        taint = f" TAINTED {','.join(seat.taint)}" if seat.taint else ""
        lines.append(f"{seat.power:8} {seat.policy:32} score {seat.score:.3f}, {seat.final_centers} centres"
                     f"{taint}{' (ours)' if seat.power.upper() in our_powers else ''} | centres by year {by_year}")
        if logs and seat.slot in game.logs:
            lines.append(f"         seat log (slot {seat.slot}): {game.logs[seat.slot]}")
    if has_press_audit(game.episode):
        lines.append(f"press audit on disk: .runtime/press/{game.episode}/audit.json")
    committed = {}
    if decisions and not ours:
        lines.append("--decisions printed nothing: it reads only our own seats' logs, so name our policy with "
                     "--versus OURPOLICY")
    elif decisions:
        is_ours = policy_matcher(ours)
        committed = logged_decisions(game, wanted, is_ours)
        shown = [s for s in seats if s.power.upper() in wanted]
        if not any(is_ours(s.policy) for s in shown):
            lines.append(f"--decisions printed nothing: no shown seat is a seat of {ours}")
        left_out = [s.power for s in shown if s.slot in game.logs and not is_ours(s.policy)]
        if left_out:
            lines.append(f"--decisions: seat logs on disk for {', '.join(left_out)} were left out (not seats of "
                         f"{ours})")
    next_index = [phase["index"] for phase in game.phases[1:]] + [10**6]
    for i, phase in enumerate(game.phases):
        if years and not years[0] <= 1901 + phase["turn"] // 2 <= years[1]:
            continue
        lines += ["", f"## {phase['label']}  ({replay_link(game.episode, phase['index'])})"]
        for power in sorted(wanted):
            mine = [o for o in phase["orders"] if o["power"] == power]
            if not mine:
                continue
            shown = []
            for o in mine:
                failed = o["type"] != "hold" and not o["success"]
                shown.append(o["text"] + (" (dislodged)" if o["dislodged"] else " (failed)" if failed else ""))
            lines.append(f"{label(power):8} " + "; ".join(shown))
        lines += committed.get(phase["turn"], [])
        if i + 1 < len(game.phases):
            before, after = phase["centers"], game.phases[i + 1]["centers"]
            changes = [
                f"{where} {(before.get(where) or 'neutral').title()} -> {(after.get(where) or 'neutral').title()}"
                for where in sorted(set(before) | set(after))
                if before.get(where) != after.get(where)
            ]
            if changes:
                lines.append("centres changed: " + ", ".join(changes))
        # Retreats and builds adjudicated after this movement phase and before the next one.
        after_phase = [
            f"{label(power)} {text}"
            for index in sorted(game.between)
            if phase["index"] < index < next_index[i]
            for power, text in game.between[index]
            if power in wanted
        ]
        if after_phase:
            lines.append("then: " + "; ".join(after_phase))
    lines += ["", "An army ordered to a province it does not border is a convoyed move. "
                  "The owner of each centre after the last autumn is not in the replay; the final counts above are "
                  "from results.json. A seat log holds that seat's `decision` lines (read it with "
                  "webdip_episodes.read_log) and, in a press game, its private press: keep both out of tracked files."]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dirs", nargs="+", metavar="DIR")
    ap.add_argument("--opponent", help="NAME (every version) or NAME:vN")
    ap.add_argument("--game", metavar="EPISODE_ID", help="print this game's orders phase by phase instead")
    ap.add_argument("--powers", help="with --game: only these powers, comma-separated (for example Turkey,Russia)")
    ap.add_argument("--years", help="with --game: only these years, for example 1901-1903 or 1904")
    ap.add_argument("--logs", action="store_true", help="with --game: print each seat's log path when it is on disk")
    ap.add_argument("--decisions", action="store_true",
                    help="with --game and --versus: under each phase, the stances, trust and required orders our own "
                         "shown seats logged (other seats' logs are never printed)")
    ap.add_argument("--out", metavar="PREFIX", help="also write PREFIX.md (the text) and PREFIX.json from this read")
    ap.add_argument("--episodes", metavar="FILE", help="only the episode ids in FILE: a PREFIX.json from --out, a "
                    "saved `matchups.py --json`, or one id per line. Repeats a "
                    "run on the same games while more are being fetched")
    ap.add_argument("--versus", help="our policy, NAME or NAME:vN: how the opponent treated our seats; with --game, "
                                     "marks our seats (ours), and with --decisions, the policy whose seat logs "
                                     "are printed")
    ap.add_argument("--variant", help="only this variant, for example classic-press or classic-gunboat")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    roots = [Path(d) for d in args.dirs]
    if args.game:
        matches = sorted({ep.name for root in roots for ep in episode_dirs(root) if ep.name.startswith(args.game)})
        games, _ = load_games(roots, only=set(matches)) if len(matches) == 1 else ([], None)
        if not games:
            why = f"{len(matches)} episodes start with" if len(matches) > 1 else "no readable episode"
            print(json.dumps({"error": f"{why} {args.game} under {', '.join(args.dirs)}", "matches": matches[:10]}))
            return 2
        powers = [p.strip().title() for p in args.powers.split(",")] if args.powers else None
        years = [int(y) for y in args.years.split("-")] if args.years else None
        print(render_game(games[0], powers, (years[0], years[-1]) if years else None, args.logs, args.decisions,
                          args.versus))
        return 0
    if not args.opponent:
        ap.error("--opponent NAME or --game EPISODE_ID is required")
    games, dropped = load_games(roots, args.variant, read_episode_list(Path(args.episodes)) if args.episodes else None)
    profile = build_profile(games, dropped, args.opponent, args.versus)
    if "error" in profile:
        print(json.dumps(profile))
        return 2
    if args.out:
        Path(args.out + ".md").write_text(render(profile) + "\n")
        Path(args.out + ".json").write_text(json.dumps(profile, indent=1) + "\n")
    print(json.dumps(profile, indent=1) if args.json else render(profile))
    return 0


if __name__ == "__main__":
    sys.exit(main())
