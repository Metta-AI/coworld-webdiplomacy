"""Delivery to the agent: the Claude Code hooks, agent status and the hook settings."""

import io
import json
import os
import subprocess
import sys
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from test_store import LabCase

from webdip_ide import hooks, paths, store

IDE = Path(__file__).resolve().parent.parent / "ide"


def run_hook(event: str, payload: dict | None = None) -> dict | None:
    """Run a hook in-process the way Claude Code does: JSON on stdin, at most one JSON object on stdout."""
    out = io.StringIO()
    with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload or {}))), redirect_stdout(out):
        code = hooks.run_hook(event)
    assert code == 0
    return json.loads(out.getvalue()) if out.getvalue().strip() else None


def fake_server() -> None:
    """Make the IDE look open: a server record that names a live process (this one)."""
    record = {"pid": os.getpid(), "port": 1, "url": "http://127.0.0.1:1", "started": time.time()}
    (paths.state_dir() / "server.json").write_text(json.dumps(record))


class HookCase(LabCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(hooks, "WAITER_GRACE_SECONDS", 0.0)
        patcher.start()
        self.addCleanup(patcher.stop)


class DeliveryHookTest(HookCase):
    def test_quiet_when_the_ide_is_not_in_use(self):
        for event in ("PostToolUse", "UserPromptSubmit", "Stop"):
            self.assertIsNone(run_hook(event))
        self.assertIsNone(store.agent_seen(), "an unused IDE must not look attached")

    def test_post_tool_use_hands_over_unread_messages_once(self):
        fake_server()
        store.post_message("user", "why did Austria fold?", {"episode": "ereq_9", "phase": 4})
        output = run_hook("PostToolUse", {"tool_name": "Bash"})
        context = output["hookSpecificOutput"]
        self.assertEqual(context["hookEventName"], "PostToolUse")
        self.assertIn("why did Austria fold?", context["additionalContext"])
        self.assertIn("episode ereq_9, phase 4", context["additionalContext"])
        self.assertIn("ide/ide say", context["additionalContext"])
        self.assertIsNone(run_hook("PostToolUse", {"tool_name": "Bash"}), "delivered twice")
        self.assertIsNone(run_hook("UserPromptSubmit"))

    def test_user_prompt_submit_delivers(self):
        fake_server()
        store.post_message("user", "hello")
        output = run_hook("UserPromptSubmit", {"prompt": "x"})
        self.assertEqual(output["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")

    def test_unread_messages_are_delivered_even_when_the_server_has_stopped(self):
        store.post_message("user", "left over from last night")
        self.assertIn("left over", run_hook("PostToolUse")["hookSpecificOutput"]["additionalContext"])

    def test_sub_agent_tool_calls_do_not_take_the_users_messages(self):
        fake_server()
        store.post_message("user", "for the main session")
        self.assertIsNone(run_hook("PostToolUse", {"agent_id": "abc", "tool_name": "Read"}))
        self.assertTrue(store.has_unread_for_agent())

    def test_stop_blocks_with_unread_messages(self):
        fake_server()
        hooks.register_listener()
        self.addCleanup(hooks.unregister_listener)
        store.post_message("user", "before you go")
        output = run_hook("Stop", {"stop_hook_active": False})
        self.assertEqual(output["decision"], "block")
        self.assertIn("before you go", output["reason"])
        self.assertIsNone(run_hook("Stop", {"stop_hook_active": True}))

    def test_stop_asks_for_a_listener_once_when_nothing_is_waiting(self):
        fake_server()
        output = run_hook("Stop", {"stop_hook_active": False})
        self.assertEqual(output["decision"], "block")
        self.assertIn("ide/ide listen", output["reason"])
        self.assertIsNone(run_hook("Stop", {"stop_hook_active": True}), "must not loop")

    def test_stop_is_quiet_when_a_waiter_is_registered(self):
        fake_server()
        hooks.register_listener()
        self.addCleanup(hooks.unregister_listener)
        self.assertIsNone(run_hook("Stop", {"stop_hook_active": False}))

    def test_session_start_says_the_ide_exists(self):
        closed = run_hook("SessionStart", {"source": "startup"})["hookSpecificOutput"]["additionalContext"]
        self.assertIn("ide/ide start --open", closed)
        self.assertIn("skills/ide/SKILL.md", closed)
        fake_server()
        self.assertIn("http://127.0.0.1:1", run_hook("SessionStart")["hookSpecificOutput"]["additionalContext"])

    def test_a_hook_never_fails_the_session(self):
        out = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO("this is not json")), redirect_stdout(out):
            with mock.patch.object(sys, "stderr", io.StringIO()):
                self.assertEqual(hooks.run_hook("PostToolUse"), 0)
                self.assertEqual(hooks.run_hook("NoSuchEvent"), 0)
        self.assertEqual(out.getvalue(), "")

    def test_annotations_named_in_the_context_are_spelled_out(self):
        fake_server()
        row = store.add_annotation(
            "ereq_9", "user", "trusted Turkey too long", tag="bad-trust", phase=9, power="TURKEY"
        )
        store.post_message("user", "fix this", {"episode": "ereq_9", "annotations": [row["id"]]})
        text = run_hook("PostToolUse")["hookSpecificOutput"]["additionalContext"]
        self.assertIn("[bad-trust] by user (phase 9, TURKEY): trusted Turkey too long", text)


class RewakeTest(HookCase):
    def _waiter(self) -> subprocess.Popen:
        env = dict(os.environ, WEBDIP_LAB=str(self.lab))
        return subprocess.Popen(
            [sys.executable, str(IDE), "hook", "Rewake"],
            env=env,
            stdin=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )

    def test_exits_at_once_when_the_ide_is_closed(self):
        waiter = self._waiter()
        self.assertEqual(waiter.wait(timeout=10), 0)
        waiter.stderr.close()

    def test_exits_2_with_the_message_on_stderr(self):
        fake_server()
        waiter = self._waiter()
        deadline = time.time() + 10
        while not hooks.listener_alive() and time.time() < deadline:
            time.sleep(0.05)
        self.assertTrue(hooks.listener_alive(), "the waiter must count as a listener")
        second = self._waiter()
        self.assertEqual(second.wait(timeout=10), 0, "only one waiter at a time")
        second.stderr.close()
        store.post_message("user", "wake up")
        _, stderr = waiter.communicate(timeout=10)
        self.assertEqual(waiter.returncode, 2)
        self.assertIn("wake up", stderr)
        self.assertFalse(store.has_unread_for_agent())
        self.assertFalse(hooks.listener_alive())


class StatusTest(HookCase):
    def test_states(self):
        self.assertEqual(hooks.agent_status()["state"], "none")
        store.touch_agent_seen()
        self.assertEqual(hooks.agent_status()["state"], "working")
        (paths.state_dir() / "agent_seen").write_text(str(time.time() - 3600))
        self.assertEqual(hooks.agent_status()["state"], "idle")
        hooks.register_listener()
        self.addCleanup(hooks.unregister_listener)
        self.assertEqual(hooks.agent_status()["state"], "listening")

    def test_waiting_counts_undelivered_user_messages(self):
        store.post_message("user", "a")
        store.post_message("agent", "b")
        store.post_message("user", "c")
        self.assertEqual(hooks.agent_status()["waiting"], 2)
        store.take_unread_for_agent()
        status = hooks.agent_status()
        self.assertEqual((status["waiting"], status["delivered"]), (0, 3))

    def test_a_dead_server_record_is_not_running(self):
        (paths.state_dir() / "server.json").write_text(json.dumps({"pid": 2**22 + 12345, "port": 1, "url": "x"}))
        self.assertIsNone(hooks.server_info())

    def test_dead_listener_records_are_cleared(self):
        (paths.state_dir() / "listeners").mkdir()
        (paths.state_dir() / "listeners" / str(2**22 + 12345)).write_text("0")
        self.assertFalse(hooks.listener_alive())
        self.assertEqual(list((paths.state_dir() / "listeners").iterdir()), [])


class SettingsTest(unittest.TestCase):
    def test_hook_settings_shape(self):
        settings = hooks.hook_settings()
        self.assertEqual(sorted(settings), ["PostToolUse", "SessionStart", "Stop", "UserPromptSubmit"])
        commands = [hook for entries in settings.values() for entry in entries for hook in entry["hooks"]]
        self.assertTrue(
            all(hook["command"].startswith('python3 "$CLAUDE_PROJECT_DIR/ide/ide" hook ') for hook in commands)
        )
        waiters = [hook for hook in commands if hook.get("asyncRewake")]
        self.assertEqual(len(waiters), 2)
        self.assertTrue(all(hook["command"].endswith("hook Rewake") for hook in waiters))
        self.assertTrue(all(hook["timeout"] <= 20 for hook in commands if not hook.get("asyncRewake")))


if __name__ == "__main__":
    unittest.main()
