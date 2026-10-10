"""Synchronous webDiplomacy API client and order helpers.

Vendored verbatim from coworld-webdiplomacy `players/api.py` at commit b4aca731 (the
build's PINNED_GAME_REF), so this package runs and tests without the coworld checkout:
the lab that holds this policy lives outside that repository, and its own `players/`
directory would shadow the coworld `players` package on import. Re-sync when the pin moves.
"""

import json
from collections import Counter
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class WebDiplomacy:
    def __init__(self, url, key, game_id, country_id, timeout=10):
        self.timeout = timeout
        self.url = url.rstrip("/")
        self.key = key
        self.game_id = int(game_id)
        self.country_id = int(country_id)

    def request(self, route, body=None, *, raw=False, **params):
        request = Request(
            self.url + "/api.php?" + urlencode({"route": route, **params}),
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": "Bearer " + self.key, "Content-Type": "application/json"},
        )
        with urlopen(request, timeout=self.timeout) as response:
            return response.read().decode() if raw else json.load(response)

    def context(self):
        return self.request("game/playercontext", gameID=self.game_id, orders=1, messages=1)

    def file(self, reference):
        with urlopen(self.url + "/" + reference["url"], timeout=self.timeout) as response:
            return json.load(response)

    def orders(self, context, orders, *, ready="Yes"):
        return self.request(
            "game/orders",
            body={
                "gameID": self.game_id,
                "countryID": self.country_id,
                "turn": context["game"]["turn"],
                "phase": context["game"]["phase"],
                "ready": ready,
                "orders": orders,
            },
        )

    def vote(self, vote, enabled=True):
        return self.request(
            "game/setvote",
            raw=True,
            body={
                "gameID": self.game_id,
                "countryID": self.country_id,
                "vote": vote,
                "voteOn": "Yes" if enabled else "No",
            },
        )


def order(kind, territory=0, destination=0, source=0, **extra):
    return {
        "type": kind,
        "terrID": territory,
        "toTerrID": destination,
        "fromTerrID": source,
        "viaConvoy": "No",
        **extra,
    }


def holds(context):
    phase = context["game"]["phase"]
    orders = (context.get("orders") or {}).get("orders", [])
    if phase == "Builds":
        return [order("Wait")]
    return [order("Hold" if phase == "Diplomacy" else "Disband", int(item["terrID"])) for item in orders]


def order_signature(item):
    kind = item["type"]
    if kind in ("Build Army", "Build Fleet", "Destroy"):
        return kind, int(item["toTerrID"])
    if kind == "Wait":
        return (kind,)
    fields = [kind, int(item["terrID"])]
    if kind not in ("Hold", "Disband"):
        fields.append(int(item["toTerrID"]))
    if kind in ("Support move", "Convoy"):
        fields.append(int(item["fromTerrID"]))
    if kind == "Move":
        fields.append(item["viaConvoy"] in (True, "Yes"))
    return tuple(fields)


def order_difference(requested, saved, slots=None):
    desired = Counter(order_signature(item) for item in requested)
    if ("Wait",) in desired:
        desired[("Wait",)] = (len(saved) if slots is None else slots) - sum(
            count for signature, count in desired.items() if signature != ("Wait",)
        )
    actual = Counter(order_signature(item) for item in saved)
    return {"missing": list((desired - actual).elements()), "unexpected": list((actual - desired).elements())}


def verify_orders(requested, saved):
    difference = order_difference(requested, saved)
    if any(difference.values()):
        raise ValueError("Upstream changed orders: " + json.dumps(difference))
