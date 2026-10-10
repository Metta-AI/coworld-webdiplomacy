"""DumbBot (David Norman's heuristic Diplomacy bot) on webDiplomacy's own map graph.

Algorithm follows the MIT-licensed Python port in diplomacy/research
(`diplomacy_research/players/rulesets/dumbbot_ruleset.py`, Philip Paquette, 2019),
re-expressed over webDip's `variant.json` territories so no territory-ID mapping or
second engine is needed. Every chosen order is checked against the
`legal_orders.LegalOrders` generator (vendored from the coworld) before submission.

Vocabulary:
- province: a territory whose `coast` is not "Child" (split coasts collapse onto it).
- node: a (unit_type, terrID) position a unit can occupy; fleets on split-coast
  provinces sit on the child-coast territory.
- value: DumbBot's destination value of a node (higher = more desirable).

Deliberate deviation from the port (see config.NEUTRAL_SIZE_MODE): the port gives
unowned supply centres an attack value of 0, which leaves 1901 expansion to chance.
We treat the neutral centres as one pseudo-power sized by how many remain, as DAIDE's
UNO owner does.
"""

from collections import Counter

from castlereagh import config
from castlereagh.legal_orders import LegalOrders
from castlereagh.webdip_api import order, order_signature


class Board:
    """Static map graph plus the current public position, in webDip terms."""

    def __init__(self, variant, board):
        self.legal = LegalOrders(variant, board)
        self.terr = self.legal.territories
        self.status = self.legal.status
        self.units = [u for u in board["units"] if not u["retreating"]]
        self.all_units = board["units"]
        self.countries = [c["countryID"] for c in variant["countries"]]

        self.nodes = [("Army", t) for t, x in self.terr.items() if x["coast"] != "Child" and x["type"] != "Sea"]
        self.nodes += [
            ("Fleet", t)
            for t, x in self.terr.items()
            if x["type"] == "Sea" or (x["type"] == "Coast" and x["coast"] != "Parent")
        ]
        node_set = set(self.nodes)
        # Nodes a unit at `node` can move to (exact coast), and the provinces they lie in.
        self.moves = {
            n: [m for m in ((n[0], t) for t in self.legal.adjacent(n[1], n[0])) if m in node_set] for n in self.nodes
        }
        self.reach = {n: {self.province(m[1]) for m in self.moves[n]} for n in self.nodes}
        self.reached_by = {}
        for n, provinces in self.reach.items():
            for p in provinces:
                self.reached_by.setdefault(p, []).append(n)
        self.nodes_in = {}
        for n in self.nodes:
            self.nodes_in.setdefault(self.province(n[1]), []).append(n)

        self.supply = [t for t, x in self.terr.items() if x["supply"] and x["coast"] != "Child"]
        # game.json marks unowned centres as country 0; the untouched-province default is None.
        self.owner = {t: self.status[t]["ownerCountryID"] or None for t in self.supply}
        self.centers = Counter(o for o in self.owner.values() if o is not None)

    def province(self, terr_id):
        return self.terr[terr_id]["coastParentID"]

    def node(self, unit):
        return (unit["type"], unit["terrID"])

    def occupant(self, province):
        for u in self.units:
            if self.province(u["terrID"]) == province:
                return u
        return None


def size(n):
    return config.SIZE_SQUARE * n * n + config.SIZE_LINEAR * n + config.SIZE_CONSTANT


class DumbBot:
    def __init__(self, variant, board, country, phase, turn, rng, board_model=None):
        self.b = board_model or Board(variant, board)
        self.country = country
        self.phase = phase
        self.spring = turn % 2 == 0
        self.rng = rng
        self.trace = Counter()
        self._factors()

    # --- encoding --------------------------------------------------------------------

    def _factors(self):
        b = self.b
        sizes = {c: size(b.centers[c]) for c in b.countries}
        neutral = sum(1 for o in b.owner.values() if o is None)
        neutral_size = size(neutral) if config.NEUTRAL_SIZE_MODE == "uno" else 0

        # Strength/competition: how many units of each power can move into a province.
        adjacent = {}
        for u in b.units:
            for p in b.reach[b.node(u)]:
                adjacent.setdefault(p, Counter())[int(u["countryID"])] += 1
        self.strength = {p: c[self.country] for p, c in adjacent.items()}
        self.competition = {
            p: max([n for k, n in c.items() if k != self.country], default=0) for p, c in adjacent.items()
        }

        attack, self.defense = {}, {}
        for p, owner in b.owner.items():
            if owner == self.country:
                enemies = [k for k, n in adjacent.get(p, {}).items() if k != self.country and n]
                self.defense[p] = max([sizes[k] for k in enemies], default=0)
            else:
                attack[p] = sizes[owner] if owner is not None else neutral_size

        spring_like = self.spring or self.phase == "Builds"
        w_att = config.SPRING_ATTACK_WEIGHT if spring_like else config.FALL_ATTACK_WEIGHT
        w_def = config.SPRING_DEFENSE_WEIGHT if spring_like else config.FALL_DEFENSE_WEIGHT
        prox = [
            {n: attack.get(b.province(n[1]), 0) * w_att + self.defense.get(b.province(n[1]), 0) * w_def
             for n in b.nodes}
        ]
        for _ in range(1, config.PROXIMITY_DEPTHS):
            prev = prox[-1]
            cur = {}
            for n in b.nodes:
                p = b.province(n[1])
                own = max(prev[m] for m in b.nodes_in[p])
                others = sum(prev[m] for m in b.reached_by.get(p, ()))
                cur[n] = (own + others) / 5.0
            prox.append(cur)

        if self.phase == "Builds":
            weights = config.FALL_PROXIMITY_WEIGHTS
        else:
            weights = config.SPRING_PROXIMITY_WEIGHTS if self.spring else config.FALL_PROXIMITY_WEIGHTS
        self.value = {}
        for n in b.nodes:
            p = b.province(n[1])
            v = sum(w * prox[d][n] for d, w in enumerate(weights))
            if self.phase == "Builds":
                v += config.BUILD_DEFENSE_WEIGHT * self.defense.get(p, 0)
            else:
                v += config.STRENGTH_WEIGHT * self.strength.get(p, 0)
                v -= config.COMPETITION_WEIGHT * self.competition.get(p, 0)
            self.value[n] = v

    # --- decoding --------------------------------------------------------------------

    def pick(self, ranked, value):
        """DumbBot's randomized descent: near-ties to the next option are played sometimes."""
        i = 0
        while i + 1 < len(ranked):
            cur, nxt = value(ranked[i]), value(ranked[i + 1])
            chance = 0 if cur == 0 else abs(cur - nxt) * config.ALTERNATIVE_DIFF_MODIFIER / abs(cur)
            if config.PLAY_ALTERNATIVE > self.rng.random() >= chance:
                i += 1
                continue
            break
        if i:
            self.trace["alternative_picked"] += 1
        return ranked[i]

    def choose(self, slots):
        if not slots:
            return []
        if self.phase == "Builds":
            return self._adjustments(slots)
        if self.phase == "Retreats":
            return self._retreats(slots)
        return self._movement(slots)

    def _movement(self, slots):
        b = self.b
        by_id = {u["id"]: u for u in b.all_units}
        mine = [by_id[s["unitID"]] for s in slots]
        queue = mine[:]
        self.rng.shuffle(queue)
        prov = lambda u: b.province(u["terrID"])  # noqa: E731
        moving = {}  # province of our moving unit -> destination node
        waiting_on = {prov(u): set() for u in mine}
        orders = {}
        deferrals = Counter()
        mine_at = {prov(u): u for u in mine}

        while queue:
            u = queue.pop(0)
            here = b.node(u)
            p = prov(u)
            dests = sorted(
                [m for m in b.moves[here] if b.province(m[1]) not in waiting_on[p]] + [here],
                key=lambda n: self.value[n],
                reverse=True,
            )
            while True:
                d = self.pick(dests, self.value.get)
                q = b.province(d[1])
                if q == p:
                    orders[p] = order("Hold", u["terrID"])
                    break
                occupant = mine_at.get(q)
                if occupant is not None and q not in orders:
                    if deferrals[p] >= 2:
                        # Deferral chains of 3+ units can cycle (the port has the same hole).
                        self.trace["deferral_cycle_broken"] += 1
                        dests.remove(d)
                        continue
                    # Can't decide until the unit in the way is ordered.
                    queue.insert(queue.index(occupant) + 1, u)
                    waiting_on[q].add(p)
                    deferrals[p] += 1
                    self.trace["deferred"] += 1
                    break
                if occupant is not None and q not in moving:
                    if self.competition.get(q, 0) > 1:
                        orders[p] = order("Support hold", u["terrID"], q)
                        self.trace["support_hold"] += 1
                        break
                    dests.remove(d)
                    continue
                mover = next((src for src, dest in moving.items() if b.province(dest[1]) == q), None)
                if mover is not None:
                    if self.competition.get(q, 0) > 0:
                        orders[p] = order("Support move", u["terrID"], q, mover)
                        self.trace["support_move"] += 1
                        break
                    dests.remove(d)
                    continue
                orders[p] = order("Move", u["terrID"], d[1])
                moving[p] = d
                break

        self._fill_wasted_holds(orders, moving, mine_at)
        return [self._legal_or_hold(by_id[s["unitID"]], orders[prov(by_id[s["unitID"]])]) for s in slots]

    def _fill_wasted_holds(self, orders, moving, mine_at):
        b = self.b
        for p, o in list(orders.items()):
            if o["type"] != "Hold":
                continue
            u = mine_at[p]
            best, best_value = None, 0
            for q in b.reach[b.node(u)]:
                mover = next((src for src, dest in moving.items() if b.province(dest[1]) == q), None)
                if mover is not None and self.competition.get(q, 0) > 0 and self.value[moving[mover]] > best_value:
                    best_value, best = self.value[moving[mover]], order("Support move", u["terrID"], q, mover)
                holder = mine_at.get(q)
                if (
                    holder is not None
                    and q not in moving
                    and self.competition.get(q, 0) > 1
                    and self.value[b.node(holder)] > best_value
                ):
                    best_value, best = self.value[b.node(holder)], order("Support hold", u["terrID"], q)
            if best is not None:
                orders[p] = best
                self.trace["wasted_hold_to_support"] += 1

    def _legal_or_hold(self, unit, chosen):
        legal = {order_signature(o) for o in self.b.legal.movement(unit)}
        if order_signature(chosen) in legal:
            self.trace[chosen["type"]] += 1
            return chosen
        self.trace["illegal_fallback_hold"] += 1
        return order("Hold", unit["terrID"])

    def _retreats(self, slots):
        b = self.b
        by_id = {u["id"]: u for u in b.all_units}
        taken = set()
        result = []
        for s in slots:
            u = by_id[s["unitID"]]
            options = [o for o in b.legal.retreats(u) if o["type"] == "Retreat"]
            options = [o for o in options if b.province(o["toTerrID"]) not in taken]
            if not options:
                result.append(order("Disband", u["terrID"]))
                self.trace["retreat_disband"] += 1
                continue
            ranked = sorted(options, key=lambda o: self.value.get((u["type"], o["toTerrID"]), 0), reverse=True)
            o = self.pick(ranked, lambda o: self.value.get((u["type"], o["toTerrID"]), 0))
            taken.add(b.province(o["toTerrID"]))
            result.append(o)
            self.trace["retreat"] += 1
        return result

    def _adjustments(self, slots):
        b = self.b
        own = [u for u in b.units if int(u["countryID"]) == self.country]
        if b.centers[self.country] < len(own):
            ranked = sorted(own, key=lambda u: self.value.get(b.node(u), 0))
            chosen = []
            for _ in slots:
                if not ranked:
                    break  # more removal slots than units (power being eliminated)
                u = self.pick(ranked, lambda u: -self.value.get(b.node(u), 0))
                ranked.remove(u)
                p = b.province(u["terrID"])
                chosen.append(order("Destroy", p, p))
                self.trace["destroy"] += 1
            return chosen
        candidates = b.legal.builds(self.country)
        unit_type = lambda o: "Army" if o["type"] == "Build Army" else "Fleet"  # noqa: E731
        ranked = sorted(candidates, key=lambda o: self.value.get((unit_type(o), o["toTerrID"]), 0), reverse=True)
        chosen = []
        for _ in slots:
            if not ranked:
                chosen.append(order("Wait"))
                self.trace["build_wait"] += 1
                break  # One Wait fills every remaining slot upstream.
            o = self.pick(ranked, lambda o: self.value.get((unit_type(o), o["toTerrID"]), 0))
            chosen.append(o)
            self.trace[o["type"]] += 1
            ranked = [c for c in ranked if b.province(c["toTerrID"]) != b.province(o["toTerrID"])]
        return chosen
