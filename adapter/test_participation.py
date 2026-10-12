"""Recovery behavior at the private world mutation boundary."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from adapter.participation.models import host_request
from adapter.participation.server import ParticipationServer


class World:
    def __init__(self, **kwargs):
        self.effects = []
        self.drop_reply = False

    def observe(self, *, slot):
        return {
            "protocol": 1,
            "seat": f"seat-{slot}",
            "finished": False,
            "window": {"id": "spring", "deadlineAt": 9_000_000_000_000, "commands": ["press", "orders"]},
            "observation": {"country": slot},
        }

    def apply(self, *, slot, command, snapshot):
        self.effects.append((slot, command.value))
        if self.drop_reply:
            raise ConnectionError("Acknowledgement lost after upstream commit")
        return "applied", None


class ParticipationRecoveryTest(unittest.TestCase):
    def test_lost_reply_and_host_restart_never_repeat_private_press(self):
        with tempfile.TemporaryDirectory() as directory, patch("adapter.participation.server.DiplomacyWorld", World):
            path = Path(directory)
            server = ParticipationServer(
                episode=None, socket_path=path / "first.sock", journal_path=path / "journal.sqlite", port=1
            )
            try:
                server.handle(
                    host_request.validate_python(
                        {
                            "operation": "bind",
                            "seat": "seat-0",
                            "controller": {"id": "owner", "generation": 1, "expiresAt": None},
                        }
                    )
                )
                command = {
                    "operation": "command",
                    "seat": "seat-0",
                    "command": {
                        "id": "private-message",
                        "controllerId": "owner",
                        "generation": 1,
                        "windowId": "spring",
                        "kind": "press",
                        "value": {"toCountryID": 2, "message": "A private proposal"},
                    },
                }
                server.world.drop_reply = True
                first = server.handle(host_request.validate_python(command))
                self.assertEqual(first["receipt"]["status"], "uncertain")
                self.assertEqual(len(server.world.effects), 1)
                self.assertEqual(server.handle(host_request.validate_python(command)), first)
                self.assertEqual(len(server.world.effects), 1)
            finally:
                server.close()
            restarted = ParticipationServer(
                episode=None, socket_path=path / "second.sock", journal_path=path / "journal.sqlite", port=1
            )
            try:
                self.assertEqual(restarted.handle(host_request.validate_python(command)), first)
                self.assertEqual(restarted.world.effects, [])
                command["command"]["value"]["message"] = "Different content"
                with self.assertRaisesRegex(ValueError, "Command conflict"):
                    restarted.handle(host_request.validate_python(command))
            finally:
                restarted.close()

    def test_replaced_controller_and_closed_window_cannot_mutate_upstream(self):
        with tempfile.TemporaryDirectory() as directory, patch("adapter.participation.server.DiplomacyWorld", World):
            path = Path(directory)
            server = ParticipationServer(
                episode=None, socket_path=path / "control.sock", journal_path=path / "journal.sqlite", port=1
            )
            try:
                for generation in (1, 2):
                    server.handle(
                        host_request.validate_python(
                            {
                                "operation": "bind",
                                "seat": "seat-0",
                                "controller": {
                                    "id": f"owner-{generation}",
                                    "generation": generation,
                                    "expiresAt": None,
                                },
                            }
                        )
                    )
                for identifier, owner, generation, window, code in (
                    ("old-owner", "owner-1", 1, "spring", "controller_replaced"),
                    ("old-phase", "owner-2", 2, "winter", "window_closed"),
                ):
                    result = server.handle(
                        host_request.validate_python(
                            {
                                "operation": "command",
                                "seat": "seat-0",
                                "command": {
                                    "id": identifier,
                                    "controllerId": owner,
                                    "generation": generation,
                                    "windowId": window,
                                    "kind": "orders",
                                    "value": {"orders": [], "ready": True},
                                },
                            }
                        )
                    )
                    self.assertEqual(result["receipt"]["status"], "rejected")
                    self.assertEqual(result["receipt"]["code"], code)
                self.assertEqual(server.world.effects, [])
            finally:
                server.close()


if __name__ == "__main__":
    unittest.main()
