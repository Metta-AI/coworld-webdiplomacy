"""Opponent beliefs, ordered samples and level-1 best responses."""

import math

from castlereagh import config
from castlereagh.dumbbot import DumbBot
from castlereagh.search_orders import _same, fast_orders


class OpponentModel:
    def __init__(self, bot):
        self.bot = bot

    def update_beliefs(self):
        """Score each opponent's last movement orders: DumbBot-like vs uniform-random legal.

        `pending` holds last movement phase's DumbBot samples per unit. The log-odds per
        power accumulate log(P_dumbbot(order) / P_random(order)); the opponent sample mix
        uses sigmoid(log-odds) as the DumbBot share.
        """
        bot = self.bot
        pending = bot.memory.get("pending")
        if not pending or bot.api is None:
            return
        bot.memory["pending"] = None
        ref = (bot.context.get("files") or {}).get("history")
        if not ref:
            return
        history = bot.api.file(ref)
        entry = next((ph for ph in history.get("phases", [])
                      if ph["turn"] == pending["turn"] and ph["phase"] == "Diplomacy"), None)
        if entry is None:
            return
        self.update_hostility(pending, entry)
        self.update_type_beliefs(pending, entry)

    def update_hostility(self, pending, entry):
        """Decay hostility, then tally moves/supports into our previous provinces."""
        bot = self.bot
        # Hostility toward us: decayed count of each power's moves into our provinces and
        # supports of such moves (implicit diplomacy in no-press play).
        ours = set(pending.get("our_provinces", []))
        hostility = bot.memory.setdefault("hostility", {})
        for c in list(hostility):
            hostility[c] *= config.DIPLO_DECAY
        parent = {t: bot.b.province(t) for t in bot.b.terr}
        for o in entry.get("orders") or []:
            c = str(o["countryID"])
            if int(c) == bot.country or not o.get("toTerrID"):
                continue
            target = parent.get(o["toTerrID"], o["toTerrID"])
            if (o["type"] == "Move" or o["type"] == "Support move") and target in ours:
                hostility[c] = hostility.get(c, 0.0) + 1.0

    def update_type_beliefs(self, pending, entry):
        """Accumulate competent/random log-odds from the previous movement orders."""
        bot = self.bot
        for o in entry.get("orders") or []:
            key = str(o["terrID"])
            unit = pending["units"].get(key)
            if unit is None or int(o["countryID"]) == bot.country:
                continue
            sig = (o["type"], o["toTerrID"] or 0, o["fromTerrID"] or 0)
            samples = unit["samples"]
            matches = sum(1 for x in samples if tuple(x) == sig)
            n_legal = max(unit["n_legal"], 1)
            if config.OPP_LIKELIHOOD == "competent":
                # Competent = DumbBot-like OR any sensible order (hold, plain move, support/convoy
                # of the player's own unit). Uniform-random players often support/convoy other
                # powers' units; strong non-DumbBot players almost never do.
                n_sensible = max(unit.get("n_sensible", n_legal), 1)
                own = unit.get("own_provinces", [])
                sensible = o["type"] in ("Hold", "Move") or (o.get("fromTerrID") or o.get("toTerrID")) in own
                p_dumb = 0.5 * matches / len(samples) + (0.5 / n_sensible if sensible else 0.02 / n_legal)
            else:
                p_dumb = 0.9 * matches / len(samples) + 0.1 / n_legal
            p_rand = 1.0 / n_legal
            c = str(o["countryID"])
            lo = bot.memory["logodds"].get(c, config.OPP_PRIOR_LOGODDS) + math.log(p_dumb / p_rand)
            bot.memory["logodds"][c] = max(-config.OPP_LOGODDS_CLIP, min(config.OPP_LOGODDS_CLIP, lo))

    def apply_press(self, c, units_c, chosen):
        """Condition one sampled plan of power c on the press policy: with probability = trust,
        a unit plays the order c promised us, and an ally does not move or support into our
        provinces."""
        bot = self.bot
        b = bot.b
        stance, trust = bot.press["stance"].get(c, ("neutral", 0.0))
        expected = bot.press["expected"].get(c, {})
        ours = bot.press["our_provinces"]
        out = []
        for u, o in zip(units_c, chosen):
            here = b.province(u["terrID"])
            if here in expected and bot.rng.random() < trust:
                o = expected[here]
                bot.trace["press_expected_order_sampled"] += 1
            elif (stance == "ally" and o["type"] in ("Move", "Support move")
                  and b.province(o["toTerrID"]) in ours and bot.rng.random() < trust):
                o = {"type": "Hold", "terrID": u["terrID"], "toTerrID": 0, "fromTerrID": 0, "viaConvoy": "No"}
                bot.trace["press_ally_attack_removed"] += 1
            out.append(o)
        return out

    def dumb_share(self, c):
        bot = self.bot
        if bot.press and bot.press["stance"].get(c, ("neutral",))[0] in ("ally", "hostile"):
            return 1.0  # a power we negotiate with plays competently, not randomly
        if config.OPP_MODEL != "adaptive":
            return 1.0
        lo = bot.memory.get("logodds", {}).get(str(c), config.OPP_PRIOR_LOGODDS)
        return 1.0 / (1.0 + math.exp(-lo))

    def improve_for(self, c, model, units_c, base, j, models, theirs, dumb_samples, mine, our_dumb, legal):
        """Level-1 opponent: one pass of single-unit best response for power c, against
        DumbBot plans for everyone else (two context samples), scored from c's side."""
        bot = self.bot
        n = len(our_dumb)
        contexts = []
        for k in (j, (j + 1) % n):
            ctx = list(zip(mine, our_dumb[k]))
            for other, us in theirs.items():
                if other != c:
                    ctx.extend(zip(us, dumb_samples[other][k]))
            contexts.append(([u for u, _ in ctx], [o for _, o in ctx]))
        vmax = max(model.value.values()) or 1.0

        def value(orders_c):
            total = 0.0
            for cu, co in contexts:
                fu, fo = fast_orders(units_c + cu, orders_c + co, bot.parent)
                total += bot.evaluator.score_fast(fu, fo, units_c + cu, orders_c + co, country=c, value=model.value,
                                                  vmax=vmax)
            return total / len(contexts)

        best = list(base)
        best_value = value(best)
        idx = list(range(len(units_c)))
        bot.rng.shuffle(idx)
        for i in idx:
            for alt in legal[units_c[i]["id"]]:
                if alt["type"] == "Convoy" or alt.get("viaConvoy") == "Yes" or _same(alt, best[i]):
                    continue
                cand = best[:i] + [alt] + best[i + 1:]
                v = value(cand)
                if v > best_value + 1e-9:
                    best, best_value = cand, v
                    bot.trace["opp_level1_improvements"] += 1
        return best

    def sample(self, slots, mine):
        """Return the opponent samples (each a list of (unit, order) for every foreign unit).

        The shared RNG's draw order here is part of the golden contract: DumbBot samples
        for every power first, then our own DumbBot plans (level 1), then per sample and
        power the competent/random draw and the level-1 draw."""
        bot = self.bot
        b = bot.b
        # Opponent samples: DumbBot (improved at level 1) or uniform-random legal orders per
        # power, according to the adaptive belief.
        self.update_beliefs()
        raw_samples = []
        models = {}
        theirs = {}
        for c in {int(u["countryID"]) for u in b.units} - {bot.country}:
            models[c] = DumbBot(bot.variant, bot.board, c, bot.phase, bot.turn, bot.rng, board_model=b)
            theirs[c] = [u for u in b.units if int(u["countryID"]) == c]
        legal = {u["id"]: b.legal.movement(u) for us in theirs.values() for u in us}
        dumb_samples = {c: [] for c in models}
        n_samples = config.SEARCH_OPPONENT_SAMPLES
        for _ in range(n_samples):
            for c, model in models.items():
                dumb_samples[c].append(model.choose([{"unitID": u["id"]} for u in theirs[c]]))
        if config.OPP_MODEL_LEVEL >= 1:
            bot.parent = {t: bot.b.province(t) for t in bot.b.terr}
            own_model = DumbBot(bot.variant, bot.board, bot.country, bot.phase, bot.turn, bot.rng, board_model=b)
            our_dumb = [own_model.choose(slots) for _ in range(n_samples)]
        for j in range(n_samples):
            raw = []
            for c, model in models.items():
                d = dumb_samples[c][j]
                if bot.rng.random() < self.dumb_share(c):
                    chosen = d
                    if config.OPP_MODEL_LEVEL >= 1 and bot.rng.random() < config.OPP_LEVEL1_SHARE:
                        chosen = self.improve_for(c, models[c], theirs[c], d, j, models, theirs, dumb_samples, mine,
                                                  our_dumb, legal)
                else:
                    chosen = [bot.rng.choice(legal[u["id"]]) for u in theirs[c]]
                    bot.trace["opp_random_samples"] += 1
                if bot.press:
                    chosen = self.apply_press(c, theirs[c], chosen)
                raw.extend(zip(theirs[c], chosen))
            raw_samples.append(raw)
        ours = {b.province(u["terrID"]) for u in b.units if int(u["countryID"]) == bot.country}
        ours |= {t for t, o in b.owner.items() if o == bot.country}
        bot.memory["pending"] = {
            "turn": bot.turn,
            "our_provinces": sorted(ours),
            "units": {
                str(u["terrID"]): {
                    "n_legal": len(legal[u["id"]]),
                    "n_sensible": _n_sensible(legal[u["id"]], {b.province(x["terrID"]) for x in theirs[c]}),
                    "own_provinces": sorted({b.province(x["terrID"]) for x in theirs[c]}),
                    "samples": [[d[k]["type"], d[k]["toTerrID"] or 0, d[k]["fromTerrID"] or 0]
                                for d in dumb_samples[c]],
                }
                for c in models
                for k, u in enumerate(theirs[c])
            },
        }
        shares = [self.dumb_share(c) for c in models]
        if shares:
            bot.trace["opp_dumb_share_x100"] = round(100 * sum(shares) / len(shares))
        return raw_samples


def _n_sensible(orders, own_provinces):
    """Count holds/plain moves plus supports/convoys that involve one of the player's own units."""
    n = 0
    for o in orders:
        if o["type"] == "Hold" or (o["type"] == "Move" and o.get("viaConvoy") != "Yes"):
            n += 1
        elif o["type"] in ("Support hold", "Support move", "Convoy") and (
            (o.get("fromTerrID") or o.get("toTerrID")) in own_provinces
        ):
            n += 1
    return n


OPPONENT_MODELS = {"adaptive": OpponentModel, "dumbbot": OpponentModel}


def opponent_model(bot):
    # Other strings historically selected full DumbBot share, not an error.
    return OPPONENT_MODELS.get(config.OPP_MODEL, OpponentModel)(bot)
