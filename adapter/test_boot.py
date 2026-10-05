"""Public failure diagnostics must not expose exception details."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from adapter.boot import network_diagnostics, report_failure
from adapter.supervisor import Supervisor


class BootDiagnosticsTests(unittest.TestCase):
    def test_socket_ownership_and_resolver_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "net").mkdir()
            (root / "123/fd").mkdir(parents=True)
            (root / "123/fd/4").symlink_to("socket:[456]")
            (root / "123/fd/5").symlink_to("/private-token-sentinel")
            (root / "123/fd/6").symlink_to("socket:[789]")
            (root / "net/udp").write_text(
                "header\n0: 0100007F:A123 0100007F:0035 01 0:0 0:0 0 0 0 456\n"
                "1: 0100007F:A124 0100007F:0035 01 0:0 0:0 0 0 0 999\n"
            )
            (root / "net/tcp6").write_text(
                "header\n0: 00000000000000000000000001000000:2328 "
                "00000000000000000000000000000000:0000 0A 0:0 0:0 0 0 0 321\n"
            )
            (root / "resolv.conf").write_text(
                "# private-comment-sentinel\nnameserver 127.0.0.1\nsearch example.test\noptions ndots:5\n"
            )
            (root / "hosts").write_text("127.0.0.1 localhost # private-comment-sentinel\n")
            supervisor = Supervisor()
            supervisor.children = [("php-fpm", Mock(pid=123)), ("exited", Mock(pid=124))]
            event = network_diagnostics(supervisor, proc=root, etc=root)
            self.assertEqual(event["listening_ports"], [9000])
            self.assertEqual(event["service_sockets"]["exited"], [])
            entries = {entry["fd"]: entry for entry in event["service_sockets"]["php-fpm"]}
            self.assertEqual(entries[4]["remote"], "0100007F:0035")
            self.assertEqual(entries[4]["protocol"], "udp")
            self.assertEqual(entries[6], {"fd": 6, "inode": "789"})
            self.assertEqual(len(entries), 2)
            self.assertEqual(event["resolver"], ["nameserver 127.0.0.1", "search example.test", "options ndots:5"])
            self.assertEqual(event["hosts"], ["127.0.0.1 localhost"])
            self.assertNotIn("sentinel", json.dumps(event))

    def test_failure_keeps_exception_message_private(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "logs").mkdir()
            (root / "logs/php-fpm.log").write_text("ready to handle connections\nprivate-fpm-log-sentinel")
            supervisor = Supervisor()
            supervisor.children = [("nginx", Mock(returncode=1, poll=Mock(return_value=1)))]
            output = io.StringIO()
            with patch("adapter.boot.RUN", root), contextlib.redirect_stdout(output):
                try:
                    raise RuntimeError("private-token-and-press-sentinel")
                except RuntimeError as error:
                    report_failure(error, supervisor)
            public = output.getvalue()
            self.assertNotIn("private-token-and-press-sentinel", public)
            self.assertNotIn("private-fpm-log-sentinel", public)
            event = json.loads(public)
            self.assertEqual(event["exception_type"], "RuntimeError")
            self.assertEqual(event["exited_services"], {"nginx": 1})
            self.assertTrue(event["fpm_ready"])
            self.assertFalse(event["fpm_started"])
            self.assertEqual(event["frames"][-1]["function"], "test_failure_keeps_exception_message_private")
            self.assertIn("private-token-and-press-sentinel", (root / "logs/boot-error.log").read_text())
