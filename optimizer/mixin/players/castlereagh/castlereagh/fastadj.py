"""Fast movement adjudication for search (pure Python).

Implements Lucas Kruijswijk's "guess and check" resolution (the DATC reference design,
https://webdiplomacy.net/doc/DATC_v3_0.html section 5) restricted to Hold / Move /
Support hold / Support move. search_orders.fast_orders approximates convoys before
calling this. The lab differentially tested it against the `diplomacy` package on
non-convoy orders (its check_fastadj.py) and kept it as the reference for a Nim port;
this package uses it directly.

Inputs are province-level: `units` is a list of (country, province, unit_type) and
`orders` a parallel list of tuples:
    ("H",)                     hold (also: any order we do not model, treated as hold)
    ("M", dest_province)       move
    ("SH", target_province)    support hold
    ("SM", from_province, to_province)  support move
Output: (moved_ok, dislodged) — per unit, whether its move succeeded and whether it
was dislodged.
"""

UNRESOLVED, GUESSING, RESOLVED = 0, 1, 2


class Adjudicator:
    def __init__(self, units, orders):
        self.units = units
        self.orders = orders
        n = len(units)
        self.at = {u[1]: i for i, u in enumerate(units)}
        self.state = [UNRESOLVED] * n
        self.result = [False] * n
        self.deps = []
        # Precompute: moves into each province, supports for each unit's order.
        self.moves_into = {}
        for i, o in enumerate(orders):
            if o[0] == "M":
                self.moves_into.setdefault(o[1], []).append(i)
        self.supports_hold = {}
        self.supports_move = {}
        for i, o in enumerate(orders):
            if o[0] == "SH":
                j = self.at.get(o[1])
                if j is not None and orders[j][0] != "M":
                    self.supports_hold.setdefault(j, []).append(i)
            elif o[0] == "SM":
                j = self.at.get(o[1])
                if j is not None and orders[j][0] == "M" and orders[j][1] == o[2]:
                    self.supports_move.setdefault(j, []).append(i)

    # --- decisions -------------------------------------------------------------------

    def resolve(self, nr):
        if self.state[nr] == RESOLVED:
            return self.result[nr]
        if self.state[nr] == GUESSING:
            if nr not in self.deps:
                self.deps.append(nr)
            return self.result[nr]
        old = len(self.deps)
        self.result[nr] = False
        self.state[nr] = GUESSING
        first = self.adjudicate(nr)
        if len(self.deps) == old:
            if self.state[nr] != RESOLVED:
                self.result[nr] = first
                self.state[nr] = RESOLVED
            return first
        if self.deps[old] != nr:
            self.deps.append(nr)
            self.result[nr] = first
            return first
        # nr starts a cycle: try the other guess.
        for d in self.deps[old:]:
            self.state[d] = UNRESOLVED
        del self.deps[old:]
        self.result[nr] = True
        self.state[nr] = GUESSING
        second = self.adjudicate(nr)
        if first == second:
            for d in self.deps[old:]:
                self.state[d] = UNRESOLVED
            del self.deps[old:]
            self.result[nr] = first
            self.state[nr] = RESOLVED
            return first
        # Ambiguous without convoys only for circular movement: every move in the cycle succeeds.
        cycle = self.deps[old:]
        for d in cycle:
            self.state[d] = UNRESOLVED
        del self.deps[old:]
        for d in [nr, *cycle]:
            if self.orders[d][0] == "M":
                self.result[d] = True
                self.state[d] = RESOLVED
        return self.resolve(nr)

    def adjudicate(self, nr):
        kind = self.orders[nr][0]
        if kind == "M":
            return self._move_succeeds(nr)
        if kind in ("SH", "SM"):
            return self._support_holds(nr)
        return True

    def _support_holds(self, nr):
        """True if the support is NOT cut (and not dislodged)."""
        country, prov, _ = self.units[nr]
        o = self.orders[nr]
        for a in self.moves_into.get(prov, ()):
            if self.units[a][0] == country:
                continue
            if o[0] == "SM" and self.units[a][1] == o[2]:
                # Attack from the province the support is directed into: cuts only by dislodging.
                if self.resolve(a):
                    return False
                continue
            return False
        return True

    def _support_count(self, sups, exclude_country=None):
        n = 0
        for s in sups:
            if exclude_country is not None and self.units[s][0] == exclude_country:
                continue
            if self.resolve(s):
                n += 1
        return n

    def _head_to_head(self, nr):
        dest = self.orders[nr][1]
        j = self.at.get(dest)
        if j is not None and self.orders[j][0] == "M" and self.orders[j][1] == self.units[nr][1]:
            return j
        return None

    def _attack_strength(self, nr):
        dest = self.orders[nr][1]
        j = self.at.get(dest)
        h2h = self._head_to_head(nr)
        if j is None or (h2h is None and self.orders[j][0] == "M" and self.resolve(j)):
            return 1 + self._support_count(self.supports_move.get(nr, ()))
        if self.units[j][0] == self.units[nr][0]:
            return 0
        return 1 + self._support_count(self.supports_move.get(nr, ()), exclude_country=self.units[j][0])

    def _defend_strength(self, nr):
        return 1 + self._support_count(self.supports_move.get(nr, ()))

    def _prevent_strength(self, nr):
        h2h = self._head_to_head(nr)
        if h2h is not None and self.resolve(h2h):
            return 0
        return 1 + self._support_count(self.supports_move.get(nr, ()))

    def _hold_strength(self, prov):
        j = self.at.get(prov)
        if j is None:
            return 0
        if self.orders[j][0] == "M":
            return 0 if self.resolve(j) else 1
        return 1 + self._support_count(self.supports_hold.get(j, ()))

    def _move_succeeds(self, nr):
        dest = self.orders[nr][1]
        attack = self._attack_strength(nr)
        h2h = self._head_to_head(nr)
        if h2h is not None:
            if attack <= self._defend_strength(h2h):
                return False
        elif attack <= self._hold_strength(dest):
            return False
        for other in self.moves_into.get(dest, ()):
            if other != nr and attack <= self._prevent_strength(other):
                return False
        return True

    def run(self):
        n = len(self.units)
        moved = [self.orders[i][0] == "M" and self.resolve(i) for i in range(n)]
        dislodged = [False] * n
        for i in range(n):
            if moved[i]:
                continue
            for a in self.moves_into.get(self.units[i][1], ()):
                if moved[a]:
                    dislodged[i] = True
                    break
        return moved, dislodged


def adjudicate(units, orders):
    """(moved_ok, dislodged) for province-level units and orders (see the module docstring)."""
    return Adjudicator(units, orders).run()
