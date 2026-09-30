"""Synchronous client for the upstream webDiplomacy API."""

import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class WebDiplomacy:
    def __init__(self, url, key, game_id, country_id):
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
        with urlopen(request, timeout=10) as response:
            return response.read().decode() if raw else json.load(response)

    def context(self):
        return self.request("game/playercontext", gameID=self.game_id, orders=1, messages=1)

    def orders(self, context, orders):
        return self.request(
            "game/orders",
            body={
                "gameID": self.game_id,
                "countryID": self.country_id,
                "turn": context["game"]["turn"],
                "phase": context["game"]["phase"],
                "ready": "Yes",
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
