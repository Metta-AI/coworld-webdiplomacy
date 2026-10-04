"""Public failure diagnostics must not expose exception details."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from adapter.boot import report_failure
from adapter.supervisor import Supervisor


class BootDiagnosticsTests(unittest.TestCase):
    def test_failure_keeps_exception_message_private(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "logs").mkdir()
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
            event = json.loads(public)
            self.assertEqual(event["exception_type"], "RuntimeError")
            self.assertEqual(event["exited_services"], {"nginx": 1})
            self.assertEqual(event["frames"][-1]["function"], "test_failure_keeps_exception_message_private")
            self.assertIn("private-token-and-press-sentinel", (root / "logs/boot-error.log").read_text())
