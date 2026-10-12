"""Seat-scoped access to the upstream API without exposing upstream credentials."""

import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from adapter.episode import php
from adapter.participation.models import Orders, Press
from players.api import order_signature


class DiplomacyWorld:
    def __init__(self, *, episode, port):
        self.episode = episode
        self.origin = f"http://127.0.0.1:{port}"

    def call(self, *, slot, route, query=None, value=None):
        params = {"route": route, **(query or {})}
        request = Request(
            self.origin + "/api.php?" + urlencode(params),
            data=json.dumps(value).encode() if value is not None else None,
            headers={"Authorization": "Bearer " + self.episode.config.tokens[slot], "Content-Type": "application/json"},
        )
        with urlopen(request, timeout=10) as response:
            body = response.read(256 * 1024 + 1)
        if len(body) > 256 * 1024:
            raise ValueError("Upstream response too large")
        return json.loads(body)

    def observe(self, *, slot):
        country = self.episode.countries[slot]
        context = self.call(
            slot=slot,
            route="game/playercontext",
            query={"gameID": self.episode.game_id, "countryID": country, "orders": 1},
        )
        game = context["game"]
        active = (
            game["phase"] in ("Diplomacy", "Retreats", "Builds")
            and game["processStatus"] == "Not-processing"
            and context["member"]["status"] == "Playing"
        )
        window = None
        if active and game.get("processTime"):
            commands = ["orders"]
            if game["pressType"] != "NoPress":
                commands.append("press")
            window = {
                "id": f"{game['turn']}-{game['phase']}",
                "deadlineAt": int(game["processTime"]) * 1000,
                "commands": commands,
            }
        with self.episode.lock:
            public = {key: value for key, value in self.episode.public.items() if key not in ("history", "messages")}
            public_messages = self.episode.public.get("messages", {}).get("messages", [])
        public["messages"] = {"messages": public_messages[-16:], "truncated": len(public_messages) > 16}
        messages = php("wdc_messages", self.episode.game_id, country)
        orders = (context.get("orders") or {}).get("orders", [])
        return {
            "protocol": 1,
            "seat": f"seat-{slot}",
            "window": window,
            "finished": game["phase"] == "Finished",
            "observation": {
                "game": game,
                "countryId": country,
                "member": context["member"],
                "orders": orders,
                "messages": messages,
                "board": public,
            },
        }

    def apply(self, *, slot, command, snapshot):
        game = snapshot["observation"]["game"]
        country = self.episode.countries[slot]
        identity = {"gameID": self.episode.game_id, "countryID": country}
        if command.kind == "orders":
            action = Orders.model_validate(command.value)
            requested = [order.model_dump() for order in action.orders]
            result = self.call(
                slot=slot,
                route="game/orders",
                value={
                    **identity,
                    "turn": game["turn"],
                    "phase": game["phase"],
                    "orders": requested,
                    "ready": "Yes" if action.ready else "No",
                },
            )
            if not isinstance(result, list):
                return "uncertain", "invalid_upstream_response"
            # Upstream may silently discard invalid orders. Check the returned canonical orders.
            saved = {order_signature(order) for order in result}
            if any(order_signature(order) not in saved for order in requested):
                return "uncertain", "orders_partially_applied"
            return "applied", None
        action = Press.model_validate(command.value)
        result = php(
            "wdc_press",
            self.episode.game_id,
            country,
            payload={**action.model_dump(), "turn": game["turn"], "phase": game["phase"]},
        )
        if result["code"]:
            return "rejected", result["code"]
        return "applied", None
