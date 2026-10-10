"""Shared test setup: import path and small fakes. Imported first by every test module."""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # the `castlereagh` package

GOLDEN = HERE / "golden.json"


def golden_data():
    return json.loads(GOLDEN.read_text())


class FakeClock:
    """time.time / time.sleep stand-ins: sleeping advances the clock."""

    def __init__(self, start=1000.0):
        self.now = start

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class FakeApi:
    """Records order saves and messages; echoes saved orders back (no silent drops)."""

    def __init__(self, country, board, variant, turn, clock, history=None):
        self.country_id, self.game_id = country, 42
        self.board, self.variant, self.turn, self.clock = board, variant, turn, clock
        self.history = history or {"phases": []}
        self.calls = []  # ("orders", ready, orders, time) and ("send", body, time)
        self.inbox = []  # messages visible in context
        self.phase = "Diplomacy"

    def context(self):
        return {"game": {"turn": self.turn, "phase": self.phase, "pressType": "Regular",
                         "processTime": self.deadline},
                "orders": {"orders": self.slots},
                "messages": {"messages": list(self.inbox)},
                "files": {"game": {"url": "game"}, "variant": {"url": "variant"}, "history": {"url": "history"}}}

    def file(self, ref):
        return {"game": {**self.board, "turn": self.turn, "phase": self.phase}, "variant": self.variant,
                "history": self.history}[ref["url"]]

    def orders(self, context, orders, ready="Yes"):
        self.calls.append(("orders", ready, list(orders), self.clock()))
        return list(orders)

    def request(self, route, body=None, **params):
        self.calls.append(("send", body, self.clock()))
        return {}
