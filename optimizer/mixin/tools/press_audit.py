#!/usr/bin/env python3
"""Check what was said in a press game against what was done.

    python3 games/webdiplomacy/tools/press_audit.py extract EPISODE_DIR --policy NAME:vN --out DIR
    python3 games/webdiplomacy/tools/press_audit.py verify DIR
    python3 games/webdiplomacy/tools/press_audit.py report DIR

Three steps. Steps 1 and 3 are code; step 2 is done by an agent (the press-audit skill
says how, and recommends a sub-agent per game).

1. `extract` writes `DIR/ledger.json` for ONE of our seats: every press message that seat
   could see (private messages it sent or received, and public press), every movement
   phase's adjudicated orders and board in standard notation, and what our policy believed
   about each power that turn (from its own seat log). It also writes `DIR/claims.json`,
   one empty entry per message, for step 2 to fill in.
2. An agent reads each message and lists its claims in `DIR/claims.json` using the small
   vocabulary below. It records what was SAID; it does not judge whether it came true.
3. `verify` checks every claim against the adjudicated orders and writes `DIR/audit.json`:
   per message, per claim: was the condition met, was the promise kept, the threat carried
   out, the statement true; and whether we relied on it. `report` renders `DIR/audit.html`,
   one self-contained page (it holds private press: keep it on your machine).

A claim in `claims.json` (the press-audit skill has the full rules and examples):

    {"kind": "promise" | "threat" | "request" | "statement" | "proposal",
     "quote": "I keep PRU/SIL quiet",    # the words in the message
     "turns": [1, 1],                    # first and last game turn covered (0 = Spring 1901);
                                         # omit for "the turn it was said in"
     "condition": [<predicate>, ...],    # optional: "if you ...". All must hold
     "commitment": [<predicate>, ...],   # what is promised, threatened, asked, asserted or offered
     "asked": "RUSSIA"}                  # requests in a public message only: who is asked

The speaker is always the message's sender, and it is the sender's word that is weighed.
- promise: the sender will or will not do something, perhaps only if `condition` holds.
  Kept or broken; released when the condition was not met.
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
                                                              (in a private message, P supporting the other party's
                                                              own move into the province is not an attack; "spare": Q
                                                              names another power to spare)
    {"p": "dislodged", "power": P, "province": "RUH"}         P's unit in RUH was dislodged
    {"p": "unit_at", "power": P, "province": "PRU", "when": "start" | "end"}
    {"p": "owns", "power": P, "province": "DEN", "when": "start" | "end"}
    {"p": "centers", "power": P, "count": 9, "when": ...}     P owns exactly 9 centres (or "at_least": 9)
    {"not": <predicate>}        {"any": [<predicate>, ...]}        {"all": [<predicate>, ...]}
    {"p": "unverifiable", "why": "about intentions"}          cannot be checked against orders

Over a window of several turns a predicate holds if it holds in any movement phase of the
window, and `not` holds only if it never does. `"success": true` on `order`, `moves_to` or
`attacks` requires that the move worked; `"success": false` that it was ordered and failed
(a bounce). `when` defaults to "end".

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
import sys
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
HONEST = {"kept": True, "carried_out": True, "true": True, "broken": False, "not_carried_out": False, "false": False}


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
                    "success": bool(o.get("success")),
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
    return phases


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
                "text": html.unescape(raw.get("message") or ""),
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
        "phases": phases,
        "messages": ledger_messages(private_press(rows), public_press(replay), our_power),
    }


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


def matching_orders(pred: dict, phase: dict) -> list[dict]:
    """The orders in one movement phase that make an order-type predicate true."""
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
    if "success" in pred and kind in ("order", "moves_to", "attacks"):
        found = [o for o in found if o["success"] == bool(pred["success"])]
    return found


def board_fact(pred: dict, window: list[dict]) -> tuple[bool, list[str]]:
    """unit_at / owns / centers: a fact about the board at the start or end of the window."""
    end = pred.get("when", "end") == "end"
    phase = window[-1] if end else window[0]
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


def evaluate(pred: dict, window: list[dict]) -> tuple[bool | None, list[str]]:
    """(holds?, evidence) for one predicate over the window's movement phases. None = cannot be checked."""
    if "not" in pred:
        held, evidence = evaluate(pred["not"], window)
        # "It did not happen" needs no evidence line; "it happened" keeps the orders that show it.
        return (None if held is None else not held), (evidence if held is not False else [])
    if "any" in pred:
        results = [evaluate(p, window) for p in pred["any"]]
        evidence = [line for _, lines in results for line in lines]
        if any(held for held, _ in results):
            return True, evidence
        return (None if any(held is None for held, _ in results) else False), evidence
    if "all" in pred:
        return evaluate_all(pred["all"], window)
    kind = pred.get("p")
    if kind == "unverifiable":
        return None, [f"not checkable: {pred.get('why', 'no reason given')}"]
    if kind in ("unit_at", "owns", "centers"):
        return board_fact(pred, window)
    evidence = []
    for phase in window:
        evidence += [f"{o['power']} {o['text']} ({phase['label']}{order_result(o, kind)})"
                     for o in matching_orders(pred, phase)]  # fmt: skip
    if not evidence:
        turns = window[0]["label"] if len(window) == 1 else f"{window[0]['label']} to {window[-1]['label']}"
        return False, [f"no order matched {describe(pred)} ({turns})"]
    return True, evidence


def describe(pred: dict) -> str:
    """A predicate in a few words, for the evidence line of something that did not happen."""
    extra = " ".join(str(pred[k]) for k in ("order", "province", "of", "target", "provinces", "unit") if pred.get(k))
    return f"{pred.get('power', '')} {pred['p']} {extra}".strip()


def unique(lines: list[str]) -> list[str]:
    return list(dict.fromkeys(lines))


def evaluate_all(preds: list[dict], window: list[dict]) -> tuple[bool | None, list[str]]:
    """All predicates must hold. False wins over unknown: one broken part breaks the whole."""
    results = [evaluate(p, window) for p in preds]
    evidence = [line for _, lines in results for line in lines]
    if any(held is False for held, _ in results):
        return False, evidence
    return (None if any(held is None for held, _ in results) else True), evidence


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


def check_claim(claim: dict, message: dict, phases: list[dict]) -> dict:
    first, last = claim.get("turns") or [message["turn"], message["turn"]]
    window = [p for p in phases if first <= p["turn"] <= last]
    result = {"window": [first, last], "condition": "none", "evidence": []}
    if not window:
        return {**result, "outcome": "not_reached"}  # the game ended before the turns it covers
    if claim.get("condition"):
        met, evidence = evaluate_all(claim["condition"], window)
        result["condition"] = "unverifiable" if met is None else "met" if met else "unmet"
        result["evidence"] += [f"condition: {line}" for line in evidence]
        if met is False:
            return {**result, "outcome": UNMET.get(claim["kind"], "not_applicable")}
    commitment = claim["commitment"]
    other = message["to"] if message["from"] != message["to"] else None
    if other in POWER.values():  # a private message: the party it was said to
        commitment = sparing(commitment, other)
    held, evidence = evaluate_all(commitment, window)
    result["evidence"] = unique(result["evidence"] + evidence)
    yes, no = OUTCOMES[claim["kind"]]
    unknown = held is None or result["condition"] == "unverifiable"
    result["outcome"] = "unverifiable" if unknown else yes if held else no
    return result


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
    predicates ("I will not enter ENG") are never aimed at us."""
    ours = {u["at"] for u in phase["units"] if u["power"] == our_power}
    ours |= {where for where, owner in phase["centers"].items() if owner == our_power}
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
             against_us: bool = False) -> str:
    """How we stood towards a claim whose honesty could be checked. `speaker` is who said it.
    `against_us`: a promise that is itself an attack on us (see `aimed_at_us`)."""
    honest = HONEST.get(outcome)
    if honest is None or kind not in SPEAKERS_WORD:
        return "none"
    if speaker == our_power:
        return "we_kept_our_word" if honest else "we_broke_our_word"
    if against_us and kind == "promise":
        # Not ours to rely on or doubt: it would otherwise read "betrayed" when the attack
        # never came and "doubted wrongly" (a missed alliance) when it did.
        return "attack_announced" if honest else "attack_not_made"
    if relied is None:
        return "true_no_stance" if honest else "false_no_stance"
    if relied:
        return "trusted_rightly" if honest else "betrayed" if kind == "promise" else "deceived"
    return "doubted_wrongly" if honest else "doubted_rightly"


def validate_claim(claim: dict, message: dict, where: str) -> None:
    if claim.get("kind") not in KINDS:
        raise ValueError(f"{where}: kind must be one of {KINDS}, not {claim.get('kind')!r}")
    if not claim.get("commitment"):
        raise ValueError(f"{where}: commitment is empty (use an 'unverifiable' predicate when nothing can be checked)")
    turns = claim.get("turns")
    if turns is not None and (len(turns) != 2 or turns[0] > turns[1]):
        raise ValueError(f"{where}: turns must be [first, last]")
    if claim["kind"] == "threat" and not claim.get("condition"):
        raise ValueError(f"{where}: a threat needs a condition (what triggers it)")
    if claim["kind"] == "request":
        asked = claim.get("asked") or message["to"]
        if asked not in POWER.values():
            raise ValueError(f"{where}: a request in a public message needs 'asked', the power being asked")


def audit(ledger: dict, claims: dict) -> dict:
    """Check every claim. `claims` maps message id -> list of claims; every message needs an entry."""
    missing = [m["id"] for m in ledger["messages"] if m["id"] not in claims]
    if missing:
        raise ValueError(
            f"claims.json has no entry for {len(missing)} message(s), e.g. {missing[:3]}; "
            "a message with no claim gets an empty list"
        )
    phases = ledger["phases"]
    by_turn = {p["turn"]: p for p in phases}
    messages = []
    for message in ledger["messages"]:
        checked = []
        for index, claim in enumerate(claims[message["id"]]):
            where = f"{message['id']} claim {index + 1}"
            validate_claim(claim, message, where)
            try:
                result = check_claim(claim, message, phases)
            except (ValueError, KeyError) as error:
                raise ValueError(f"{where}: {error}") from error
            phase = by_turn.get(result["window"][0])
            # The word being weighed is always the sender's: a claim about another power's
            # conduct is still the sender's statement.
            relied = relied_on(message["from"], phase["belief"] if phase else None, phase)
            against_us = phase is not None and aimed_at_us(claim["commitment"], phase, ledger["our_power"])
            stood = category(claim["kind"], message["from"], result["outcome"], relied, ledger["our_power"],
                             against_us)
            checked.append({**claim, **result, "relied": relied, "category": stood})
        messages.append({**message, "claims": checked})
    kept = ("episode", "slot", "policy", "our_power", "score", "outcome", "belief_logged")
    return {
        **{k: ledger[k] for k in kept},
        "summary": summarize(messages, ledger["our_power"]),
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
                asked["asked"] += claim["outcome"] in ("complied", "refused")
                asked["complied"] += claim["outcome"] == "complied"
                continue
            speaker["claims"] += 1
            speaker["unverifiable"] += claim["outcome"] == "unverifiable"
            honest = HONEST.get(claim["outcome"]) if claim["kind"] in SPEAKERS_WORD else None
            if honest is not None:
                speaker["held" if honest else "did_not_hold"] += 1
            if claim["category"] != "none":
                speaker["categories"][claim["category"]] = speaker["categories"].get(claim["category"], 0) + 1
            if claim["category"] in ("betrayed", "deceived"):
                events.setdefault(message["from"], set()).add(tuple(claim.get("evidence") or [message["id"]]))
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
    claims_path = out / "claims.json"
    if claims_path.exists() and not args.force:
        print(f"kept the existing {claims_path} (use --force to start it again)", file=sys.stderr)
    else:
        claims_path.write_text(json.dumps({m["id"]: [] for m in ledger["messages"]}, indent=1) + "\n")
    print(
        json.dumps(
            {
                "ledger": str(out / "ledger.json"),
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
    print(
        json.dumps(
            {
                "audit": str(out / "audit.json"),
                **{k: data["summary"][k] for k in ("messages", "messages_with_claims")},
                "powers": {p: {k: row[k] for k in SUMMARY_KEYS} for p, row in data["summary"]["powers"].items()},
            },
            indent=1,
        )
    )


def cmd_report(args: argparse.Namespace) -> None:
    out = Path(args.dir)
    page = out / "audit.html"
    page.write_text(render_report(json.loads((out / "audit.json").read_text())))
    print(page)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    extract = sub.add_parser("extract", help="write ledger.json and an empty claims.json for one of our seats")
    extract.add_argument("episode_dir")
    extract.add_argument("--policy", help="our policy as NAME:vN (or the local seating label)")
    extract.add_argument("--slot", type=int, help="our roster slot, when the policy holds more than one seat")
    extract.add_argument("--out", required=True, help="directory for this game's ledger, claims and audit")
    extract.add_argument("--force", action="store_true", help="overwrite an existing claims.json")
    extract.set_defaults(run=cmd_extract)
    verify = sub.add_parser("verify", help="check claims.json against the ledger and write audit.json")
    verify.add_argument("dir")
    verify.set_defaults(run=cmd_verify)
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
