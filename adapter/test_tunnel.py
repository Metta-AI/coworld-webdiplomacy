"""The browser cannot use its transport as a general HTTP proxy or another seat."""

import json
import unittest
from urllib.parse import urlencode

from adapter.tunnel import Tunnel


class TunnelBoundaryTest(unittest.TestCase):
    def setUp(self):
        self.tunnel = object.__new__(Tunnel)
        self.tunnel.game_id = 101
        self.tunnel.seat = {"user_id": 5, "country_id": 6}

    def test_only_current_public_files(self):
        self.tunnel.validate({"path": "/cache/games/1/101/history.json?v=3"})
        for path in (
            "/cache/games/1/102/history.json",
            "/cache/games/1/101/../../config.php",
            "/config.php",
            "http://example.com/api.php",
            "//example.com/api.php",
            "/gamemaster.php",
            "/events",
            "/gamefile.php",
            "/api.php?route=client/error",
            "/api.php?route=sandbox/copy",
            "/api.php?route=game/playercontext&gameID=102",
            "/api.php?route=game/playercontext&gameID=101&gameID=102",
        ):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.tunnel.validate({"path": path})

    def test_signed_order_context_bound_to_seat(self):
        context = {"gameID": 101, "userID": 5, "countryID": 6, "isSandboxMode": False}

        def request(value):
            return {
                "method": "POST",
                "path": "/ajax.php?ready=on",
                "body": urlencode(
                    {"context": json.dumps(value), "contextKey": "upstream-signature", "orderUpdates": "[]"}
                ),
            }

        message = request(context)
        self.assertEqual(self.tunnel.validate(message)[2], message["body"])
        for key, value in (("gameID", 102), ("userID", 7), ("countryID", 2), ("isSandboxMode", True)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.tunnel.validate(request({**context, key: value}))
        with self.assertRaises(ValueError):
            self.tunnel.validate({**message, "path": "/ajax.php?likeMessageToggleToken=anything"})

    def test_api_method_and_game_binding(self):
        message = {"method": "POST", "path": "/api.php?route=game/sendmessage", "body": '{"gameID":101}'}
        self.tunnel.validate(message)
        with self.assertRaises(ValueError):
            self.tunnel.validate({**message, "body": '{"gameID":102}'})
        with self.assertRaises(ValueError):
            self.tunnel.validate({**message, "method": "GET"})
        with self.assertRaises(ValueError):
            self.tunnel.validate({**message, "body": "x" * 131073})

    def test_bot_orders_bound_to_game_and_country(self):
        body = {"gameID": 101, "countryID": 6, "turn": 0, "phase": "Diplomacy", "orders": [{"type": "Hold"}]}
        message = {"method": "POST", "path": "/api.php?route=game/orders", "body": json.dumps(body)}
        self.assertEqual(self.tunnel.validate(message)[2], message["body"])
        for changes in (
            {"gameID": 102},
            {"countryID": 7},
            {"sbToken": "secret"},
            {"orders": [{"countryID": 7}]},
            {"orders": [None]},
            {"orders": {}},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.tunnel.validate({**message, "body": json.dumps(body | changes)})
        for path in (
            "/api.php?route=game/orders&countryID=7",
            "/api.php?route=game/orders&gameID=102",
        ):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.tunnel.validate({**message, "path": path})
        with self.assertRaises(ValueError):
            self.tunnel.validate({**message, "method": "GET"})

    def test_toggle_vote_uses_upstream_get_and_seat_binding(self):
        message = {"path": "/api.php?route=game/togglevote&gameID=101&countryID=6&vote=Draw"}
        self.tunnel.validate(message)
        with self.assertRaises(ValueError):
            self.tunnel.validate({"path": message["path"].replace("countryID=6", "countryID=7")})
        with self.assertRaises(ValueError):
            self.tunnel.validate({**message, "method": "POST"})
