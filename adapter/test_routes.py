"""Server-side takeover and completion ordering, without an upstream game."""

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.testclient import TestClient

from adapter.config import EpisodeConfig
from adapter.routes import install_routes


class LifecycleTest(unittest.TestCase):
    def setUp(self):
        self.episode = SimpleNamespace(
            lock=threading.Lock(),
            config=EpisodeConfig(tokens=[f"token{i}" for i in range(7)]),
            seats=[{"country_id": i + 1, "country": str(i + 1), "user_id": i + 1} for i in range(7)],
            connections={},
            acknowledged=set(),
            game_id=1,
            started=False,
            finished=False,
            result={},
        )
        self.app = FastAPI()
        install_routes(self.app, self.episode)
        self.address = "/player?slot=0&token=token0&mode=browser"

    def test_replaced_socket_receives_notice_before_close(self):
        with TestClient(self.app) as client, client.websocket_connect(self.address) as first:
            self.assertEqual(first.receive_json()["type"], "hello")
            with client.websocket_connect(self.address) as second:
                self.assertEqual(second.receive_json()["type"], "hello")
                self.assertEqual(first.receive_json(), {"type": "seat_replaced"})
                with self.assertRaises(WebSocketDisconnect):
                    first.receive_json()

    def test_completion_is_recorded_before_confirmation(self):
        self.episode.finished = True
        with TestClient(self.app) as client, client.websocket_connect(self.address) as socket:
            socket.receive_json()
            self.assertEqual(socket.receive_json()["type"], "game_over")
            socket.send_json({"type": "game_over_ack"})
            self.assertEqual(socket.receive_json(), {"type": "game_over_acknowledged"})
            self.assertEqual(self.episode.acknowledged, {0})

    def test_confirmation_failure_does_not_lose_acknowledgment(self):
        self.episode.finished = True
        original = WebSocket.send_json
        attempted = threading.Event()

        async def send(socket, data, mode="text"):
            if data.get("type") == "game_over_acknowledged":
                attempted.set()
                raise WebSocketDisconnect(code=1006)
            await original(socket, data, mode=mode)

        with patch.object(WebSocket, "send_json", send):
            with TestClient(self.app) as client, client.websocket_connect(self.address) as socket:
                socket.receive_json()
                socket.receive_json()
                socket.send_json({"type": "game_over_ack"})
                self.assertTrue(attempted.wait(timeout=2))
                self.assertEqual(self.episode.acknowledged, {0})


if __name__ == "__main__":
    unittest.main()
