"""Launcher lifetime, artifact failure, and saved-order rejection contracts."""

import io
import json
import multiprocessing
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock

from websockets.sync.server import serve

from players.api import WebDiplomacy, order, order_difference
from players.launcher import finish_press, stop_child
from players.random_bot import submit


class PlayerTests(unittest.TestCase):
    def test_silent_drop_and_phase_race(self):
        api = Mock()
        context = {"game": {"turn": 0, "phase": "Diplomacy"}, "orders": {"orders": [order("Hold", 1)]}}
        api.orders.return_value = [order("Hold", 1)]
        api.context.return_value = context
        with self.assertRaisesRegex(ValueError, "changed random orders"):
            submit(api, context, [order("Move", 1, 2)])
        api.context.return_value = {"game": {"turn": 1, "phase": "Diplomacy"}}
        self.assertFalse(submit(api, context, [order("Move", 1, 2)]))
        self.assertTrue(any(order_difference([order("Hold", 1)], [order("Hold", 1), order("Hold", 2)]).values()))
        self.assertFalse(any(order_difference([order("Wait")], [order("Wait"), order("Wait")], 2).values()))

    def launcher_case(
        self, *, long=False, cancelled=False, upload_fails=False, http_upload=False, close_early=False, child_code=None
    ):
        state = {"status": 200, "connections": 0, "put": None}
        sentinel = "private-player-test-sentinel"

        class HTTP(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                self.send_response(state["status"])
                self.end_headers()
                if state["status"] == 200:
                    self.wfile.write(json.dumps({"messages": {"messages": [dict(id=1, message=sentinel)]}}).encode())

            def do_PUT(self):
                self.server.content_type = self.headers["Content-Type"]
                state["put"] = self.rfile.read(int(self.headers["Content-Length"]))
                self.send_response(500 if upload_fails else 200)
                self.end_headers()

        http = ThreadingHTTPServer(("127.0.0.1", 0), HTTP)
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{http.server_port}"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "player.log"
            artifact = Path(directory) / "press.zip"
            hello = dict(
                type="hello",
                protocol="webdip-coworld/1",
                rules={"seed": 42},
                slot=3,
                webdip=dict(base_url=base, api_key="fixture-key", game_id=1, country_id=2),
            )

            def handle(ws):
                state["connections"] += 1
                ws.send(json.dumps(hello))
                if long and state["connections"] == 1:
                    time.sleep(1)
                    ws.close()
                    return
                time.sleep(41 if long else 3)
                if cancelled:
                    state["status"] = 404
                state["finished"] = time.monotonic()
                ws.send(json.dumps({"type": "game_over"}))
                if close_early:
                    ws.close()
                    return
                self.assertEqual(json.loads(ws.recv(timeout=18))["type"], "game_over_ack")
                state["ack"] = True

            with serve(handle, "127.0.0.1", 0, ping_interval=1, ping_timeout=2) as server:
                serving = threading.Thread(target=server.serve_forever, daemon=True)
                serving.start()
                address = f"ws://127.0.0.1:{server.socket.getsockname()[1]}/player?slot=0&token=test"
                command = "import time; time.sleep(120)" if child_code is None else f"raise SystemExit({child_code})"
                command = "import os; assert os.environ['WEBDIP_SEED'] == '297'; " + command
                env = {
                    **os.environ,
                    "COWORLD_PLAYER_WS_URL": address,
                    "COWORLD_PLAYER_ARTIFACT_UPLOAD_URL": base + "/upload?private=secret"
                    if upload_fails or http_upload
                    else artifact.as_uri(),
                }
                with output.open("w") as log:
                    process = subprocess.Popen(
                        [sys.executable, "-m", "players.launcher", sys.executable, "-c", command],
                        env=env,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                    )
                    try:
                        code = process.wait(timeout=65 if long else 25)
                    finally:
                        if process.poll() is None:
                            process.kill()
                            process.wait()
                server.shutdown()
            text = output.read_text()
            if not close_early:
                self.assertTrue(state.get("ack"), text)
            self.assertEqual(code, child_code or 0, text)
            self.assertLess(time.monotonic() - state["finished"], 20)
            self.assertIn(sentinel, text)
            self.assertNotIn("fixture-key", text)
            self.assertNotIn("private=secret", text)
            data = state["put"] if upload_fails or http_upload else artifact.read_bytes()
            with zipfile.ZipFile(io.BytesIO(data)) as zipped:
                record = json.loads(zipped.read("private-press.json"))
            self.assertEqual(record["complete"], not cancelled)
            if long:
                self.assertEqual(state["connections"], 2)
            if upload_fails:
                self.assertEqual(http.content_type, "application/zip")
                self.assertIn('"status":"failed"', text)
        http.shutdown()
        http.server_close()

    def test_long_presence_and_reconnect(self):
        self.launcher_case(long=True, http_upload=True)

    def test_cancel_cache_and_early_child_failure(self):
        self.launcher_case(cancelled=True, child_code=7)

    def test_optional_upload_failure(self):
        self.launcher_case(upload_fails=True)

    def test_server_closes_before_ack(self):
        self.launcher_case(close_early=True)

    def test_hard_worker_deadline_and_stubborn_child(self):
        context = multiprocessing.get_context("spawn")
        receiver, sender = context.Pipe(duplex=False)
        worker = context.Process(target=time.sleep, args=(60,))
        worker.start()
        started = time.monotonic()
        finish_press(worker, sender, "game_over")
        self.assertLess(time.monotonic() - started, 15)
        self.assertFalse(worker.is_alive())
        receiver.close()
        child = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "print('ready',flush=True); time.sleep(60)",
            ],
            start_new_session=True,
            stdout=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(child.stdout.readline().strip(), "ready")
        stop_child(child)
        child.stdout.close()
        self.assertEqual(child.returncode, -9)

    def test_empty_200_is_not_valid_api_context(self):
        class Empty(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()

            def log_message(self, *_):
                pass

        with ThreadingHTTPServer(("127.0.0.1", 0), Empty) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            api = WebDiplomacy(f"http://127.0.0.1:{server.server_port}", "bad-key", 1, 1)
            with self.assertRaises(json.JSONDecodeError):
                api.context()
            server.shutdown()


if __name__ == "__main__":
    unittest.main()
