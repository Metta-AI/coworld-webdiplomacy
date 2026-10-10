"""Order keys and the conversion of webDip orders into fastadj inputs."""

from castlereagh.dipmap import DipMap

_MAPS = {}


def dipmap(variant):
    key = variant["variantID"]
    if key not in _MAPS:
        _MAPS[key] = DipMap(variant["territories"])
    return _MAPS[key]


def _key(o):
    return (o["type"], o["terrID"], o["toTerrID"], o["fromTerrID"])


def _same(a, b):
    return _key(a) == _key(b)


def fast_orders(units, orders, parent):
    """webDip units + parallel movement orders -> fastadj (units, order tuples), province level.

    Convoys are approximated: a convoying fleet holds; a convoyed army move becomes a plain
    move when every fleet on its path is ordered to convoy exactly that move, otherwise a
    hold. This ignores convoy disruption by dislodging a fleet, which is fine for
    *evaluating* hypotheticals. (The lab could switch this off and fall back to the
    `diplomacy` package; that path was never the default and is not carried here.)"""
    fu, fo = [], []
    convoys = None
    for u, o in zip(units, orders):
        fu.append((int(u["countryID"]), parent[u["terrID"]], u["type"]))
        kind = o["type"]
        if kind == "Move":
            if o.get("viaConvoy") in ("Yes", True):
                if convoys is None:
                    convoys = {
                        (parent[c["terrID"]], parent[c["fromTerrID"]], parent[c["toTerrID"]])
                        for c in orders if c["type"] == "Convoy"
                    }
                src, dst = parent[o["terrID"]], parent[o["toTerrID"]]
                path = (o.get("convoyPath") or [])[1:]
                if path and all((parent[f], src, dst) in convoys for f in path):
                    fo.append(("M", dst))
                else:
                    fo.append(("H",))
                continue
            fo.append(("M", parent[o["toTerrID"]]))
        elif kind == "Support hold":
            fo.append(("SH", parent[o["toTerrID"]]))
        elif kind == "Support move":
            fo.append(("SM", parent[o["fromTerrID"]], parent[o["toTerrID"]]))
        else:  # Hold, and Convoy (a convoying fleet holds)
            fo.append(("H",))
    return fu, fo
