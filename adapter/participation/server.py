"""Attempt-private control socket with durable receipts around upstream mutations."""

import json
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler
from socketserver import ThreadingUnixStreamServer

from pydantic import ValidationError

from adapter.participation.models import Orders, Press, host_request
from adapter.participation.world import DiplomacyWorld


def now_ms():
    return int(time.time() * 1000)


class ParticipationServer:
    def __init__(self, *, episode, socket_path, journal_path, port):
        self.world = DiplomacyWorld(episode=episode, port=port)
        self.lock = threading.Lock()
        self.database = sqlite3.connect(journal_path, check_same_thread=False, isolation_level=None)
        self.database.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            CREATE TABLE IF NOT EXISTS controllers (seat TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS snapshots (seat TEXT PRIMARY KEY, revision INTEGER NOT NULL, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS receipts (
                seat TEXT NOT NULL, id TEXT NOT NULL, command TEXT NOT NULL, data TEXT NOT NULL,
                PRIMARY KEY (seat, id)
            );
        """)
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                try:
                    size = int(self.headers.get("content-length", "-1"))
                    if self.path != "/participation" or not 0 <= size <= 36 * 1024:
                        self.send_error(400)
                        return
                    request = host_request.validate_json(self.rfile.read(size))
                    with owner.lock:
                        response = owner.handle(request)
                    body = json.dumps(response).encode()
                    if len(body) > 256 * 1024:
                        raise ValueError("Response limit")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except (ValueError, ValidationError):
                    self.send_error(400)
                except Exception:
                    # Upstream failures can include a private request; only expose a safe status.
                    self.send_error(503)

        self.server = ThreadingUnixStreamServer(str(socket_path), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, name="participation")
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.database.close()

    def handle(self, request):
        if request.seat not in {f"seat-{slot}" for slot in range(7)}:
            raise ValueError("Unknown seat")
        slot = int(request.seat.removeprefix("seat-"))
        if request.operation == "observe":
            return {"operation": "observe", "snapshot": self.snapshot(slot=slot)}
        if request.operation == "bind":
            row = self.database.execute("SELECT data FROM controllers WHERE seat = ?", (request.seat,)).fetchone()
            previous = json.loads(row[0]) if row else None
            controller = request.controller.model_dump()
            if previous:
                if controller["generation"] < previous["generation"]:
                    raise ValueError("Stale controller")
                if controller["generation"] == previous["generation"]:
                    if controller["id"] != previous["id"]:
                        raise ValueError("Controller conflict")
                    old_expiry, new_expiry = previous["expiresAt"], controller["expiresAt"]
                    if (old_expiry is None) != (new_expiry is None) or (
                        old_expiry is not None and new_expiry < old_expiry
                    ):
                        raise ValueError("Lease moved backwards")
            self.database.execute(
                "INSERT OR REPLACE INTO controllers VALUES (?, ?)", (request.seat, json.dumps(controller))
            )
            return {"operation": "bind", "controller": controller}
        command_id = request.commandId if request.operation == "receipt" else request.command.id
        row = self.database.execute(
            "SELECT command, data FROM receipts WHERE seat = ? AND id = ?", (request.seat, command_id)
        ).fetchone()
        if request.operation == "receipt":
            return {"operation": "receipt", "receipt": json.loads(row[1]) if row else None}
        encoded = request.command.model_dump_json()
        if row:
            if row[0] != encoded:
                raise ValueError("Command conflict")
            return {"operation": "command", "receipt": json.loads(row[1])}
        command = request.command
        row = self.database.execute("SELECT data FROM controllers WHERE seat = ?", (request.seat,)).fetchone()
        controller = json.loads(row[0]) if row else None
        code = None
        if not controller or (controller["id"], controller["generation"]) != (command.controllerId, command.generation):
            code = "controller_replaced"
        elif controller["expiresAt"] is not None and controller["expiresAt"] <= now_ms():
            code = "controller_expired"
        snapshot = self.snapshot(slot=slot)
        window = snapshot["window"]
        if not code and (not window or command.windowId != window["id"] or window["deadlineAt"] <= now_ms()):
            code = "window_closed"
        if not code and command.kind not in window["commands"]:
            code = "command_unavailable"
        if not code:
            try:
                if command.kind == "orders":
                    Orders.model_validate(command.value)
                else:
                    Press.model_validate(command.value)
            except ValidationError:
                code = "invalid_action"
        receipt = {
            "id": command.id,
            "seat": request.seat,
            "status": "rejected" if code else "uncertain",
            "receivedAt": now_ms(),
            "resolvedAt": now_ms(),
            "revision": snapshot["revision"],
        }
        if code:
            receipt["code"] = code
        else:
            receipt["code"] = "application_unconfirmed"
        # Persist uncertainty before calling upstream. A crash must not repeat a press message or orders.
        self.database.execute(
            "INSERT INTO receipts VALUES (?, ?, ?, ?)", (request.seat, command.id, encoded, json.dumps(receipt))
        )
        if not code:
            try:
                status, outcome = self.world.apply(slot=slot, command=command, snapshot=snapshot)
                receipt["status"] = status
                receipt["resolvedAt"] = now_ms()
                if outcome:
                    receipt["code"] = outcome
                else:
                    receipt.pop("code", None)
            except Exception:
                pass  # Keep the durable uncertain receipt; never repeat an ambiguous upstream mutation.
            self.database.execute(
                "UPDATE receipts SET data = ? WHERE seat = ? AND id = ?",
                (json.dumps(receipt), request.seat, command.id),
            )
        return {"operation": "command", "receipt": receipt}

    def snapshot(self, *, slot):
        snapshot = self.world.observe(slot=slot)
        encoded = json.dumps(snapshot, sort_keys=True)
        row = self.database.execute(
            "SELECT revision, data FROM snapshots WHERE seat = ?", (snapshot["seat"],)
        ).fetchone()
        revision = 1 if row is None else row[0] + int(row[1] != encoded)
        self.database.execute(
            "INSERT OR REPLACE INTO snapshots VALUES (?, ?, ?)", (snapshot["seat"], revision, encoded)
        )
        return {**snapshot, "revision": revision}
