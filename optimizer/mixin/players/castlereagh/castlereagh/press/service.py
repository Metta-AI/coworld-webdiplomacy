"""Press part (a), the search service: SearchBot behind a typed API for the agent's tools.

A *policy* is what the LLM controls (all fields optional, powers by name, orders and
provinces in standard notation):

    {"stances": {"AUSTRIA": "ally" | "neutral" | "hostile"},  # ally: assumed not to attack us
     "trust": {"AUSTRIA": 0.8},                 # P(an ally/promiser keeps its word); default DEFAULT_TRUST
     "expected_orders": ["A BUD - RUM"],        # orders other powers promised; sampled with that power's trust
     "forbid_moves_into": ["GAL"],              # provinces our units must not move or support into
     "require_orders": ["A VIE S A BUD - RUM"], # orders our units must play
     "center_values": {"TURKEY": 0.5},          # extra value per centre taken from that power (negative = reluctance)
     "risk": 0.0}                               # 0 = average over opponent samples, 1 = worst case

`resolve` turns it into SearchBot's `press` dict. With no policy (None or {}) the search is
the plain Default search, bit-identical to gunboat play. A stance or expected order for a
power without a trust value uses DEFAULT_TRUST. Each call builds a fresh SearchBot with its
own seeded RNG; opponent beliefs are shared through the game `state`.
"""

import random
from contextlib import contextmanager

from castlereagh import config, fastadj
from castlereagh.press.notation import Notation
from castlereagh.search import SearchBot
from castlereagh.search_orders import dipmap, fast_orders

DEFAULT_TRUST = 0.7


@contextmanager
def overrides(values):
    saved = {k: getattr(config, k) for k in values}
    try:
        for k, v in values.items():
            setattr(config, k, v)
        yield
    finally:
        for k, v in saved.items():
            setattr(config, k, v)


class SearchService:
    def __init__(self, variant, board, country, turn, slots, state, api=None, context=None, seed=0):
        self.variant, self.board, self.country, self.turn = variant, board, country, turn
        self.slots, self.state, self.api, self.context, self.seed = slots, state, api, context, seed
        self.calls = 0
        probe = SearchBot(variant, board, country, "Diplomacy", turn, random.Random(seed))
        self.b = probe.b
        self.notation = Notation(self.b, dipmap(variant))

    # --- policy ------------------------------------------------------------------------

    def resolve(self, policy):
        """LLM policy -> SearchBot press dict. Raises ValueError naming the bad field."""
        if not policy:
            return None
        n, b = self.notation, self.b

        def trust_of(cid):
            given = {n.country_id(k): v for k, v in (policy.get("trust") or {}).items()}
            return min(max(float(given.get(cid, DEFAULT_TRUST)), 0.0), 1.0)

        stances = {}
        for name, stance in (policy.get("stances") or {}).items():
            stance = str(stance).lower()
            if stance not in ("ally", "neutral", "hostile"):
                raise ValueError(f"stance for {name} must be ally, neutral or hostile")
            cid = n.country_id(name)
            stances[cid] = (stance, trust_of(cid))
        for name in policy.get("trust") or {}:
            cid = n.country_id(name)
            if cid not in stances:
                stances[cid] = ("neutral", trust_of(cid))
        expected = {}
        for text in policy.get("expected_orders") or []:
            unit, order = n.parse(text)
            cid = int(unit["countryID"])
            if cid == self.country:
                raise ValueError(f"{text!r} is our own unit; use require_orders")
            expected.setdefault(cid, {})[b.province(unit["terrID"])] = order
            stances.setdefault(cid, ("neutral", trust_of(cid)))
        require = {}
        for text in policy.get("require_orders") or []:
            unit, order = n.parse(text)
            if int(unit["countryID"]) != self.country:
                raise ValueError(f"{text!r} is not our unit")
            require[b.province(unit["terrID"])] = order
        forbid = set()
        for abbr in policy.get("forbid_moves_into") or []:
            prov = n.province_id(abbr)
            if prov is None:
                raise ValueError(f"unknown province {abbr!r}")
            forbid.add(prov)
        values = {n.country_id(name): float(v) for name, v in (policy.get("center_values") or {}).items()}
        ours = {b.province(u["terrID"]) for u in b.units if int(u["countryID"]) == self.country}
        ours |= {t for t, o in b.owner.items() if o == self.country}
        return {"stance": stances, "expected": expected, "require": require, "forbid_into": forbid,
                "center_values": values, "our_provinces": ours}

    def _config(self, policy):
        risk = float((policy or {}).get("risk", config.SEARCH_RISK))
        return {"SEARCH_RISK": min(max(risk, 0.0), 1.0)}

    def _bot(self, policy, rng_key=None):
        self.calls += 1
        rng = random.Random(rng_key or f"{self.seed}:{self.country}:{self.turn}:press:{self.calls}")
        bot = SearchBot(self.variant, self.board, self.country, "Diplomacy", self.turn, rng)
        if self.api is not None:
            bot.observe(self.api, self.context, self.state)
        else:
            bot.memory = self.state.setdefault("search", {"logodds": {}, "pending": None})
        bot.press = self.resolve(policy)
        return bot

    # --- operations ----------------------------------------------------------------------

    def search(self, policy=None, rng_key=None):
        """Best orders under `policy`. Returns (webDip orders, report dict, trace).

        `rng_key` seeds this call's RNG; the order floor passes the gunboat phase key so that
        search(None) plays exactly what CASTLEREAGH_POLICY=search would."""
        with overrides(self._config(policy)):
            bot = self._bot(policy, rng_key)
            orders = bot.choose(self.slots)
            report = self._outcomes(bot, orders)
        report["orders"] = [self.notation.render(o) for o in orders]
        return orders, report, bot.trace

    def evaluate(self, order_texts, policy=None):
        """Outcome statistics of a written order set (units left out hold)."""
        with overrides(self._config(policy)):
            bot = self._bot(policy)
            mine = bot.prepare_movement(self.slots)
            chosen = {}
            for text in order_texts:
                unit, order = self.notation.parse(text)
                if int(unit["countryID"]) != self.country:
                    raise ValueError(f"{text!r} is not our unit")
                chosen[unit["id"]] = order
            orders = [chosen.get(u["id"]) or {"type": "Hold", "terrID": u["terrID"], "toTerrID": 0,
                                               "fromTerrID": 0, "viaConvoy": "No"} for u in mine]
            report = self._outcomes(bot, orders)
        report["orders"] = [self.notation.render(o) for o in orders]
        return orders, report

    def predict(self, power, policy=None):
        """Most likely orders of one power under our opponent model (and policy), with frequencies."""
        cid = self.notation.country_id(power)
        with overrides(self._config(policy)):
            bot = self._bot(policy)
            bot.prepare_movement(self.slots)
        tally = {}
        for units, _, _, raw in bot.fast_samples:
            for u, o in zip(units, raw):
                if int(u["countryID"]) == cid:
                    label = self.notation.unit_label(u)
                    text = self.notation.render(o)
                    tally.setdefault(label, {}).setdefault(text, 0)
                    tally[label][text] += 1
        n = len(bot.fast_samples) or 1
        return {unit: [f"{text} ({round(100 * c / n)}%)" for text, c in sorted(opts.items(), key=lambda x: -x[1])[:3]]
                for unit, opts in sorted(tally.items())}

    def _outcomes(self, bot, orders):
        """Mean/worst projected centres and per-unit success rates across opponent samples."""
        mu, mo = fast_orders(bot.mine_units, orders, bot.parent)
        centres, per_unit = [], [[0, 0] for _ in orders]
        for units, fu, fo, raw in bot.fast_samples:
            moved, dislodged = fastadj.adjudicate(mu + fu, mo + fo)
            occupied = {}
            for (country, prov, _), o, mv, dl in zip(mu + fu, mo + fo, moved, dislodged):
                if not dl:
                    occupied[o[1] if mv else prov] = country
            centres.append(sum(1 for t, owner in bot.b.owner.items() if occupied.get(t, owner) == self.country))
            for i in range(len(orders)):
                per_unit[i][0] += moved[i]
                per_unit[i][1] += dislodged[i]
        n = len(centres) or 1
        units = {}
        for o, (mv, dl) in zip(orders, per_unit):
            text = self.notation.render(o)
            note = []
            if o["type"] == "Move":
                note.append(f"succeeds {round(100 * mv / n)}%")
            if dl:
                note.append(f"dislodged {round(100 * dl / n)}%")
            units[text] = ", ".join(note) or "-"
        return {"expected_centres": round(sum(centres) / n, 2), "worst_case_centres": min(centres, default=0),
                "best_case_centres": max(centres, default=0), "current_centres": bot.b.centers[self.country],
                "opponent_samples": len(centres), "per_order": units}
