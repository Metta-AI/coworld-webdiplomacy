"""Real socket tests for the local bridge, including uncertain writes and lifecycle."""

import json
import queue
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from http.client import HTTPConnection
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from websockets.exceptions import ConnectionClosed
from websockets.sync.server import serve

from players.bridge import BridgeError, BridgeServer, TunnelClient, player_address, write_environment

HELLO = {
    "type": "hello",
    "protocol": "webdip-coworld/1",
    "capabilities": ["http-bot-api-v1"],
    "slot": 0,
    "webdip": {"game_id": 101, "country_id": 6},
    "rules": {"seed": 2},
}


def wait_for(predicate):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("Condition did not become true")


@contextmanager
def peer(handler):
    with serve(handler, "127.0.0.1", 0, close_timeout=0.1) as server:
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            yield f"ws://127.0.0.1:{server.socket.getsockname()[1]}/player?slot=0&token=private&mode=browser"
        finally:
            server.shutdown()
            thread.join(timeout=3)


class AddressTest(unittest.TestCase):
    def test_viewer_launch_and_proxy_prefix(self):
        url = "https://api.example/v2/jobs/id/proxy/client/player?slot=3&token=private"
        address = player_address(url)
        self.assertEqual(urlsplit(address).path, "/v2/jobs/id/proxy/player")
        self.assertEqual(urlsplit(address).scheme, "wss")
        self.assertEqual(parse_qs(urlsplit(address).query)["mode"], ["browser"])
        launch = json.dumps({"kind": "player", "viewer_url": url + "&" + urlencode({"address": address})})
        self.assertEqual(player_address(launch), address)

    def test_reject_unsafe_or_nonplayer_urls(self):
        for value in (
            "ws://example.com/player?slot=0&token=private",
            "wss://user:pass@example.com/player?slot=0&token=private",
            "wss://example.com/global?slot=0&token=private",
            "wss://example.com/player?slot=0&token=private&token=other",
            "wss://example.com/player?slot=0",
            '{"kind":"pending"}',
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                player_address(value)

    def test_environment_created_private_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bot.env"
            write_environment(path, {"WEBDIP_API_KEY": "secret with spaces"})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.read_text(), "export WEBDIP_API_KEY='secret with spaces'\n")
            with self.assertRaises(FileExistsError):
                write_environment(path, {"WEBDIP_API_KEY": "replacement"})


class SocketTest(unittest.TestCase):
    def test_http_fidelity_local_auth_and_public_files(self):
        requests = queue.Queue()

        def handler(ws):
            ws.send(json.dumps(HELLO))
            for raw in ws:
                request = json.loads(raw)
                requests.put(request)
                if request["path"] == "/bad-response":
                    ws.send(json.dumps({"type": "response", "id": request["id"], "body": None}))
                    continue
                ws.send(
                    json.dumps(
                        {
                            "type": "response",
                            "id": request["id"],
                            "status": 409,
                            "body": "upstream error: café",
                            "headers": {"content-type": "text/plain", "x-json": "saved", "set-cookie": "no"},
                        }
                    )
                )

        with peer(handler) as address:
            tunnel = TunnelClient(address)
            self.addCleanup(tunnel.close)
            with BridgeServer(tunnel) as server:
                thread = threading.Thread(target=server.serve_forever)
                thread.start()
                try:

                    def request(method, path, body=None, headers=None):
                        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=3)
                        connection.request(method, path, body, headers or {})
                        response = connection.getresponse()
                        result = response.status, dict(response.getheaders()), response.read().decode()
                        connection.close()
                        return result

                    self.assertEqual(request("GET", "/api.php?route=game/playercontext")[0], 401)
                    auth = {"Authorization": "Bearer " + server.api_key}
                    status, headers, body = request("POST", "/api.php?route=game/orders", '{"orders":[]}', auth)
                    self.assertEqual((status, body), (409, "upstream error: café"))
                    self.assertEqual(headers["x-json"], "saved")
                    self.assertNotIn("set-cookie", headers)
                    forwarded = requests.get(timeout=1)
                    self.assertEqual(forwarded["body"], '{"orders":[]}')
                    self.assertNotIn(server.api_key, json.dumps(forwarded))
                    self.assertEqual(request("GET", "/cache/games/1/101/game.json")[0], 409)
                    requests.get(timeout=1)
                    self.assertEqual(request("GET", "/bad-response", headers=auth)[0], 502)
                    requests.get(timeout=1)
                    self.assertEqual(request("POST", "/api.php", "x" * 131073, auth)[0], 413)
                    self.assertEqual(request("GET", "/api.php", headers=auth | {"Host": "evil.example"})[0], 403)
                    self.assertEqual(
                        request("GET", "/api.php", headers=auth | {"Origin": "https://evil.example"})[0], 403
                    )
                    self.assertEqual(request("GET", "https://evil.example/api.php", headers=auth)[0], 403)
                    self.assertTrue(requests.empty())
                finally:
                    server.shutdown()
                    thread.join(timeout=3)
                    tunnel.close()

    def test_dropped_write_is_not_replayed_and_next_request_works(self):
        requests = queue.Queue()
        connections = []

        def handler(ws):
            connections.append(ws)
            ws.send(json.dumps(HELLO))
            try:
                for raw in ws:
                    request = json.loads(raw)
                    requests.put(request)
                    if len(connections) == 1:
                        ws.close()
                        return
                    ws.send(json.dumps({"type": "response", "id": request["id"], "status": 200, "body": "ok"}))
            except ConnectionClosed:
                pass

        with peer(handler) as address:
            tunnel = TunnelClient(address)
            try:
                with self.assertRaises(BridgeError) as error:
                    tunnel.request("POST", "/api.php?route=game/sendmessage", "private press")
                self.assertEqual(error.exception.status, 503)
                wait_for(lambda: len(connections) == 2 and tunnel.ws is not None)
                self.assertEqual(requests.qsize(), 1)
                self.assertEqual(tunnel.request("GET", "/api.php?route=game/playercontext", "")["body"], "ok")
            finally:
                tunnel.close()

    def test_timeout_does_not_replay(self):
        requests = queue.Queue()

        def handler(ws):
            ws.send(json.dumps(HELLO))
            for raw in ws:
                requests.put(raw)  # Simulate an accepted write with a lost response.

        with peer(handler) as address:
            tunnel = TunnelClient(address, timeout=0.05)
            try:
                original = tunnel.ws
                with self.assertRaises(BridgeError) as error:
                    tunnel.request("POST", "/api.php?route=game/sendmessage", "private press")
                self.assertEqual(error.exception.status, 504)
                wait_for(lambda: tunnel.ws is not None and tunnel.ws is not original)
                self.assertEqual(requests.qsize(), 1)
            finally:
                tunnel.close()

    def test_idle_game_over_acknowledged_and_terminal(self):
        ack = queue.Queue()

        def handler(ws):
            ws.send(json.dumps(HELLO))
            ws.send(json.dumps({"type": "game_over", "results": {}}))
            ack.put(json.loads(ws.recv(timeout=2)))

        with peer(handler) as address:
            tunnel = TunnelClient(address)
            try:
                self.assertEqual(ack.get(timeout=3), {"type": "game_over_ack"})
                with self.assertRaises(BridgeError) as error:
                    tunnel.request("GET", "/api.php?route=game/playercontext", "")
                self.assertEqual(error.exception.status, 410)
            finally:
                tunnel.close()

    def test_old_server_fails_at_handshake(self):
        def handler(ws):
            ws.send(json.dumps(HELLO | {"capabilities": []}))
            try:
                ws.recv(timeout=2)
            except ConnectionClosed:
                pass

        with peer(handler) as address, self.assertRaisesRegex(BridgeError, "updated Coworld"):
            TunnelClient(address)

    def test_bot_mode_fails_at_handshake(self):
        def handler(ws):
            ws.send(json.dumps(HELLO | {"webdip": HELLO["webdip"] | {"api_key": "hosted-secret"}}))
            try:
                ws.recv(timeout=2)
            except ConnectionClosed:
                pass

        with peer(handler) as address, self.assertRaisesRegex(BridgeError, "bot mode"):
            TunnelClient(address)

    def test_replaced_seat_does_not_reconnect(self):
        connections = []

        def handler(ws):
            connections.append(ws)
            ws.send(json.dumps(HELLO))
            ws.send(json.dumps({"type": "seat_replaced"}))
            ws.close()

        with peer(handler) as address:
            tunnel = TunnelClient(address)
            try:
                wait_for(lambda: not tunnel.thread.is_alive())
                self.assertEqual(len(connections), 1)
                with self.assertRaises(BridgeError) as error:
                    tunnel.request("GET", "/api.php?route=game/playercontext", "")
                self.assertEqual(error.exception.status, 409)
            finally:
                tunnel.close()

    def test_reconnect_rejects_changed_seat_identity(self):
        connections = []

        def handler(ws):
            connections.append(ws)
            hello = HELLO if len(connections) == 1 else HELLO | {"webdip": {"game_id": 102, "country_id": 6}}
            ws.send(json.dumps(hello))
            if len(connections) == 1:
                ws.close()
            else:
                try:
                    ws.recv(timeout=2)
                except ConnectionClosed:
                    pass

        with peer(handler) as address:
            tunnel = TunnelClient(address)
            try:
                wait_for(lambda: len(connections) == 2 and not tunnel.thread.is_alive())
                with self.assertRaises(BridgeError) as error:
                    tunnel.request("POST", "/api.php?route=game/orders", "{}")
                self.assertEqual(error.exception.status, 502)
                self.assertIn("identity changed", str(error.exception))
            finally:
                tunnel.close()


if __name__ == "__main__":
    unittest.main()
