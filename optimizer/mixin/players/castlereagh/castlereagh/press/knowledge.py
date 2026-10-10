"""Press part (d), knowledge: what the agent can remember and look up.

Deliberately unopinionated (the lab's fixed plan.md, per-power profiles and commitment
ledger are gone; 10 of 30 sampled "broken promise" verdicts there were our own recording
errors). Three stores:

- `Notes`: a plain key -> text store. The agent decides what to keep (`notes(key, text)`,
  `read_notes()`). Persisted to a JSON file so it survives a bot restart within a game.
- `PressLog`: every message in or out, verbatim. The briefing shows the current season;
  older seasons come through the `conversation(power)` tool.
- `RefereeFacts`: per adjudicated movement phase, every move or support into a province
  that another power held or owned. Derived ONLY from the public order history, never
  from recorded promises.

Each store logs one JSON event per change, so the seat log carries the full record.
"""

import json
from pathlib import Path

from castlereagh import config
from castlereagh.dipmap import POWER


def phase_label(turn):
    return f"{'S' if turn % 2 == 0 else 'F'}{1901 + turn // 2}"


class Notes:
    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.data = {}
        if self.path and self.path.is_file():
            self.data = json.loads(self.path.read_text())

    def write(self, key, text):
        """Set one note; empty text deletes it."""
        key = key.strip()
        if not key:
            raise ValueError("note key must not be empty")
        if text.strip():
            self.data[key] = text[: config.PRESS_NOTE_CHARS]
            result = f"note {key!r} saved ({len(self.data[key])} chars)"
        else:
            self.data.pop(key, None)
            result = f"note {key!r} deleted"
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data, indent=1))
        return result

    def read(self):
        if not self.data:
            return "(no notes yet)"
        return "\n\n".join(f"### {key}\n{text}" for key, text in self.data.items())


class PressLog:
    def __init__(self, me, log):
        self.me, self.log = me, log
        self.seen_ids = set()
        self.messages = []  # every message in or out, in arrival order

    def ingest(self, raw_messages):
        """Add unseen messages (private or public). Returns the new ones from other powers."""
        fresh = []
        for m in sorted(raw_messages, key=lambda m: m["id"]):
            if m["id"] in self.seen_ids:
                continue
            self.seen_ids.add(m["id"])
            entry = {"id": m["id"], "turn": int(m["turn"]), "from": int(m["fromCountryID"]),
                     "to": int(m["toCountryID"]), "text": m["message"]}
            self.messages.append(entry)
            if entry["from"] != self.me:
                fresh.append(entry)
                self.log(event="press_in", id=entry["id"], turn=entry["turn"], frm=POWER.get(entry["from"]),
                         to="ALL" if entry["to"] == 0 else "us", text=entry["text"])
        return fresh

    def sent(self, turn, to, text):
        self.log(event="press_out", turn=turn, to="ALL" if to == 0 else POWER[to], text=text)

    def render(self, m):
        frm = "you" if m["from"] == self.me else POWER.get(m["from"], "?")
        to = "ALL (public)" if m["to"] == 0 else ("you" if m["to"] == self.me else POWER.get(m["to"], "?"))
        return f'<press phase="{phase_label(m["turn"])}" from="{frm}" to="{to}">{m["text"]}</press>'

    def season(self, turn):
        """Every message of this season (both directions, private and public), oldest first."""
        return [self.render(m) for m in self.messages if m["turn"] == turn]

    def conversation(self, power_id, limit=60):
        """Private messages between us and one power, all seasons, most recent `limit`."""
        thread = [m for m in self.messages if {m["from"], m["to"]} == {self.me, power_id}]
        return [self.render(m) for m in thread[-limit:]]


class RefereeFacts:
    def __init__(self, me, log):
        self.me, self.log = me, log
        self.processed = set()
        self.events = []  # {"phase", "turn", "by", "target", "province", "kind", "order", "success", "against_us"}

    def update(self, history, board, abbr):
        """Add facts for every adjudicated movement phase not yet seen.

        A unit counts as acting against a power when it moves, or supports a move, into a
        province that at the start of the phase held that power's unit or was its supply centre."""
        supply = set(board.supply)
        for ph in history.get("phases", []):
            turn = int(ph["turn"])
            if ph["phase"] != "Diplomacy" or not ph.get("orders") or turn in self.processed:
                continue
            holder = {board.province(u["terrID"]): int(u["countryID"]) for u in ph.get("units") or []}
            owner = {board.province(c["terrID"]): int(c["countryID"]) for c in ph.get("centers") or []
                     if board.province(c["terrID"]) in supply}
            fresh = []
            for o in ph["orders"]:
                if o["type"] not in ("Move", "Support move") or not o.get("toTerrID"):
                    continue
                actor, target = int(o["countryID"]), board.province(o["toTerrID"])
                victim = holder.get(target) or owner.get(target)
                if not victim or victim == actor:
                    continue
                kind = "move" if o["type"] == "Move" else "support"
                origin = abbr(board.province(o["terrID"]))
                fresh.append({"phase": phase_label(turn), "turn": turn, "by": POWER[actor], "target": POWER[victim],
                              "province": abbr(target), "kind": kind,
                              "order": f"{origin} -> {abbr(target)}" if kind == "move"
                              else f"{origin} supports into {abbr(target)}",
                              "success": bool(o.get("success")), "against_us": victim == self.me})
            self.events.extend(fresh)
            self.processed.add(turn)
            self.log(event="aggression", turn=turn, events=fresh)

    @staticmethod
    def _line(e):
        target = "US" if e["against_us"] else e["target"]
        return f"{e['phase']} {e['by']} {e['order']} vs {target}{'' if e['success'] else ' (failed)'}"

    def recent(self, current_turn):
        """Briefing view: the last two movement phases, plus all-game attacks on us per power."""
        lines = [self._line(e) for e in self.events if e["turn"] >= current_turn - 2]
        tally = {}
        for e in self.events:
            if e["against_us"]:
                tally[e["by"]] = tally.get(e["by"], 0) + 1
        if tally:
            lines.append("Attacks on us all game: " + ", ".join(f"{p} {n}" for p, n in sorted(tally.items())))
        return "\n".join(lines) or "(none yet)"

    def of(self, power):
        """Every recorded act by one power, all game."""
        lines = [self._line(e) for e in self.events if e["by"] == power]
        return "\n".join(lines) or f"(no moves or supports by {power} into another power's units or centres yet)"
