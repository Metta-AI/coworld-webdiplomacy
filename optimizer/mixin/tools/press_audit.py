#!/usr/bin/env python3
"""Check what was said in a press game against what was done.

    python3 games/webdiplomacy/tools/press_audit.py extract EPISODE_DIR --policy NAME:vN --out DIR
    python3 games/webdiplomacy/tools/press_audit.py check DIR      (the annotator's format test: no verdicts)
    python3 games/webdiplomacy/tools/press_audit.py verify DIR
    python3 games/webdiplomacy/tools/press_audit.py report DIR

Three steps. Steps 1 and 3 are code; step 2 is done by an agent (the press-audit skill
says how, and recommends a sub-agent per game).

1. `extract` writes `DIR/ledger.json` for ONE of our seats: every press message that seat
   could see (private messages it sent or received, and public press), every movement
   phase's adjudicated orders and board in standard notation, and what our policy believed
   about each power that turn (from its own seat log). It also writes `DIR/annotate.json`, the
   same press with each turn's STARTING board and no orders or results, and `DIR/claims.json`,
   one empty entry per message, for step 2 to fill in (a `claims.json` already there is kept;
   `--force` starts it again). `--slot N` picks the seat when the policy holds more than one.
   `--by-year` also writes `DIR/annotate-1901.json`, `annotate-1902.json`, ...: the same content
   as `annotate.json`, one game year per file, for a reader that cannot take a full game's
   `annotate.json` in one read (they are listed under `annotate_by_year` in the output).
2. An agent reads `annotate.json` and lists each message's claims in `DIR/claims.json` using the
   small vocabulary below. It records what was SAID; it does not judge whether it came true, and
   it does not see how any turn came out.
3. `verify` checks every claim against the adjudicated orders and writes `DIR/audit.json`:
   per message, per claim: was the condition met, was the promise kept, the threat carried
   out, the statement true; and whether we relied on it. It prints, per power,
   `claims_without_requests` (that power's own promises, threats, statements and proposals,
   those that cannot be checked included) beside `requests_made`; the two add up to the claim
   count `check` prints. A request is weighed against the power asked (`asked`, `complied`),
   not the power that made it. In `audit.json` an order's `success` is null for a hold, which
   cannot succeed or fail. `report` renders `DIR/audit.html`,
   one self-contained page (it holds private press: keep it on your machine).

A claim in `claims.json` (the press-audit skill has the full rules and examples):

    {"kind": "promise" | "threat" | "request" | "statement" | "proposal",
     "quote": "I keep PRU/SIL quiet",    # the words in the message
     "turns": [1, 1],                    # first and last game turn covered (0 = Spring 1901);
                                         # omit for "the turn it was said in". The code adds no
                                         # turns of its own: an open-ended claim must be written
                                         # with its range
     "condition": [<predicate>, ...],    # optional: "if you ...". All must hold
     "commitment": [<predicate>, ...],   # what is promised, threatened, asked, asserted or offered
     "asked": "RUSSIA",                  # requests in a public message only: who is asked
     "to": "FRANCE",                     # optional: whom it was promised to, when not the message's
                                         # recipient ("as agreed with France, I stay out of BUR")
     "replaces": ["prv-82#1"],           # optional: earlier claims BY THE SAME SENDER that this one takes
                                         # the place of ("prv-82" = all of that message's claims)
     "context": "to prv-209: hold VIE"}  # optional: the annotator's own note; `quote` is the message's words

`verify` refuses a `quote` that does not occur in its message ("..." may stand for words left out).

The speaker is always the message's sender, and it is the sender's word that is weighed.
- promise: the sender will or will not do something, perhaps only if `condition` holds.
  Kept or broken; released when the condition was not met; "attempted" when the order was given
  and failed.
- threat: the sender will do `commitment` if `condition` happens. Carried out or a bluff;
  not triggered when the condition did not happen.
- statement: the sender asserts a fact about the board or anyone's orders. True or false.
- request: the sender asks the addressee to do or not do `commitment`. Complied or refused.
  It is counted against the power asked, not the sender.
- proposal: an offer not yet agreed ("shall we keep Galicia empty?"). The commitment is the
  sender's own side; followed or not. It does not count for or against the sender's honesty.
A message with no claim keeps an empty list.

Predicates (provinces are three-letter abbreviations, powers are upper-case names):

    {"p": "order", "power": P, "order": "A BUD - SER"}        P gave this order
    {"p": "moves_to", "power": P, "province": "TYR"}          P ordered a unit into TYR ("unit": "TRI" = that unit)
    {"p": "holds", "power": P, "province": "DEN"}             P's unit in DEN was not ordered to move
    {"p": "leaves", "power": P, "province": "TRI"}            P's unit in TRI was ordered to move
    {"p": "supports", "power": P, "of": Q, "province": "X", "kind": "move" | "hold", "unit": "BAL"}
                                                              P supported a unit. Optional: of Q; into or in X;
                                                              kind; only by P's unit in BAL
    {"p": "attacks", "power": P, "target": Q, "what": "unit" | "centre", "unit": "ALB",
     "how": "move" | "support"}
                                                              P moved on, or supported a move on, Q's units or centres
                                                              (`what`, `how` narrow it; `unit` = that unit of P's)
    {"p": "attacks", "power": P, "provinces": ["SER", "RUM"]} the same, for a list of provinces
                                                              (P supporting the move of the power the claim was made
                                                              to into the province is not an attack; "spare": Q
                                                              names another power to spare)
    {"p": "dislodged", "power": P, "province": "RUH"}         P's unit in RUH was dislodged
    {"p": "unit_at", "power": P, "province": "PRU", "when": "start" | "end"}
    {"p": "owns", "power": P, "province": "DEN", "when": "start" | "end"}
    {"p": "centers", "power": P, "count": 9, "when": ...}     P owns exactly 9 centres (or "at_least": 9)
    {"not": <predicate>}        {"any": [<predicate>, ...]}        {"all": [<predicate>, ...]}
    {"p": "unverifiable", "why": "about intentions"}          cannot be checked against orders

Over a window of several turns a predicate holds if it holds in any movement phase of the
window, and `not` holds only if it never does. Several things to be ordered together must be
ordered in the same turn. A predicate about one unit ("my army in SEV holds") is not checkable
in a turn where that unit does not exist. `"success": true` on `order`, `moves_to`, `leaves` or
`attacks` requires that the move worked; `"success": false` that it was ordered and failed
(a bounce). In a promise, threat, request or proposal an order that was given and failed counts
as "attempted", not broken: those are about what will be ORDERED. `when` defaults to "end".

Rules `verify` applies after checking the orders (each from a false alarm in real games):
- A statement about another power's orders in a turn not yet played is a forecast
  (forecast_right / forecast_wrong), not the speaker's word. A wrong statement about turns
  already played is "misstated": everyone can read those orders off the board.
- A claim `replaced` by a later claim ends at the turn before that message. The later claim
  must be the same sender's, said to the same party, or come from the party the promise was
  made to (letting it go). A broken promise whose every breaking order the speaker announced to
  the same party, or the other party asked for, in a later message before the orders went in is
  "superseded" too.
- "released_by_them": a pledge of peace ("I will not move on X") broken only after the other
  party attacked the speaker earlier in its window; or a promise broken only after the other
  party had, in an earlier turn, not done what the same message asked of it (the other half
  of the deal).
- A promise made to another power (`to`) is kept_to_other / broken_to_other, never a betrayal.
- "changed_plans" / "we_changed_plans": the only thing broken was "this unit will stay put",
  and the speaker made no move on the party it was said to.
- "our_attack_announced" / "our_attack_not_made": we told a power we would move on it.
  "attack_announced" / "attack_not_made": a power told us it would move on us. Neither is a
  promise anyone relied on.
- "doubted_wrongly" (perhaps a missed alliance) needs: a pledge not to move on us, kept; the
  speaker could have broken it (a unit able to move into what it protects); the speaker did not
  move on us in the window or the turn before; we moved on the speaker in the window; and we
  had not broken our own word to that power in those turns. Otherwise kept_but_attacked_us or
  kept_despite_doubt. Every claim made to us lists `attacks_on_us` and `our_attacks_on_them`.

A flag is a lead, not a count to quote: read its evidence first. The kinds of false alarm are
in the press-audit skill.

What "relied on" means: our policy's committed press policy for that turn named the
sender an ally, gave it trust of 0.5 or more, or expected orders from it. A hostile (or enemy) stance
or trust below 0.5 means we did not rely on it. With neither, `relied` is null. Policies
that do not log a press policy always get null.

Standard library only.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from collections import Counter
from pathlib import Path

from press_report import render_report
from webdip_episodes import REPLAY_NAMES, first_existing, load_episode, read_json_file, read_log, seat_log_paths

POWER = {1: "ENGLAND", 2: "FRANCE", 3: "ITALY", 4: "GERMANY", 5: "AUSTRIA", 6: "TURKEY", 7: "RUSSIA"}
# webDiplomacy's Classic territory names -> standard abbreviations (the same table the
# reference policy uses; a test keeps the two equal).
ABBREVIATION = {
    "Clyde": "CLY",
    "Edinburgh": "EDI",
    "Liverpool": "LVP",
    "Yorkshire": "YOR",
    "Wales": "WAL",
    "London": "LON",
    "Portugal": "POR",
    "Spain": "SPA",
    "North Africa": "NAF",
    "Tunis": "TUN",
    "Naples": "NAP",
    "Rome": "ROM",
    "Tuscany": "TUS",
    "Piedmont": "PIE",
    "Venice": "VEN",
    "Apulia": "APU",
    "Greece": "GRE",
    "Albania": "ALB",
    "Serbia": "SER",
    "Bulgaria": "BUL",
    "Rumania": "RUM",
    "Constantinople": "CON",
    "Smyrna": "SMY",
    "Ankara": "ANK",
    "Armenia": "ARM",
    "Syria": "SYR",
    "Sevastopol": "SEV",
    "Ukraine": "UKR",
    "Warsaw": "WAR",
    "Livonia": "LVN",
    "Moscow": "MOS",
    "St. Petersburg": "STP",
    "Finland": "FIN",
    "Sweden": "SWE",
    "Norway": "NWY",
    "Denmark": "DEN",
    "Kiel": "KIE",
    "Berlin": "BER",
    "Prussia": "PRU",
    "Silesia": "SIL",
    "Munich": "MUN",
    "Ruhr": "RUH",
    "Holland": "HOL",
    "Belgium": "BEL",
    "Picardy": "PIC",
    "Brest": "BRE",
    "Paris": "PAR",
    "Burgundy": "BUR",
    "Marseilles": "MAR",
    "Gascony": "GAS",
    "Barents Sea": "BAR",
    "Norwegian Sea": "NWG",
    "North Sea": "NTH",
    "Skagerrack": "SKA",
    "Heligoland Bight": "HEL",
    "Baltic Sea": "BAL",
    "Gulf of Bothnia": "BOT",
    "North Atlantic Ocean": "NAO",
    "Irish Sea": "IRI",
    "English Channel": "ENG",
    "Mid-Atlantic Ocean": "MAO",
    "Western Mediterranean": "WES",
    "Gulf of Lyons": "LYO",
    "Tyrrhenian Sea": "TYS",
    "Ionian Sea": "ION",
    "Adriatic Sea": "ADR",
    "Aegean Sea": "AEG",
    "Eastern Mediterranean": "EAS",
    "Black Sea": "BLA",
    "Tyrolia": "TYR",
    "Bohemia": "BOH",
    "Vienna": "VIE",
    "Trieste": "TRI",
    "Budapest": "BUD",
    "Galicia": "GAL",
    "Spain (North Coast)": "SPA/NC",
    "Spain (South Coast)": "SPA/SC",
    "St. Petersburg (North Coast)": "STP/NC",
    "St. Petersburg (South Coast)": "STP/SC",
    "Bulgaria (North Coast)": "BUL/EC",
    "Bulgaria (South Coast)": "BUL/SC",
}
KINDS = ("promise", "threat", "request", "statement", "proposal")
SPEAKERS_WORD = ("promise", "threat", "statement")  # the kinds that put the speaker's honesty on the line
ORDER_TYPES = {
    "Hold": "hold",
    "Move": "move",
    "Support hold": "support_hold",
    "Support move": "support_move",
    "Convoy": "convoy",
}
RELY_TRUST = 0.5  # trust at or above this counts as relying on a power's word
# Stances that mean "we did not rely on this power". The reference policy logs "hostile"
# (press/HARNESS.md); "enemy" is kept for policies that use that word.
DISTRUST_STANCES = ("hostile", "enemy")
# outcome -> did the words match the deeds (None = says nothing about honesty)
HONEST = {"kept": True, "carried_out": True, "true": True, "attempted": True,
          "broken": False, "not_carried_out": False, "false": False}  # fmt: skip
# The kinds where the words are about what someone will ORDER. For these an order that was given
# and then bounced, was cut or was dislodged still did what was said: outcome "attempted".
INTENT_KINDS = ("promise", "threat", "request", "proposal")


def province(location: str) -> str:
    """'STP/SC' -> 'STP': claims talk about provinces, not coasts."""
    return location.split("/")[0].upper()


def turn_label(turn: int) -> str:
    return f"{'Spring' if turn % 2 == 0 else 'Autumn'} {1901 + turn // 2}"


# ---------- step 1: the ledger ----------


def order_text(order: dict) -> str:
    unit = f"{order['unit']} {order['at']}"
    kind = order["type"]
    if kind == "hold":
        return f"{unit} H"
    if kind == "move":
        return f"{unit} - {order['to']}"
    if kind == "support_hold":
        return f"{unit} S {order['to']}"
    verb = "S" if kind == "support_move" else "C"
    return f"{unit} {verb} {order['src']} - {order['to']}"


def movement_phases(replay: list) -> list[dict]:
    """One entry per adjudicated movement phase: orders, units and centre owners at its start."""
    last = replay[-1]
    name = {t["id"]: ABBREVIATION[t["name"]] for t in last["variant"]["territories"]}
    supply = {t["id"] for t in last["variant"]["territories"] if t["supply"] and t.get("coast") != "Child"}
    phases = []
    for ph in last["history"]["phases"]:
        if ph["phase"] != "Diplomacy" or not ph.get("orders"):
            continue
        orders = []
        for o in ph["orders"]:
            if o["type"] not in ORDER_TYPES:
                continue
            orders.append(
                {
                    "power": POWER[o["countryID"]],
                    "unit": "A" if o["unitType"] == "Army" else "F",
                    "at": province(name[o["terrID"]]),
                    "type": ORDER_TYPES[o["type"]],
                    "to": province(name[o["toTerrID"]]) if o.get("toTerrID") else None,
                    "src": province(name[o["fromTerrID"]]) if o.get("fromTerrID") else None,
                    # Upstream marks every hold `success: false`. A hold cannot succeed or fail.
                    "success": None if ORDER_TYPES[o["type"]] == "hold" else bool(o.get("success")),
                    "dislodged": bool(o.get("dislodged")),
                }
            )
        for o in orders:
            o["text"] = order_text(o)
        phases.append(
            {
                "turn": ph["turn"],
                "label": turn_label(ph["turn"]),
                "orders": orders,
                "units": [
                    {
                        "power": POWER[u["countryID"]],
                        "unit": "A" if u["type"] == "Army" else "F",
                        "at": province(name[u["terrID"]]),
                    }
                    for u in ph.get("units") or []
                ],
                "centers": {
                    province(name[c["terrID"]]): POWER[c["countryID"]]
                    for c in ph.get("centers") or []
                    if c["terrID"] in supply and c.get("countryID")
                },
            }
        )
    # The board after a phase is the next movement phase's starting board (retreats and builds
    # applied). The last phase has no later board in the public history, so it keeps its own.
    for i, phase in enumerate(phases):
        later = phases[i + 1] if i + 1 < len(phases) else phase
        phase["units_end"], phase["centers_end"] = later["units"], later["centers"]
        phase["end_known"] = i + 1 < len(phases)  # claims about the board after the last turn are not checked
    return phases


def province_borders(replay: list) -> dict[str, dict[str, list[str]]]:
    """{"A": province -> the provinces an army there can move to, "F": the same for a fleet}
    (coasts folded into their province)."""
    territories = replay[-1]["variant"]["territories"]
    name = {t["id"]: province(ABBREVIATION[t["name"]]) for t in territories}
    touching: dict[str, dict[str, set[str]]] = {"A": {}, "F": {}}
    for territory in territories:
        here = name[territory["id"]]
        for border in territory.get("borders") or []:
            for unit, key in (("A", "army"), ("F", "fleet")):
                if border.get(key) and name[border["id"]] != here:
                    touching[unit].setdefault(here, set()).add(name[border["id"]])
    return {unit: {where: sorted(others) for where, others in sorted(reach.items())}
            for unit, reach in touching.items()}  # fmt: skip


def private_press(rows: list[dict]) -> list[dict]:
    """The launcher's end-of-game archive of this seat's private messages, from its seat log."""
    for row in reversed(rows):
        if row.get("event") == "private_press":
            return (row.get("archive") or {}).get("messages") or []
    return []


def public_press(replay: list) -> list[dict]:
    seen = {}
    for frame in replay:
        for message in (frame.get("messages") or {}).get("messages") or []:
            seen[message.get("id") or (message.get("timeSent"), message.get("message"))] = message
    return list(seen.values())


def applies_to_turn(message: dict) -> int:
    """Press in a movement phase is about that turn's orders; press during retreats or builds
    is about the next movement turn."""
    return message["turn"] if message["phase"] == "Diplomacy" else message["turn"] + 1


def ledger_messages(private: list[dict], public: list[dict], our_power: str) -> list[dict]:
    out = []
    for raw, is_public in [(m, False) for m in private] + [(m, True) for m in public]:
        sender = POWER.get(raw.get("fromCountryID"))
        if sender is None:  # system notices
            continue
        to = "ALL" if is_public or not raw.get("toCountryID") else POWER[raw["toCountryID"]]
        out.append(
            {
                "id": f"{'pub' if to == 'ALL' else 'prv'}-{raw['id']}",
                "turn": applies_to_turn(raw),
                "sent_in": f"{turn_label(raw['turn'])} {raw['phase']}",
                "time": raw.get("timeSent", 0),
                "from": sender,
                "to": to,
                "direction": "out" if sender == our_power else "in",
                # Upstream stores a line break as "<br />": a reader (and the annotator) gets a new line.
                "text": html.unescape(re.sub(r"<br\s*/?>", "\n", raw.get("message") or "")),
            }
        )
    unique = {m["id"]: m for m in out}
    return sorted(unique.values(), key=lambda m: (m["turn"], m["time"], m["id"]))


def beliefs(rows: list[dict]) -> dict[int, dict]:
    """turn -> the press policy our bot committed that turn (the last one), when it logs one."""
    by_turn = {}
    for row in rows:
        if row.get("event") in ("press_commit", "decision") and isinstance(row.get("press_policy"), dict):
            if row.get("event") == "decision" and row.get("phase") != "Diplomacy":
                continue
            by_turn[int(row["turn"])] = row["press_policy"]
    return by_turn


def build_ledger(episode_dir: Path, slot: int) -> dict:
    seats, status = load_episode(episode_dir)
    seat = next((s for s in seats if s.slot == slot), None)
    if seat is None:
        raise ValueError(f"no seat {slot} in {episode_dir} (missing: {status['missing']})")
    replay_path = first_existing(episode_dir, REPLAY_NAMES)
    if replay_path is None:
        raise ValueError(f"no replay in {episode_dir}")
    replay = read_json_file(replay_path)
    log_path = seat_log_paths(episode_dir).get(slot)
    if log_path is None:
        raise ValueError(f"no seat log for slot {slot} in {episode_dir}: private press is only in our own seat's log")
    rows = read_log(log_path)
    our_power = seat.power.upper()
    by_turn = beliefs(rows)
    phases = movement_phases(replay)
    for phase in phases:
        phase["belief"] = by_turn.get(phase["turn"])
    return {
        "episode": status["episode_id"],
        "episode_dir": str(episode_dir),
        "slot": slot,
        "policy": seat.policy,
        "our_power": our_power,
        "score": seat.score,
        "outcome": seat.outcome,
        # A bot that only ever logs an empty press policy has told us nothing about its stance.
        "belief_logged": any(by_turn.values()),
        "borders": province_borders(replay),
        "phases": phases,
        "messages": ledger_messages(private_press(rows), public_press(replay), our_power),
    }


def annotator_view(ledger: dict) -> dict:
    """What the annotating agent reads: the press, and the board at the START of each movement
    turn (to resolve "my fleet", "your army in Warsaw"). No orders and no results, so the reading
    of a message cannot be bent by how the turn came out. `verify` reads `ledger.json`, not this.

    One leak remains and is accepted: the next turn's starting board shows where units ended up."""
    by_turn: dict[int, list[dict]] = {}
    for message in ledger["messages"]:
        by_turn.setdefault(message["turn"], []).append(
            {k: message[k] for k in ("id", "sent_in", "from", "to", "direction", "text")})
    boards = {p["turn"]: p for p in ledger["phases"]}
    turns = []
    for turn in sorted(set(by_turn) | set(boards)):
        board = boards.get(turn)
        turns.append({
            "turn": turn,
            "label": turn_label(turn),
            "units_at_start": sorted(f"{u['power']} {u['unit']} {u['at']}" for u in board["units"]) if board else None,
            "centres_at_start": board["centers"] if board else None,
            "messages": by_turn.get(turn, []),
        })  # fmt: skip
    return {
        "read_me": "Press seen from our seat, turn by turn, with the board at the start of each turn. "
                   "A message's claims default to the turn it is listed under. Work through the turns in order.",
        "our_power": ledger["our_power"],
        "turns": turns,
    }


def annotator_views_by_year(view: dict) -> dict[int, dict]:
    """`annotator_view` cut into one view per game year, for a reader that cannot take it in one read."""
    years: dict[int, list[dict]] = {}
    for turn in view["turns"]:
        years.setdefault(1901 + turn["turn"] // 2, []).append(turn)
    return {year: {**view, "read_me": view["read_me"] + f" This file holds {year} only; read the years in order.",
                   "turns": turns}
            for year, turns in sorted(years.items())}


# ---------- step 3: checking claims ----------


def parse_order(text: str) -> dict:
    """'A BUD - SER', 'F DEN H', 'A PRU S A WAR - SIL', 'F NTH C A LON - NWY', 'A MUN S A BER'."""
    spaced = text.upper().replace("->", "-").replace("-", " - ").replace("VIA", "")
    tokens = [t for t in spaced.split() if t not in ("A", "F")]
    if not tokens:
        raise ValueError(f"empty order {text!r}")
    at = province(tokens[0])
    rest = tokens[1:]
    if not rest or rest in (["H"], ["HOLD"], ["HOLDS"]):
        return {"at": at, "type": "hold"}
    if rest[0] == "-" and len(rest) == 2:
        return {"at": at, "type": "move", "to": province(rest[1])}
    if rest[0] == "S" and len(rest) == 2:
        return {"at": at, "type": "support_hold", "to": province(rest[1])}
    if rest[0] in ("S", "C") and len(rest) == 4 and rest[2] == "-":
        kind = "support_move" if rest[0] == "S" else "convoy"
        return {"at": at, "type": kind, "src": province(rest[1]), "to": province(rest[3])}
    raise ValueError(f"cannot read order {text!r}")


def owner_of_unit(phase: dict, where: str) -> str | None:
    return next((u["power"] for u in phase["units"] if u["at"] == where), None)


def holdings(power: str, phase: dict) -> set[str]:
    """Where `power` has a unit or owns a centre at the start of the phase."""
    held = {u["at"] for u in phase["units"] if u["power"] == power}
    return held | {where for where, owner in phase["centers"].items() if owner == power}


def attacked_provinces(pred: dict, phase: dict) -> set[str]:
    """Where a move would count as an attack: the listed provinces, or the target's units and centres."""
    if pred.get("provinces"):
        return {province(p) for p in pred["provinces"]}
    target, what = pred["target"], pred.get("what", "any")
    hit = set()
    if what in ("any", "unit"):
        hit |= {u["at"] for u in phase["units"] if u["power"] == target}
    if what in ("any", "centre"):
        hit |= {where for where, owner in phase["centers"].items() if owner == target}
    return hit


def unit_named(pred: dict) -> str | None:
    """The province of the one unit a predicate is about, when it names one."""
    kind = pred.get("p")
    if kind in ("holds", "leaves", "dislodged"):
        return province(pred["province"])
    if kind == "order":
        return parse_order(pred["order"])["at"]
    if kind in ("moves_to", "supports", "attacks") and pred.get("unit"):
        return province(pred["unit"])
    return None


def matching_orders(pred: dict, phase: dict, intent: bool = False) -> list[dict]:
    """The orders in one movement phase that make an order-type predicate true.

    `intent`: read `"success": true` as "was ordered" (see INTENT_KINDS)."""
    kind, power = pred["p"], pred.get("power")
    mine = [o for o in phase["orders"] if o["power"] == power]
    if kind == "order":
        want = parse_order(pred["order"])
        found = [o for o in mine if all(o.get(k) == v for k, v in want.items())]
    elif kind == "moves_to":
        found = [o for o in mine if o["type"] == "move" and o["to"] == province(pred["province"])]
        if pred.get("unit"):
            found = [o for o in found if o["at"] == province(pred["unit"])]
    elif kind == "holds":
        found = [o for o in mine if o["at"] == province(pred["province"]) and o["type"] != "move"]
    elif kind == "leaves":
        found = [o for o in mine if o["at"] == province(pred["province"]) and o["type"] == "move"]
    elif kind == "dislodged":
        found = [o for o in mine if o["at"] == province(pred["province"]) and o["dislodged"]]
    elif kind == "supports":
        wanted = {"move": ("support_move",), "hold": ("support_hold",)}.get(
            pred.get("kind"), ("support_move", "support_hold")
        )
        found = []
        for o in mine:
            if o["type"] not in wanted:
                continue
            supported_at = o["src"] if o["type"] == "support_move" else o["to"]
            if pred.get("of") and owner_of_unit(phase, supported_at) != pred["of"]:
                continue
            if pred.get("province") and o["to"] != province(pred["province"]):
                continue
            if pred.get("unit") and o["at"] != province(pred["unit"]):
                continue
            found.append(o)
    elif kind == "attacks":
        hit = attacked_provinces(pred, phase)
        how = {"move": ("move",), "support": ("support_move",)}.get(pred.get("how"), ("move", "support_move"))
        found = [o for o in mine if o["type"] in how and o["to"] in hit]
        if pred.get("spare"):
            # Supporting the spared power's own move into the province is help, not an attack.
            found = [o for o in found
                     if not (o["type"] == "support_move" and owner_of_unit(phase, o["src"]) == pred["spare"])]
        if pred.get("unit"):
            found = [o for o in found if o["at"] == province(pred["unit"])]
    else:
        raise ValueError(f"unknown predicate {kind!r}")
    if "success" in pred and kind in ("order", "moves_to", "attacks", "leaves"):
        if not (intent and pred["success"]):
            found = [o for o in found if o["success"] == bool(pred["success"])]
    return found


def board_fact(pred: dict, window: list[dict], intent: bool = False) -> tuple[bool | None, list[str]]:
    """unit_at / owns / centers: a fact about the board at the start or end of the window.

    `intent`: "I keep a unit in X" was done as far as orders go when the unit there was ordered
    to stay and was dislodged (see INTENT_KINDS)."""
    end = pred.get("when", "end") == "end"
    phase = window[-1] if end else window[0]
    if intent and end and pred["p"] == "unit_at":
        stayed = [o for o in phase["orders"] if o["power"] == pred["power"] and o["dislodged"]
                  and o["at"] == province(pred["province"]) and o["type"] != "move"]  # fmt: skip
        if stayed:
            return True, [order_line(o, phase) for o in stayed]
    if end and not phase.get("end_known", True):
        return None, [f"not checkable: the board after {phase['label']}, the last turn, is not in the record"]
    units = phase["units_end"] if end else phase["units"]
    centers = phase["centers_end"] if end else phase["centers"]
    when = f"{'after' if end else 'at the start of'} {phase['label']}"
    power = pred["power"]
    if pred["p"] == "centers":
        count = sum(owner == power for owner in centers.values())
        held = count >= pred["at_least"] if "at_least" in pred else count == pred["count"]
        return held, [f"{power} owns {count} centres {when}"]
    where = province(pred["province"])
    if pred["p"] == "unit_at":
        held = any(u["power"] == power and u["at"] == where for u in units)
        return held, [f"{power} {'has a' if held else 'has no'} unit in {where} {when}"]
    held = centers.get(where) == power
    return held, [f"{power} {'owns' if held else 'does not own'} {where} {when}"]


def order_result(order: dict, kind: str) -> str:
    """', succeeded' / ', failed' / ', dislodged' for an evidence line. A hold has no result worth naming."""
    if kind == "dislodged" or order["dislodged"]:
        return ", dislodged"
    if order["type"] == "hold":
        return ""
    return ", succeeded" if order["success"] else ", failed"


def order_line(order: dict, phase: dict, kind: str = "") -> str:
    return f"{order['power']} {order['text']} ({phase['label']}{order_result(order, kind)})"


def span(window: list[dict]) -> str:
    return window[0]["label"] if len(window) == 1 else f"{window[0]['label']} to {window[-1]['label']}"


def evaluate(pred: dict, window: list[dict], intent: bool = False,
             used: list | None = None) -> tuple[bool | None, list[str]]:
    """(holds?, evidence) for one predicate over the window's movement phases. None = cannot be checked.

    `used`, when given, collects the orders that matched, as (turn, power, order text)."""
    if "not" in pred:
        held, evidence = evaluate(pred["not"], window, intent, used)
        # "It did not happen" needs no evidence line; "it happened" keeps the orders that show it.
        return (None if held is None else not held), (evidence if held is not False else [])
    if "any" in pred:
        results = [evaluate(p, window, intent, used) for p in pred["any"]]
        evidence = [line for _, lines in results for line in lines]
        if any(held for held, _ in results):
            return True, evidence
        return (None if any(held is None for held, _ in results) else False), evidence
    if "all" in pred:
        return evaluate_all(pred["all"], window, intent, used)
    kind = pred.get("p")
    if kind == "unverifiable":
        return None, [f"not checkable: {pred.get('why', 'no reason given')}"]
    if kind in ("unit_at", "owns", "centers"):
        return board_fact(pred, window, intent)
    # A predicate about one unit ("my army in SEV holds") says nothing in a turn where that unit
    # does not exist (it was dislodged or destroyed the turn before).
    named = unit_named(pred)
    present = [p for p in window if named is None or owner_of_unit(p, named) == pred.get("power")]
    if not present:
        return None, [f"not checkable: {pred.get('power')} has no unit in {named} ({span(window)})"]
    evidence = []
    for phase in present:
        for order in matching_orders(pred, phase, intent):
            evidence.append(order_line(order, phase, kind))
            if used is not None:
                used.append((phase["turn"], order["power"], order["text"]))
    if not evidence:
        return False, [f"no order matched {describe(pred)} ({span(present)})"]
    return True, evidence


def describe(pred: dict) -> str:
    """A predicate in a few words, for the evidence line of something that did not happen."""
    extra = " ".join(str(pred[k]) for k in ("order", "province", "of", "target", "provinces", "unit") if pred.get(k))
    return f"{pred.get('power', '')} {pred['p']} {extra}".strip()


def unique(lines: list[str]) -> list[str]:
    return list(dict.fromkeys(lines))


def is_action(pred: dict) -> bool:
    """Something to be ordered (not a `not`, not a fact about the board, not `unverifiable`)."""
    return "not" not in pred and pred.get("p") not in ("unit_at", "owns", "centers", "unverifiable")


def judge(preds: list[dict], window: list[dict], intent: bool, used: list | None) -> tuple[bool | None, list[str]]:
    """Every predicate over the same window. False wins over unknown: one broken part breaks the whole."""
    results = [evaluate(p, window, intent, used) for p in preds]
    evidence = [line for _, lines in results for line in lines]
    if any(held is False for held, _ in results):
        return False, evidence
    return (None if any(held is None for held, _ in results) else True), evidence


def evaluate_all(preds: list[dict], window: list[dict], intent: bool = False,
                 used: list | None = None) -> tuple[bool | None, list[str]]:
    """All predicates must hold.

    Over several turns, things to be ordered together ("BUD moves to SER with RUM's support")
    must be ordered in the SAME turn: the move in spring and the support in autumn is not the
    plan. `not` and board facts are still judged over the whole window."""
    actions = [p for p in preds if is_action(p)]
    if len(window) < 2 or len(actions) < 2:
        return judge(preds, window, intent, used)
    rest = [p for p in preds if not is_action(p)]
    by_turn = [judge(actions, [phase], intent, None)[0] for phase in window]
    if True in by_turn:
        done, evidence = judge(actions, [window[by_turn.index(True)]], intent, used)
    else:
        done = False if all(held is False for held in by_turn) else None
        each, evidence = judge(actions, window, intent, used)
        if each and done is False:
            evidence.append(f"but never all in the same turn ({span(window)})")
    other, other_evidence = judge(rest, window, intent, used)
    if done is False or other is False:
        return False, evidence + other_evidence
    return (None if done is None or other is None else True), evidence + other_evidence


OUTCOMES = {  # kind -> (commitment held, did not hold)
    "promise": ("kept", "broken"),
    "threat": ("carried_out", "not_carried_out"),
    "request": ("complied", "refused"),
    "statement": ("true", "false"),
    "proposal": ("followed", "not_followed"),
}
UNMET = {"promise": "released", "threat": "not_triggered"}  # every other kind: "not_applicable"


def sparing(preds: list[dict], power: str) -> list[dict]:
    """A copy of `preds` in which every `attacks` predicate spares `power` (unless it names its own).

    "BUL is yours" from Turkey to us is `not attacks [BUL]` by Turkey. Turkey supporting OUR army
    into Bulgaria keeps that promise; without this it would read as breaking it."""
    out = []
    for pred in preds:
        pred = dict(pred)
        if "not" in pred:
            pred["not"] = sparing([pred["not"]], power)[0]
        for key in ("any", "all"):
            if key in pred:
                pred[key] = sparing(pred[key], power)
        if pred.get("p") == "attacks" and pred.get("power") != power:
            pred.setdefault("spare", power)
        out.append(pred)
    return out


def said_to(claim: dict, message: dict) -> str:
    """Whom the claim was made to: the claim's `to`, else the message's recipient ("ALL" for public press)."""
    return claim.get("to") or message["to"]


def leaves(preds: list[dict]) -> list[dict]:
    """The plain predicates inside `not`, `any` and `all`."""
    out = []
    for pred in preds:
        if "not" in pred:
            out += leaves([pred["not"]])
        elif "any" in pred or "all" in pred:
            out += leaves(pred.get("any") or pred.get("all"))
        else:
            out.append(pred)
    return out


def statement_scope(claim: dict, message: dict, window: list[dict]) -> str:
    """What a statement is about, which decides whether it can mislead anyone.

    "record": only turns already played when it was said, or the board as it stood. Every player
              can read that off the map, so a wrong account of it is a slip, not a deception.
    "forecast": another power's orders in a turn not yet played. The speaker cannot know them.
    "own_orders": the speaker's own orders in a turn not yet played. This is the speaker's word."""
    scope = "record"
    for pred in leaves(claim["commitment"]):
        kind = pred.get("p")
        if kind == "unverifiable":
            continue
        board = kind in ("unit_at", "owns", "centers")
        ahead = window[-1]["turn"] >= message["turn"] and not (board and pred.get("when", "end") == "start")
        if not ahead:
            continue
        if pred.get("power") != message["from"]:
            return "forecast"
        scope = "own_orders"
    return scope


def check_claim(claim: dict, message: dict, phases: list[dict]) -> dict:
    """One claim against the orders. Keys starting with "_" are working notes for `audit`."""
    first, last = claim.get("turns") or [message["turn"], message["turn"]]
    window = [p for p in phases if first <= p["turn"] <= last]
    result = {"window": [first, last], "condition": "none", "evidence": [], "_orders": [], "_breaks": None}
    if not window:
        return {**result, "outcome": "not_reached"}  # the game ended before the turns it covers
    kind = claim["kind"]
    if claim.get("condition"):
        met, evidence = evaluate_all(claim["condition"], window)
        result["condition"] = "unverifiable" if met is None else "met" if met else "unmet"
        result["evidence"] += [f"condition: {line}" for line in evidence]
        if met is False:
            return {**result, "outcome": UNMET.get(kind, "not_applicable")}
    commitment = claim["commitment"]
    other = said_to(claim, message) if message["from"] != said_to(claim, message) else None
    if other in POWER.values():  # said to one power: a private message, or a public one with `to`
        commitment = sparing(commitment, other)
    used: list = []
    held, evidence = evaluate_all(commitment, window, used=used)
    yes, no = OUTCOMES[kind]
    outcome = yes if held else no
    if held is False and kind in INTENT_KINDS:
        tried_orders: list = []
        tried, tried_evidence = evaluate_all(commitment, window, intent=True, used=tried_orders)
        if tried:
            held, evidence, used, outcome = True, tried_evidence, tried_orders, "attempted"
    if kind == "statement":
        result["scope"] = statement_scope(claim, message, window)
        if result["scope"] == "forecast" and held is not None:
            outcome = "forecast_right" if held else "forecast_wrong"
    result["evidence"] = unique(result["evidence"] + evidence)
    if held is None or result["condition"] == "unverifiable":
        outcome = "unverifiable"
    if held is False:
        result["_breaks"] = breaking_orders(commitment, window)
    return {**result, "outcome": outcome, "_orders": used if held else []}


def breaking_orders(commitment: list[dict], window: list[dict]) -> tuple[int, list | None, bool]:
    """For a commitment that did not hold: (the turn it first failed in, the orders that broke it,
    was every failed part a `not`).

    The orders are (turn, power, text). They are None when no particular order broke it: something
    was promised and no unit was ever ordered to do it."""
    orders: list | None = []
    only_nots = True
    for pred in commitment:
        used: list = []
        if evaluate(pred, window, used=used)[0] is not False:
            continue
        if "not" in pred and used:
            orders = None if orders is None else orders + used
            continue
        only_nots = False
        named = unit_named(pred) if "p" in pred else None
        keeps = [p for p in pred.get("any") or [pred] if p.get("p") == "unit_at" and p.get("when", "end") == "end"]
        if named is None and keeps:  # "I keep X": the unit that was in X is the one that broke it
            named, pred = province(keeps[0]["province"]), keeps[0]
        if named is None or len(window) != 1:
            orders = None
            continue
        # A named unit that was to do one thing and did another: what it did is what broke it.
        did = [(window[0]["turn"], o["power"], o["text"]) for o in window[0]["orders"]
               if o["at"] == named and o["power"] == pred.get("power")]
        orders = None if orders is None or not did else orders + did
    turn = min(t for t, _, _ in orders) if orders and only_nots else window[-1]["turn"]
    return turn, orders, only_nots


def attacks_by(attacker: str, victim: str, phase: dict) -> list[dict]:
    """The attacker's orders in one phase that move on, or support or convoy a move on, a unit or
    centre of the victim's (as they stood at the start of the phase). Helping the victim's own
    unit into the victim's own province is not an attack."""
    held = holdings(victim, phase)
    out = []
    for order in phase["orders"]:
        if order["power"] != attacker or order["type"] not in ("move", "support_move", "convoy"):
            continue
        if order["to"] not in held:
            continue
        if order["type"] != "move" and owner_of_unit(phase, order["src"]) == victim:
            continue
        out.append(order)
    return out


def attack_lines(attacker: str, victim: str, phases: list[dict]) -> list[str]:
    return [order_line(o, phase) for phase in phases for o in attacks_by(attacker, victim, phase)]


def could_break(commitment: list[dict], window: list[dict], borders: dict | None) -> bool:
    """Could the named power have broken this commitment at all?

    Only a commitment made of nothing but "will not move on / attack / support into" is ever
    judged impossible to break: when the power has no unit that could move into any province it
    protects, in any turn of the window. (Convoys are not followed: an army that could only
    arrive by sea counts as out of reach. The ledger keeps provinces, not coasts, so a fleet in
    SPA, STP or BUL is given the borders of both coasts and can count as able when it is not.)
    Without a border table the answer is "yes"."""
    if not borders:
        return True
    for pred in commitment:
        inner = pred.get("not")
        if not inner or inner.get("p") not in ("moves_to", "attacks", "supports") or (
                inner["p"] == "supports" and not inner.get("province")):
            return True
        for phase in window:
            targets = attacked_provinces(inner, phase) if inner["p"] == "attacks" else {province(inner["province"])}
            for unit in phase["units"]:
                if unit["power"] != inner.get("power"):
                    continue
                if inner.get("unit") and unit["at"] != province(inner["unit"]):
                    continue
                if targets & set(borders.get(unit["unit"], {}).get(unit["at"], [])):
                    return True
    return False


def pledge_of_peace(commitment: list[dict]) -> bool:
    """Is every part of the commitment "will not move on / attack / support into"?"""
    return all("not" in pred and pred["not"].get("p") in ("moves_to", "attacks", "supports") for pred in commitment)


def protects_another(commitment: list[dict], party: str) -> bool:
    """Is every part of a pledge of peace "will not attack Q", with Q a power other than `party`?
    "I will not attack Italy", said to us, is a plan about Italy and no pledge to us."""
    inner = [pred["not"] for pred in commitment if "not" in pred]
    return bool(inner) and all(p.get("p") == "attacks" and p.get("target") not in (None, party) for p in inner)


def only_holds_failed(commitment: list[dict], window: list[dict], to: str | None = None) -> bool:
    """Did the commitment fail only in parts that say one of the speaker's units will stay put
    (`holds`, or an exact hold or support-hold order)? "A BUR holds", then A BUR - MAR.

    A support-hold of a unit of `to`, the party it was said to, is not such a part: that is help
    promised to them, and withholding it can cost them the province."""
    failed = [pred for pred in commitment if evaluate(pred, window)[0] is False]
    def stays(pred: dict) -> bool:
        if pred.get("p") == "holds":
            return True
        if pred.get("p") != "order":
            return False
        order = parse_order(pred["order"])
        if order["type"] == "support_hold":
            return to is None or all(owner_of_unit(phase, order["to"]) != to for phase in window)
        return order["type"] == "hold"
    return bool(failed) and all(stays(pred) for pred in failed)


def first_refusal(claim: dict, message: dict, phases: list[dict]) -> int | None:
    """The first turn in which a request was not complied with; None when it was, or cannot be told."""
    first, last = claim.get("turns") or [message["turn"], message["turn"]]
    window = [p for p in phases if first <= p["turn"] <= last]
    if not window or evaluate_all(claim["commitment"], window, intent=True)[0] is not False:
        return None
    if not pledge_of_peace(claim["commitment"]):
        return window[-1]["turn"]  # something asked for and never done: it ran out with the window
    return next(p["turn"] for p in window if evaluate_all(claim["commitment"], [p], intent=True)[0] is False)


def relied_on(power: str, belief: dict | None, phase: dict | None) -> bool | None:
    """Did our committed press policy for the turn rely on `power`'s word? None = no stance recorded."""
    if not belief:
        return None
    stance = (belief.get("stances") or {}).get(power)
    trust = (belief.get("trust") or {}).get(power)
    if stance in DISTRUST_STANCES or (trust is not None and float(trust) < RELY_TRUST):
        return False
    expected = False
    for text in belief.get("expected_orders") or []:
        try:
            expected |= phase is not None and owner_of_unit(phase, parse_order(text)["at"]) == power
        except ValueError:
            continue
    if stance == "ally" or (trust is not None and float(trust) >= RELY_TRUST) or expected:
        return True
    return None


def aimed_at_us(preds: list[dict], phase: dict, our_power: str) -> bool:
    """Does this commitment say the named power WILL move on, or support a move on, one of our
    units or centres (as they stood at the start of the window)? "PIC falls this autumn" said to
    the power holding PIC is an announced attack, not a promise we could rely on. Negated
    predicates ("I will not enter ENG") are never aimed at us.

    `our_power` is the party the words were said to: us, or the power we said them to."""
    ours = holdings(our_power, phase)
    for pred in preds:
        if "any" in pred or "all" in pred:
            if aimed_at_us(pred.get("any") or pred.get("all"), phase, our_power):
                return True
            continue
        kind = pred.get("p")
        if pred.get("power") == our_power:
            continue
        if kind == "moves_to" or (kind == "supports" and pred.get("kind") != "hold" and pred.get("province")):
            targets = {province(pred["province"])}
        elif kind == "attacks":
            targets = attacked_provinces(pred, phase)
        elif kind == "order":
            order = parse_order(pred["order"])
            targets = {order["to"]} if order["type"] in ("move", "support_move") else set()
        else:
            continue
        if targets & ours:
            return True
    return False


def category(kind: str, speaker: str, outcome: str, relied: bool | None, our_power: str,
             against_us: bool = False, *, to: str | None = None, scope: str | None = None,
             attacked_us: bool = False, breakable: bool = True, we_attacked: bool = True,
             about_us: bool = True, harmless: bool = False) -> str:
    """How we stood towards a claim whose honesty could be checked. `speaker` is who said it.

    `against_us`: a promise that is itself an attack on the party it was said to: on us (see
    `aimed_at_us`), or, when we are the speaker, on the power we said it to.
    `to`: whom it was said to (None = to us). `scope`: a statement's `statement_scope`.
    `harmless`: the only thing broken was "this unit will stay put", and the speaker made no move
    on the party it was said to (see `only_holds_failed`).
    The last four decide whether a kept promise we doubted was a missed alliance:
    `attacked_us`: the speaker moved on us in the claim's window or the turn before;
    `breakable`: the speaker had a unit that could have broken it (`could_break`);
    `about_us`: it was a pledge not to move on us (`pledge_of_peace`), not a plan against others;
    `we_attacked`: we moved on the speaker in the window, so the doubt cost something."""
    honest = HONEST.get(outcome)
    if honest is None or kind not in SPEAKERS_WORD:
        return "none"
    if kind == "statement" and scope == "record" and not honest:
        # Wrong about orders everyone has already seen: a slip or a taunt, not a deception.
        return "we_misstated" if speaker == our_power else "misstated"
    if harmless and not honest:
        return "we_changed_plans" if speaker == our_power else "changed_plans"
    if speaker == our_power:
        if against_us and kind == "promise":
            # We told a power we would move on it. Whether we did is not a matter of our word to it.
            return "our_attack_announced" if honest else "our_attack_not_made"
        return "we_kept_our_word" if honest else "we_broke_our_word"
    if to not in (None, our_power, "ALL"):
        # Said about a deal with someone else. We can watch it break; it was never ours to rely on.
        return "kept_to_other" if honest else "broken_to_other"
    if against_us and kind == "promise":
        # Not ours to rely on or doubt: it would otherwise read "betrayed" when the attack
        # never came and "doubted wrongly" (a missed alliance) when it did.
        return "attack_announced" if honest else "attack_not_made"
    if relied is None:
        return "true_no_stance" if honest else "false_no_stance"
    if relied:
        return "trusted_rightly" if honest else "betrayed" if kind == "promise" else "deceived"
    if not honest:
        return "doubted_rightly"
    if attacked_us:
        return "kept_but_attacked_us"
    if kind == "promise" and about_us and breakable and we_attacked:
        return "doubted_wrongly"
    return "kept_despite_doubt"


def plain(text: str) -> str:
    """Text for comparing a quote with its message: no markup, one kind of quote mark and dash,
    single spaces, lower case."""
    text = re.sub(r"<br\s*/?>", " ", html.unescape(text))
    for odd, usual in (("\u2019", "'"), ("\u2018", "'"), ("\u201c", '"'), ("\u201d", '"'),
                       ("\u2014", "-"), ("\u2013", "-"), ("\u2026", "...")):
        text = text.replace(odd, usual)
    return " ".join(text.lower().split())


def quote_missing(quote: str, text: str) -> str | None:
    """The first part of `quote` that is not in the message, or None when all of it is.

    "..." may stand for words left out, and a note in [square brackets] is the annotator's own."""
    parts = [part.strip() for part in plain(re.sub(r"\[[^\]]*\]", " ", quote)).split("...")]
    parts = [part for part in parts if part]
    if not parts:
        return quote or "(empty)"
    said = plain(text)
    at = 0  # "..." leaves words out; it does not move them, so each part is looked for after the one before
    for part in parts:
        found = said.find(part, at)
        if found < 0:
            return part
        at = found + len(part)
    return None


def claim_refs(refs: list[str], messages: dict[str, dict]) -> list[tuple[str, int | None]]:
    """"prv-82" (every claim of that message) or "prv-82#2" (its second claim) -> (message id, index or None)."""
    out = []
    for ref in refs:
        mid, _, number = str(ref).partition("#")
        if mid not in messages or (number and not number.isdigit()):
            raise ValueError(f"'replaces' names {ref!r}, which is not a message id or 'message id#claim number'")
        out.append((mid, int(number) - 1 if number else None))
    return out


NEEDS = {  # predicate -> the fields it cannot be checked without
    "order": ("power", "order"), "moves_to": ("power", "province"), "holds": ("power", "province"),
    "leaves": ("power", "province"), "dislodged": ("power", "province"), "supports": ("power",),
    "attacks": ("power",), "unit_at": ("power", "province"), "owns": ("power", "province"),
    "centers": ("power",), "unverifiable": (),
}  # fmt: skip


def validate_predicate(pred) -> None:
    """Refuse a predicate `evaluate` could not read. Checked for every claim, also one about turns
    the game never reached or behind a condition that was not met: whether claims.json is well
    formed must not depend on how the game went."""
    if not isinstance(pred, dict):
        raise ValueError(f"a predicate must be an object, not {pred!r}")
    if "not" in pred:
        return validate_predicate(pred["not"])
    for key in ("any", "all"):
        if key in pred:
            if not isinstance(pred[key], list) or not pred[key]:
                raise ValueError(f"'{key}' needs a list of predicates")
            for inner in pred[key]:
                validate_predicate(inner)
            return None
    kind = pred.get("p")
    if kind not in NEEDS:
        raise ValueError(f"unknown predicate {kind!r}")
    absent = [field for field in NEEDS[kind] if not pred.get(field)]
    if kind == "attacks" and not (pred.get("target") or pred.get("provinces")):
        absent.append("target or provinces")
    if kind == "centers" and "count" not in pred and "at_least" not in pred:
        absent.append("count or at_least")
    if absent:
        raise ValueError(f"predicate {kind!r} needs {', '.join(absent)}")
    if kind == "order":
        parse_order(pred["order"])
    return None


def validate_claim(claim: dict, message: dict, where: str) -> None:
    if claim.get("kind") not in KINDS:
        raise ValueError(f"{where}: kind must be one of {KINDS}, not {claim.get('kind')!r}")
    if not claim.get("commitment"):
        raise ValueError(f"{where}: commitment is empty (use an 'unverifiable' predicate when nothing can be checked)")
    for pred in list(claim["commitment"]) + list(claim.get("condition") or []):
        try:
            validate_predicate(pred)
        except ValueError as error:
            raise ValueError(f"{where}: {error}") from error
    turns = claim.get("turns")
    if turns is not None and (len(turns) != 2 or turns[0] > turns[1]):
        raise ValueError(f"{where}: turns must be [first, last]")
    if claim["kind"] == "threat" and not claim.get("condition"):
        raise ValueError(f"{where}: a threat needs a condition (what triggers it)")
    if claim["kind"] == "request":
        asked = claim.get("asked") or message["to"]
        if asked not in POWER.values():
            raise ValueError(f"{where}: a request in a public message needs 'asked', the power being asked")
    to = claim.get("to")
    if to is not None and to != "ALL" and to not in POWER.values():
        raise ValueError(f"{where}: 'to' must be a power or \"ALL\", not {to!r}")
    missing = quote_missing(claim.get("quote") or "", message["text"])
    if missing is not None:
        raise ValueError(f"{where}: the quote is not in the message: {missing!r} (copy the message's own words; "
                         "put your own notes in 'context')")


def apply_replacements(ledger: dict, claims: dict, results: dict) -> None:
    """A later claim that `replaces` an earlier one ends it: the earlier claim no longer covers the
    turn the later message is about, nor any turn after. A plan changed in the open before the
    orders went in is not a broken word.

    "In the open" means told to the party the earlier claim was made to. A change told only to
    someone else leaves the earlier claim standing: that party was never given notice.

    The party a promise was made to can also let it go ("no need to support me into BEL after
    all"): its later claim, said to the promiser, may replace the promiser's claim."""
    messages = {m["id"]: m for m in ledger["messages"]}
    order = {m["id"]: i for i, m in enumerate(ledger["messages"])}
    for message in ledger["messages"]:
        for index, claim in enumerate(claims[message["id"]]):
            if not claim.get("replaces"):
                continue
            where = f"{message['id']} claim {index + 1}"
            for mid, number in claim_refs(claim["replaces"], messages):
                old = messages[mid]
                parties = {old["from"], old["to"]} | {said_to(made, old) for made in claims[mid]}
                if order[mid] >= order[message["id"]] or message["from"] not in parties:
                    raise ValueError(f"{where}: 'replaces' must name an earlier message from the same sender "
                                     f"(or one whose promise was made to this sender), not {mid}")
                targets = range(len(claims[mid])) if number is None else [number]
                for target in targets:
                    if target >= len(claims[mid]):
                        raise ValueError(f"{where}: {mid} has no claim {target + 1}")
                    made_to = said_to(claims[mid][target], old)
                    own_change = old["from"] == message["from"] and made_to == said_to(claim, message)
                    let_go = made_to == message["from"] and said_to(claim, message) == old["from"]
                    if not (own_change or let_go):
                        continue
                    result = results[mid, target]
                    first, last = result["window"]
                    cut = message["turn"] - 1
                    if cut >= last:
                        continue  # the earlier claim had already run its course
                    if cut < first:
                        changed = {"window": [first, last], "condition": "none", "outcome": "superseded",
                                   "evidence": [], "_orders": [], "_breaks": None}
                    else:
                        changed = check_claim({**claims[mid][target], "turns": [first, cut]}, old, ledger["phases"])
                    changed["evidence"] = changed["evidence"] + [
                        f"note: replaced by {message['id']} ({message['sent_in']}), before that turn's orders"]
                    results[mid, target] = {**changed, "replaced_by": message["id"]}


def said_beforehand(ledger: dict, claims: dict, results: dict, mid: str, index: int) -> list[str] | None:
    """The later messages that told the other party, before the orders went in, about every order
    that broke this claim; None when some breaking order was never mentioned.

    Two things count: the speaker announcing the order to the same party in a later message (a
    promise or statement that the order then fulfilled), and the other party asking for it (a
    request the order complied with)."""
    result = results[mid, index]
    _, breaking, _ = result["_breaks"]
    if not breaking:
        return None
    position = {m["id"]: i for i, m in enumerate(ledger["messages"])}
    said = next(m for m in ledger["messages"] if m["id"] == mid)
    speaker, other = said["from"], said_to(claims[mid][index], said)
    told = []
    for turn, power, text in breaking:
        source = None
        for later in ledger["messages"][position[mid] + 1:]:
            if later["turn"] > turn:
                break
            for number, claim in enumerate(claims[later["id"]]):
                found = results[later["id"], number]
                if (turn, power, text) not in found["_orders"]:
                    continue
                announced = (later["from"] == speaker and said_to(claim, later) == other
                             and claim["kind"] in ("promise", "statement") and HONEST.get(found["outcome"]))
                asked_for = (later["from"] == other and claim["kind"] == "request"
                             and (claim.get("asked") or later["to"]) == speaker)
                if announced or asked_for:
                    source = later["id"]
        if source is None:
            return None
        told.append(source)
    return unique(told)


def audit(ledger: dict, claims: dict) -> dict:
    """Check every claim. `claims` maps message id -> list of claims; every message needs an entry."""
    missing = [m["id"] for m in ledger["messages"] if m["id"] not in claims]
    if missing:
        raise ValueError(
            f"claims.json has no entry for {len(missing)} message(s), e.g. {missing[:3]}; "
            "a message with no claim gets an empty list"
        )
    phases, us = ledger["phases"], ledger["our_power"]
    by_turn = {p["turn"]: p for p in phases}
    results: dict[tuple[str, int], dict] = {}
    for message in ledger["messages"]:
        for index, claim in enumerate(claims[message["id"]]):
            where = f"{message['id']} claim {index + 1}"
            validate_claim(claim, message, where)
            try:
                results[message["id"], index] = check_claim(claim, message, phases)
            except (ValueError, KeyError) as error:
                raise ValueError(f"{where}: {error}") from error
    apply_replacements(ledger, claims, results)
    messages = []
    for message in ledger["messages"]:
        checked = []
        for index, claim in enumerate(claims[message["id"]]):
            result = results[message["id"], index]
            to = said_to(claim, message)
            first, last = result["window"]
            window = [p for p in phases if first <= p["turn"] <= last]
            if HONEST.get(result["outcome"]) is False and claim["kind"] in SPEAKERS_WORD:
                told = said_beforehand(ledger, claims, results, message["id"], index)
                first_break, _, only_nots = result["_breaks"]
                earlier = [p for p in window if p["turn"] < first_break]
                struck_first = attack_lines(to, message["from"], earlier) if to in POWER.values() else []
                # The other half of a deal: what this same message asked of the party it was said to.
                # Only a request that was refused: one whose condition never came about asked nothing.
                asked = [(other, first_refusal(other, message, phases))
                         for number, other in enumerate(claims[message["id"]])
                         if other["kind"] == "request" and (other.get("asked") or message["to"]) == to
                         and results[message["id"], number]["outcome"] == "refused"]  # fmt: skip
                refused = [other for other, turn in asked if turn is not None and turn < first_break]
                if told:
                    result["outcome"] = "superseded"
                    result["evidence"].append(f"note: said or asked for beforehand in {', '.join(told)}")
                elif claim["kind"] == "promise" and only_nots and struck_first:
                    # A pledge of peace does not outlive the other side's attack.
                    result["outcome"] = "released_by_them"
                    result["evidence"] += [f"note: {to} struck first: {line}" for line in struck_first]
                elif claim["kind"] == "promise" and refused:
                    # Nor does one half of a deal outlive the other half.
                    result["outcome"] = "released_by_them"
                    result["evidence"] += [f"note: {to} had already not done its part: “{other.get('quote', '')}”"
                                           for other in refused]  # fmt: skip
            phase = by_turn.get(first)
            # The word being weighed is always the sender's: a claim about another power's
            # conduct is still the sender's statement.
            relied = relied_on(message["from"], phase["belief"] if phase else None, phase)
            extra = {}
            if message["from"] != us and to in (us, "ALL") and window:
                before = [by_turn[first - 1]] if first - 1 in by_turn else []
                extra["attacks_on_us"] = attack_lines(message["from"], us, window)
                extra["attacks_on_us_before"] = attack_lines(message["from"], us, before)
                extra["our_attacks_on_them"] = attack_lines(us, message["from"], window)
                extra["could_break"] = could_break(claim["commitment"], window, ledger.get("borders"))
            target = us if message["from"] != us else to
            against_us = phase is not None and target in POWER.values() and aimed_at_us(
                claim["commitment"], phase, target)  # fmt: skip
            harmless = (HONEST.get(result["outcome"]) is False and to in POWER.values() and bool(window)
                        and only_holds_failed(claim["commitment"], window, to)
                        and not attack_lines(message["from"], to, window))  # fmt: skip
            stood = category(
                claim["kind"], message["from"], result["outcome"], relied, us, against_us,
                to=to, scope=result.get("scope"),
                attacked_us=bool(extra.get("attacks_on_us") or extra.get("attacks_on_us_before")),
                breakable=extra.get("could_break", True), we_attacked=bool(extra.get("our_attacks_on_them")),
                about_us=pledge_of_peace(claim["commitment"]) and not protects_another(claim["commitment"], us),
                harmless=harmless,
            )  # fmt: skip
            if stood == "kept_but_attacked_us":
                hits = extra["attacks_on_us"] or extra["attacks_on_us_before"]
                result["evidence"] += [f"note: but {message['from']} moved on us: {line}" for line in hits]
            public = {k: v for k, v in result.items() if not k.startswith("_")}
            checked.append({**claim, **public, "to": to, "relied": relied, "category": stood, **extra})
        messages.append({**message, "claims": checked})
    our_stabs = [(claim["to"], claim["window"]) for message in messages for claim in message["claims"]
                 if claim["category"] == "we_broke_our_word"]  # fmt: skip
    for message in messages:
        for claim in message["claims"]:
            first, last = claim["window"]
            if claim["category"] == "doubted_wrongly" and any(
                    power == message["from"] and low <= last and first <= high for power, (low, high) in our_stabs):
                # We had given this power our own word for those turns and broke it. That is our
                # broken word (flagged on our message), not a doubt that turned out wrong.
                claim["category"] = "kept_despite_doubt"
    kept = ("episode", "slot", "policy", "our_power", "score", "outcome", "belief_logged")
    return {
        **{k: ledger[k] for k in kept},
        "summary": summarize(messages, us),
        "messages": messages,
        "phases": phases,
    }


FLAGGED = ("betrayed", "deceived", "doubted_wrongly", "we_broke_our_word")
# what `verify` prints per power
SUMMARY_KEYS = ("claims", "held", "did_not_hold", "unverifiable", "asked", "complied", "categories",
                "betrayal_events")


def summarize(messages: list[dict], our_power: str) -> dict:
    """Per speaker: claims made, how many held, how we stood, and the claims worth opening.
    Requests are counted against the power that was asked."""
    powers: dict[str, dict] = {}

    def row(power: str) -> dict:
        return powers.setdefault(power, {
            "messages": 0, "claims": 0, "held": 0, "did_not_hold": 0, "unverifiable": 0, "held_share": None,
            "asked": 0, "complied": 0, "categories": {}, "flagged": [], "betrayal_events": 0,
        })  # fmt: skip

    # A deal restated ten times ("Locked.", "Confirmed.") is ten promises, and one order breaks
    # them all. Count the distinct sets of orders behind the betrayed and deceived claims too.
    events: dict[str, set] = {}

    for message in messages:
        speaker = row(message["from"])
        speaker["messages"] += 1
        for claim in message["claims"]:
            if claim["kind"] == "request":
                asked = row(claim.get("asked") or message["to"])
                asked["asked"] += claim["outcome"] in ("complied", "attempted", "refused")
                asked["complied"] += claim["outcome"] in ("complied", "attempted")
                continue
            speaker["claims"] += 1
            speaker["unverifiable"] += claim["outcome"] == "unverifiable"
            honest = HONEST.get(claim["outcome"]) if claim["kind"] in SPEAKERS_WORD else None
            if honest is not None:
                speaker["held" if honest else "did_not_hold"] += 1
            if claim["category"] != "none":
                speaker["categories"][claim["category"]] = speaker["categories"].get(claim["category"], 0) + 1
            if claim["category"] in ("betrayed", "deceived"):
                orders = [line for line in claim.get("evidence") or [] if not line.startswith("note: ")]
                events.setdefault(message["from"], set()).add(tuple(orders or [message["id"]]))
            if claim["category"] in FLAGGED:
                speaker["flagged"].append({
                    "message": message["id"], "turn": message["turn"], "category": claim["category"],
                    "quote": claim.get("quote", ""),
                })  # fmt: skip
    for power, entry in powers.items():
        entry["betrayal_events"] = len(events.get(power, ()))
        judged = entry["held"] + entry["did_not_hold"]
        entry["held_share"] = round(entry["held"] / judged, 3) if judged else None
    return {
        "our_power": our_power,
        "messages": len(messages),
        "messages_with_claims": sum(bool(m["claims"]) for m in messages),
        "powers": powers,
    }


# ---------- command line ----------


def find_slot(episode_dir: Path, policy: str | None, slot: int | None) -> int:
    if slot is not None:
        return slot
    seats, _ = load_episode(episode_dir)
    logged = seat_log_paths(episode_dir)
    ours = [s.slot for s in seats if s.policy == policy and s.slot in logged]
    if len(ours) != 1:
        raise ValueError(f"{len(ours)} seats of {policy!r} with a seat log in {episode_dir}; choose one with --slot")
    return ours[0]


def cmd_extract(args: argparse.Namespace) -> None:
    episode_dir = Path(args.episode_dir)
    ledger = build_ledger(episode_dir, find_slot(episode_dir, args.policy, args.slot))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "ledger.json").write_text(json.dumps(ledger, indent=1) + "\n")
    view = annotator_view(ledger)
    (out / "annotate.json").write_text(json.dumps(view, indent=1) + "\n")
    by_year = []
    for year, part in annotator_views_by_year(view).items() if args.by_year else ():
        by_year.append(str(out / f"annotate-{year}.json"))
        Path(by_year[-1]).write_text(json.dumps(part, indent=1) + "\n")
    claims_path = out / "claims.json"
    if claims_path.exists() and not args.force:
        print(f"kept the existing {claims_path} (use --force to start it again)", file=sys.stderr)
    else:
        claims_path.write_text(json.dumps({m["id"]: [] for m in ledger["messages"]}, indent=1) + "\n")
    print(
        json.dumps(
            {
                "ledger": str(out / "ledger.json"),
                "annotate": str(out / "annotate.json"),
                **({"annotate_by_year": by_year} if by_year else {}),
                "claims": str(claims_path),
                "our_power": ledger["our_power"],
                "messages": len(ledger["messages"]),
                "movement_phases": len(ledger["phases"]),
                "belief_logged": ledger["belief_logged"],
            },
            indent=1,
        )
    )


def cmd_verify(args: argparse.Namespace) -> None:
    out = Path(args.dir)
    data = audit(json.loads((out / "ledger.json").read_text()), json.loads((out / "claims.json").read_text()))
    (out / "audit.json").write_text(json.dumps(data, indent=1) + "\n")
    # `summary.powers.<POWER>.claims` leaves requests out (they are weighed against the power asked),
    # so it is printed under a name that says so, beside the requests that power made.
    requests = Counter(m["from"] for m in data["messages"] for claim in m["claims"] if claim["kind"] == "request")
    powers = {}
    for power, row in data["summary"]["powers"].items():
        printed = {k: row[k] for k in SUMMARY_KEYS}
        powers[power] = {"claims_without_requests": printed.pop("claims"), "requests_made": requests[power], **printed}
    print(
        json.dumps(
            {
                "audit": str(out / "audit.json"),
                **{k: data["summary"][k] for k in ("messages", "messages_with_claims")},
                "claims": sum(len(m["claims"]) for m in data["messages"]),
                "note": "claims is every claim, the number `check` prints. Per power, claims_without_requests "
                        "counts that power's own promises, threats, statements and proposals, and requests_made "
                        "its requests: a request is weighed against the power asked (asked, complied), not its "
                        "sender. The two columns add up to claims.",
                "powers": powers,
            },
            indent=1,
        )
    )


def cmd_check(args: argparse.Namespace) -> None:
    """The annotator's command: is claims.json well formed? It shows no verdict and writes nothing."""
    out = Path(args.dir)
    claims = json.loads((out / "claims.json").read_text())
    audit(json.loads((out / "ledger.json").read_text()), claims)
    filled = sum(bool(entry) for entry in claims.values())
    print(f"ok: {len(claims)} messages, {filled} with claims, {sum(len(entry) for entry in claims.values())} claims")


def cmd_report(args: argparse.Namespace) -> None:
    out = Path(args.dir)
    page = out / "audit.html"
    page.write_text(render_report(json.loads((out / "audit.json").read_text())))
    print(page)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    extract = sub.add_parser("extract", help="write ledger.json, annotate.json and an empty claims.json for one seat")
    extract.add_argument("episode_dir")
    extract.add_argument("--policy", help="our policy as NAME:vN (or the local seating label)")
    extract.add_argument("--slot", type=int, help="our roster slot, when the policy holds more than one seat")
    extract.add_argument("--out", required=True, help="directory for this game's ledger, claims and audit")
    extract.add_argument("--force", action="store_true", help="overwrite an existing claims.json")
    extract.add_argument("--by-year", action="store_true",
                         help="also write annotate-<year>.json, one game year each, for reading in parts")
    extract.set_defaults(run=cmd_extract)
    verify = sub.add_parser("verify", help="check claims.json against the ledger and write audit.json")
    verify.add_argument("dir")
    verify.set_defaults(run=cmd_verify)
    check = sub.add_parser("check", help="check that claims.json is well formed; shows no verdicts")
    check.add_argument("dir")
    check.set_defaults(run=cmd_check)
    report = sub.add_parser("report", help="render audit.json as audit.html")
    report.add_argument("dir")
    report.set_defaults(run=cmd_report)
    args = ap.parse_args(argv)
    if args.command == "extract" and args.policy is None and args.slot is None:
        ap.error("extract needs --policy or --slot")
    try:
        args.run(args)
    except (ValueError, FileNotFoundError) as error:
        sys.exit(f"press_audit: {error}")


if __name__ == "__main__":
    main()
