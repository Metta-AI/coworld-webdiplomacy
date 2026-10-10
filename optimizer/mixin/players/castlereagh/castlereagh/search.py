"""SearchBot (the lab's Kissinger): decision state, phase dispatch and movement setup.

Movement uses opponent_model, search_moves and evaluation. Retreats and builds use DumbBot.
"""

import time

from castlereagh import search_moves
from castlereagh.dumbbot import DumbBot
from castlereagh.evaluation import evaluator
from castlereagh.opponent_model import opponent_model
from castlereagh.search_orders import dipmap, fast_orders


class SearchBot:
    def __init__(self, variant, board, country, phase, turn, rng):
        self.variant, self.board, self.country, self.phase, self.turn, self.rng = (
            variant, board, country, phase, turn, rng)
        self.dumb = DumbBot(variant, board, country, phase, turn, rng)
        self.b = self.dumb.b
        self.trace = self.dumb.trace
        self.api = self.context = None
        self.memory = {}
        # Press policy (press/service.py): stances, expected orders, constraints and
        # per-power centre values. None = no-press behaviour, bit-identical to gunboat play.
        self.press = None
        self.evaluator = evaluator(self)
        self.opponent_model = opponent_model(self)

    def observe(self, api, context, state):
        """Called by bot.py each phase; `state` persists across the whole game."""
        self.api, self.context = api, context
        self.memory = state.setdefault("search", {"logodds": {}, "pending": None})

    def choose(self, slots):
        self.evaluator = evaluator(self)
        self.opponent_model = opponent_model(self)
        if self.phase != "Diplomacy" or not slots:
            return self.dumb.choose(slots)
        started = time.monotonic()
        mine = self.prepare_movement(slots)
        return search_moves.choose_movement(self, slots, mine, started)

    def prepare_movement(self, slots):
        """Board state, opponent samples and fast-adjudicator inputs for a movement decision."""
        b = self.b
        self.dm = dipmap(self.variant)
        self.unit_at = {}
        for u in b.units:
            self.unit_at[u["terrID"]] = u
            self.unit_at[b.province(u["terrID"])] = u
        by_id = {u["id"]: u for u in b.all_units}
        mine = [by_id[s["unitID"]] for s in slots]

        raw_samples = self.opponent_model.sample(slots, mine)
        self.sims = 0
        self._prepare_fast(mine, raw_samples)
        self.pinned = {}
        if self.press:
            required = self.press.get("require", {})
            self.pinned = {i: required[b.province(u["terrID"])] for i, u in enumerate(mine)
                           if b.province(u["terrID"]) in required}
        return mine

    def _prepare_fast(self, mine, raw_samples):
        """Province-level arrays for fastadj: our units first, then each sample's others."""
        parent = {t: self.b.province(t) for t in self.b.terr}
        self.parent = parent
        self.mine_units = mine
        self.fast_samples = []
        for raw in raw_samples:
            units = [u for u, _ in raw]
            fu, fo = fast_orders(units, [o for _, o in raw], parent)
            self.fast_samples.append((units, fu, fo, [o for _, o in raw]))
        self.vmax = max(self.dumb.value.values()) or 1.0
