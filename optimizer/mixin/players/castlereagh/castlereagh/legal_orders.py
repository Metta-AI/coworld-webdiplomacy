"""Classic legal inputs from webDip's variant graph and public board, without adjudicating.

The checks follow upstream board/orders/{diplomacy,retreats,builds}.php. An order
can be legal and still bounce, lose support, or have its convoy disrupted.

Vendored verbatim (imports aside) from coworld-webdiplomacy `players/legal_orders.py` at
commit b4aca731; see webdip_api.py for why. The search's behaviour depends on this exact
generator (the golden test pins it), so re-sync deliberately and re-run the golden test.
"""

from collections import deque

from castlereagh.webdip_api import order


class LegalOrders:
    def __init__(self, variant, board):
        self.territories = {item["id"]: item for item in variant["territories"]}
        self.board = board
        # Upstream omits untouched neutral provinces from TerrStatus.
        self.status = {
            territory["id"]: {"ownerCountryID": None, "unitID": None, "standoff": False, "occupiedFromTerrID": None}
            for territory in variant["territories"]
            if territory["coast"] != "Child"
        }
        self.status.update({item["terrID"]: item for item in board["territories"]})
        self.units = [unit for unit in board["units"] if not unit["retreating"]]
        self.at_sea = {unit["terrID"] for unit in self.units if self.territories[unit["terrID"]]["type"] == "Sea"}

    def parent(self, territory):
        return self.territories[territory]["coastParentID"]

    def adjacent(self, territory, unit_type, graph="coastalBorders"):
        return [edge["id"] for edge in self.territories[territory][graph] if edge[unit_type.lower()]]

    def convoy_paths(self, source, *, through=None, exclude=None):
        """One simple path per reachable coast, optionally through a specific fleet.

        BFS state retains the visited chain: a repeated sea would be an invalid
        convoy. There are at most 19 sea provinces on Classic.
        """
        queue = deque([[source]])
        paths = {}
        visited = set()
        while queue:
            path = queue.popleft()
            last = path[-1]
            for target in self.adjacent(last, "Fleet", "borders"):
                target = self.parent(target)
                if target == source or target == exclude or target in path:
                    continue
                if self.territories[target]["type"] == "Coast" and len(path) > 1:
                    if through is None or through in path:
                        paths.setdefault(target, path)
                elif target in self.at_sea:
                    # Keep the visited set in the search key; different simple paths
                    # may be necessary to include a requested convoying fleet.
                    state = (target, frozenset(path))
                    if state not in visited:
                        visited.add(state)
                        queue.append([*path, target])
        return paths

    def moves(self, unit):
        origin = unit["terrID"]
        result = [order("Move", origin, target) for target in self.adjacent(origin, unit["type"])]
        if unit["type"] == "Army" and self.territories[origin]["type"] == "Coast":
            result += [
                order("Move", origin, target, viaConvoy="Yes", convoyPath=path)
                for target, path in self.convoy_paths(origin).items()
            ]
        return result

    def movement(self, unit):
        origin = unit["terrID"]
        result = [order("Hold", origin), *self.moves(unit)]
        hold_destinations = {self.parent(t) for t in self.adjacent(origin, unit["type"])}
        support_destinations = {self.parent(t) for t in self.adjacent(origin, unit["type"], "borders")}
        for other in self.units:
            source = other["terrID"]
            if other["id"] == unit["id"]:
                continue
            if self.parent(source) in hold_destinations:
                result.append(order("Support hold", origin, self.parent(source)))
            for move in self.moves(other):
                target = self.parent(move["toTerrID"])
                if target not in support_destinations:
                    continue
                path = move.get("convoyPath")
                if path and origin in path:
                    path = self.convoy_paths(source, exclude=origin).get(target)
                    if not path:
                        continue
                extra = {"convoyPath": path} if path else {}
                result.append(order("Support move", origin, target, self.parent(source), **extra))
            if origin in self.at_sea and other["type"] == "Army" and self.territories[source]["type"] == "Coast":
                for target, path in self.convoy_paths(source, through=origin).items():
                    result.append(order("Convoy", origin, target, source, convoyPath=path))
        # Split-coast moves can produce the same province-level support twice.
        unique = {}
        for item in result:
            key = (item["type"], item["toTerrID"], item["fromTerrID"], item["viaConvoy"])
            unique.setdefault(key, item)
        return list(unique.values())

    def retreats(self, unit):
        origin = unit["terrID"]
        attacked_from = self.status[self.parent(origin)]["occupiedFromTerrID"]
        result = [order("Disband", origin)]
        for target in self.adjacent(origin, unit["type"]):
            status = self.status[self.parent(target)]
            if status["unitID"] is not None or status["standoff"]:
                continue
            if attacked_from and self.parent(target) == self.parent(attacked_from):
                continue
            result.append(order("Retreat", origin, target))
        return result

    def builds(self, country):
        result = []
        for territory in self.territories.values():
            if territory["coast"] == "Child" or not territory["supply"] or territory["homeCountryID"] != country:
                continue
            target = territory["id"]
            status = self.status[target]
            if status["ownerCountryID"] != country or status["unitID"] is not None:
                continue
            result.append(order("Build Army", target, target))
            if territory["type"] == "Coast":
                coasts = [
                    t["id"]
                    for t in self.territories.values()
                    if t["coastParentID"] == target and t["coast"] != "Parent"
                ]
                result += [order("Build Fleet", coast, coast) for coast in coasts]
        return result

    def choose(self, context, rng):
        phase = context["game"]["phase"]
        country = context["member"]["countryID"]
        slots = context["orders"]["orders"]
        if not slots:
            return []
        if phase == "Builds":
            own_units = [unit for unit in self.units if unit["countryID"] == country]
            centers = sum(
                self.territories[t]["supply"] and state["ownerCountryID"] == country for t, state in self.status.items()
            )
            if centers < len(own_units):
                # Destroy takes the parent province even if the fleet occupies a child coast.
                return [
                    order("Destroy", self.parent(unit["terrID"]), self.parent(unit["terrID"]))
                    for unit in rng.sample(own_units, len(slots))
                ]
            candidates = self.builds(country)
            chosen = []
            for _ in slots:
                if not candidates:
                    chosen.append(order("Wait"))
                    break  # One Wait fills every remaining free slot in the upstream API.
                item = rng.choice(candidates)
                chosen.append(item)
                candidates = [
                    candidate
                    for candidate in candidates
                    if self.parent(candidate["toTerrID"]) != self.parent(item["toTerrID"])
                ]
            return chosen
        units = {unit["id"]: unit for unit in self.board["units"]}
        return [
            rng.choice(
                self.retreats(units[item["unitID"]]) if phase == "Retreats" else self.movement(units[item["unitID"]])
            )
            for item in slots
        ]
