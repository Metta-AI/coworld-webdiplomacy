"""Position scoring and opponent-sample aggregation, with live config tunables."""

from castlereagh import config, fastadj
from castlereagh.search_orders import fast_orders


class PositionEvaluator:
    def __init__(self, bot):
        self.bot = bot

    def evaluate(self, ours):
        """Mean score of our orders `ours` over the opponent samples (pulled toward the worst by SEARCH_RISK)."""
        bot = self.bot
        mu, mo = fast_orders(bot.mine_units, ours, bot.parent)
        values = []
        for units, fu, fo, raw in bot.fast_samples:
            values.append(self.score_fast(mu + fu, mo + fo, bot.mine_units + units, ours + raw))
            bot.sims += 1
        mean = sum(values) / len(values)
        # Risk aversion: pull the mean toward the worst opponent sample.
        return mean - config.SEARCH_RISK * (mean - min(values))

    def score_fast(self, fu, fo, units, orders, country=None, value=None, vmax=None):
        """Static evaluation of an adjudicated outcome from `country`'s side (default: us)."""
        bot = self.bot
        me = bot.country if country is None else country
        value = bot.dumb.value if value is None else value
        vmax = bot.vmax if vmax is None else vmax
        moved, dislodged = fastadj.adjudicate(fu, fo)
        occupied = {}
        my_nodes = []
        lost = 0
        for (country, prov, utype), o, mv, dl, u, raw in zip(fu, fo, moved, dislodged, units, orders):
            if dl:
                lost += country == me
                continue
            where = o[1] if mv else prov
            occupied[where] = country
            if country == me:
                my_nodes.append((utype, raw["toTerrID"] if mv else u["terrID"]))
        counts = {}
        projected = {}
        for t, owner in bot.b.owner.items():
            holder = occupied.get(t, owner)
            projected[t] = holder
            if holder:
                counts[holder] = counts.get(holder, 0) + 1
        sc = counts.get(me, 0)
        if config.DIPLO and me == bot.country:
            sc += self.diplomacy_adjust(projected, me)
        if bot.press and me == bot.country:
            values = bot.press.get("center_values")
            if values:
                sc += sum(values.get(bot.b.owner.get(t), 0.0) for t, holder in projected.items()
                          if holder == me and bot.b.owner.get(t) not in (None, me))
        if config.SEARCH_OBJECTIVE == "share":
            total = sum(v * v for v in counts.values()) or 1
            sc = 34.0 * sc * sc / total
        pos = sum(value.get(n, 0.0) for n in my_nodes) / vmax
        return config.SEARCH_SC_WEIGHT * sc + config.SEARCH_POS_WEIGHT * pos - config.SEARCH_DISLODGED_WEIGHT * lost

    def diplomacy_adjust(self, projected, me):
        """Implicit diplomacy: centres taken from a power count more if it has been hostile to
        us (grudge) and less if it has left us alone (peace), until DIPLO_STAB_YEAR."""
        bot = self.bot
        hostility = bot.memory.get("hostility", {})
        year = 1901 + bot.turn // 2
        adj = 0.0
        for t, holder in projected.items():
            if holder != me:
                continue
            prev = bot.b.owner.get(t)
            if not prev or prev == me:
                continue
            h = hostility.get(str(prev), 0.0)
            if h >= config.DIPLO_HOSTILE:
                adj += config.DIPLO_GRUDGE
            elif year < config.DIPLO_STAB_YEAR:
                adj -= config.DIPLO_PEACE
        bot.trace["diplo_evals"] += 1
        return adj


def evaluator(bot):
    return PositionEvaluator(bot)
