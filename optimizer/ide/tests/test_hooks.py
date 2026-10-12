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


def fake_server(case: unittest.TestCase) -> None:
    """Make the IDE look open: a server record that names a live process (this one), which holds the server lock."""
    record = {"pid": os.getpid(), "port": 1, "url": "http://127.0.0.1:1", "started": time.time()}
    (paths.state_dir() / "server.json").write_text(json.dumps(record))
    case.addCleanup(hooks.hold_server_lock().close)


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
        fake_server(self)
        store.post_message("user", "why did Austria fold?", {"episode": "ereq_9", "phase": 4})
        output = run_hook("PostToolUse", {"tool_name": "Bash"})
        context = output["hookSpecificOutput"]
        self.assertEqual(context["hookEventName"], "PostToolUse")
        self.assertIn("why did Austria fold?", context["additionalContext"])
        self.assertIn("episode ereq_9, phase 4", context["additionalContext"])
        self.assertIn("ide/ide say", context["additionalContext"])
        self.assertIn("they will not see", context["additionalContext"])  # the terminal is not the answer
        self.assertIsNone(run_hook("PostToolUse", {"tool_name": "Bash"}), "delivered twice")
        self.assertIsNone(run_hook("UserPromptSubmit"))

    def test_user_prompt_submit_delivers(self):
        fake_server(self)
        store.post_message("user", "hello")
        output = run_hook("UserPromptSubmit", {"prompt": "x"})
        self.assertEqual(output["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")

    def test_unread_messages_are_delivered_even_when_the_server_has_stopped(self):
        store.post_message("user", "left over from last night")
        self.assertIn("left over", run_hook("PostToolUse")["hookSpecificOutput"]["additionalContext"])

    def test_sub_agent_tool_calls_do_not_take_the_users_messages(self):
        fake_server(self)
        store.post_message("user", "for the main session")
        self.assertIsNone(run_hook("PostToolUse", {"agent_id": "abc", "tool_name": "Read"}))
        self.assertTrue(store.has_unread_for_agent())

    def test_stop_blocks_with_unread_messages(self):
        fake_server(self)
        hooks.register_listener()
        self.addCleanup(hooks.unregister_listener)
        store.post_message("user", "before you go")
        output = run_hook("Stop", {"stop_hook_active": False})
        self.assertEqual(output["decision"], "block")
        self.assertIn("before you go", output["reason"])
        self.assertIsNone(run_hook("Stop", {"stop_hook_active": True}))

    def test_stop_asks_for_a_listener_once_when_nothing_is_waiting(self):
        fake_server(self)
        output = run_hook("Stop", {"stop_hook_active": False})
        self.assertEqual(output["decision"], "block")
        self.assertIn("ide/ide listen", output["reason"])
        self.assertIsNone(run_hook("Stop", {"stop_hook_active": True}), "must not loop")

    def test_stop_is_quiet_when_a_waiter_is_registered(self):
        fake_server(self)
        hooks.register_listener()
        self.addCleanup(hooks.unregister_listener)
        self.assertIsNone(run_hook("Stop", {"stop_hook_active": False}))

    def test_session_start_says_the_ide_exists(self):
        closed = run_hook("SessionStart", {"source": "startup"})["hookSpecificOutput"]["additionalContext"]
        self.assertIn("ide/ide start --open", closed)
        self.assertIn("skills/ide/SKILL.md", closed)
        fake_server(self)
        self.assertIn("http://127.0.0.1:1", run_hook("SessionStart")["hookSpecificOutput"]["additionalContext"])

    def test_session_start_asks_for_the_chat_file_to_be_watched(self):
        """A change to it runs the FileChanged waiter, so a message wakes a session that has no waiter left."""
        chat = paths.state_dir() / "chat.jsonl"
        self.assertFalse(chat.exists())
        output = run_hook("SessionStart", {"source": "startup"})["hookSpecificOutput"]
        self.assertEqual(output["watchPaths"], [str(chat)])
        self.assertTrue(chat.exists(), "there must be a file to watch before the first message")
        self.assertEqual(store.messages(), [])
        store.post_message("user", "hello")
        run_hook("SessionStart", {"source": "resume"})  # an existing chat is left as it is
        self.assertEqual([m["seq"] for m in store.messages()], [1])

    def test_a_hook_never_fails_the_session(self):
        out = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO("this is not json")), redirect_stdout(out):
            with mock.patch.object(sys, "stderr", io.StringIO()):
                self.assertEqual(hooks.run_hook("PostToolUse"), 0)
                self.assertEqual(hooks.run_hook("NoSuchEvent"), 0)
        self.assertEqual(out.getvalue(), "")

    def test_annotations_named_in_the_context_are_spelled_out(self):
        fake_server(self)
        row = store.add_annotation(
            "ereq_9", "user", "trusted Turkey too long", tag="bad-trust", phase=9, power="TURKEY"
        )
        store.post_message("user", "fix this", {"episode": "ereq_9", "annotations": [row["id"]]})
        text = run_hook("PostToolUse")["hookSpecificOutput"]["additionalContext"]
        self.assertIn("[bad-trust] by user (phase 9, TURKEY): trusted Turkey too long", text)


class OwnerTest(HookCase):
    """Hooks are wired per folder, so a second Claude Code session there runs them too. One session has the chat."""

    def test_the_first_session_to_run_a_hook_takes_the_chat(self):
        fake_server(self)
        store.post_message("user", "hello")
        self.assertIsNone(store.owner_session())
        self.assertIsNotNone(run_hook("PostToolUse", {"session_id": "a", "tool_name": "Read"}))
        self.assertEqual(store.owner_session(), "a")

    def test_another_session_gets_nothing_and_leaves_no_mark(self):
        fake_server(self)
        store.set_owner_session("a")
        store.post_message("user", "for the owner")
        for event in ("PostToolUse", "UserPromptSubmit", "Stop"):
            self.assertIsNone(run_hook(event, {"session_id": "b", "tool_name": "Read"}), event)
        self.assertIsNone(store.agent_seen())
        self.assertTrue(store.has_unread_for_agent())
        self.assertIn("for the owner", run_hook("Stop", {"session_id": "a"})["reason"])

    def test_the_session_that_runs_start_or_attach_takes_the_chat(self):
        fake_server(self)
        store.set_owner_session("a")
        for command in (
            "ide/ide start --open",
            'python3 "$CLAUDE_PROJECT_DIR/ide/ide" attach',
            "cd x && ide/ide  attach",
        ):
            store.set_owner_session("a")
            store.request_claim()  # what the command itself does when it runs
            run_hook("PostToolUse", {"session_id": "b", "tool_name": "Bash", "tool_input": {"command": command}})
            self.assertEqual(store.owner_session(), "b", command)
        for command in ("ide/ide status", "ide/ide say start", "echo side start"):
            store.request_claim()
            run_hook("PostToolUse", {"session_id": "a", "tool_name": "Bash", "tool_input": {"command": command}})
            self.assertEqual(store.owner_session(), "b", command)

    def test_a_command_that_only_mentions_attach_does_not_take_the_chat(self):
        # Seen live: a `tmux send-keys` whose text named the command took the chat from its owner.
        fake_server(self)
        store.set_owner_session("a")
        for command in ('tmux send-keys -t lab "ide/ide attach" Enter', "echo ide/ide start", "grep 'ide attach' x"):
            run_hook("PostToolUse", {"session_id": "b", "tool_name": "Bash", "tool_input": {"command": command}})
            self.assertEqual(store.owner_session(), "a", command)

    def test_a_claim_is_used_once_and_goes_stale(self):
        fake_server(self)
        store.set_owner_session("a")
        attach = {"tool_name": "Bash", "tool_input": {"command": "ide/ide attach"}}
        store.request_claim()
        run_hook("PostToolUse", {"session_id": "b", **attach})
        run_hook("PostToolUse", {"session_id": "c", **attach})
        self.assertEqual(store.owner_session(), "b")
        (paths.state_dir() / "claim_pending").write_text(str(time.time() - store.CLAIM_SECONDS - 1))
        run_hook("PostToolUse", {"session_id": "c", **attach})
        self.assertEqual(store.owner_session(), "b")

    def test_a_sub_agent_that_starts_the_ide_claims_for_its_session(self):
        fake_server(self)
        payload = {
            "session_id": "b",
            "agent_id": "sub",
            "tool_name": "Bash",
            "tool_input": {"command": "ide/ide start"},
        }
        store.request_claim()
        self.assertIsNone(run_hook("PostToolUse", payload))
        self.assertEqual(store.owner_session(), "b")

    def test_only_the_owners_session_end_releases_the_chat(self):
        fake_server(self)
        store.set_owner_session("a")
        store.touch_agent_seen()
        run_hook("SessionEnd", {"session_id": "b"})
        self.assertEqual(store.owner_session(), "a")
        self.assertIsNone(store.agent_ended())
        run_hook("SessionEnd", {"session_id": "a"})
        self.assertIsNone(store.owner_session())
        self.assertIsNotNone(store.agent_ended())

    def test_a_hook_with_no_session_id_still_delivers(self):
        fake_server(self)
        store.set_owner_session("a")
        store.post_message("user", "hello")
        self.assertIsNotNone(run_hook("PostToolUse", {"tool_name": "Read"}))

    def test_an_unused_ide_has_no_owner(self):
        run_hook("PostToolUse", {"session_id": "a", "tool_name": "Read"})
        self.assertIsNone(store.owner_session())

    def test_status_names_the_owner(self):
        store.set_owner_session("a")
        self.assertEqual(hooks.agent_status()["owner"], "a")

    def test_a_waiter_of_another_session_exits_at_once(self):
        store.set_owner_session("a")
        store.post_message("user", "for the owner")
        done = subprocess.run(
            [sys.executable, str(IDE), "hook", "Rewake"],
            input=json.dumps({"session_id": "b"}),
            capture_output=True,
            text=True,
            timeout=20,
            env={**os.environ, "WEBDIP_LAB": str(self.lab)},
        )
        self.assertEqual(done.returncode, 0)
        self.assertTrue(store.has_unread_for_agent())

    def test_a_waiter_lets_go_when_another_session_takes_the_chat(self):
        waiter = subprocess.Popen(
            [sys.executable, str(IDE), "hook", "Rewake"],
            stdin=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**os.environ, "WEBDIP_LAB": str(self.lab)},
        )
        self.addCleanup(waiter.kill)
        waiter.stdin.write(json.dumps({"session_id": "a"}))
        waiter.stdin.close()
        time.sleep(1.5)
        self.assertIsNone(waiter.poll())
        store.set_owner_session("b")
        self.assertEqual(waiter.wait(timeout=10), 0)
        waiter.stderr.close()


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

    def test_keeps_waiting_while_the_ide_is_closed(self):
        # The server may be started or restarted while the session is idle; the waiter
        # must still be there to deliver the first message.
        waiter = self._waiter()
        time.sleep(1.5)
        self.assertIsNone(waiter.poll(), "the waiter must not exit because no server is running")
        store.post_message("user", "sent after a restart")
        _, stderr = waiter.communicate(timeout=10)
        self.assertEqual(waiter.returncode, 2)
        self.assertIn("sent after a restart", stderr)

    def test_exits_2_with_the_message_on_stderr(self):
        fake_server(self)
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

    def test_a_record_left_by_a_killed_server_is_not_running_even_when_its_pid_is_alive(self):
        """The pid can come to belong to another program (here: this test). The lock tells them apart."""
        (paths.state_dir() / "server.json").write_text(json.dumps({"pid": os.getpid(), "port": 1, "url": "x"}))
        self.assertIsNone(hooks.server_info())
        lock = hooks.hold_server_lock()
        self.assertIsNotNone(hooks.server_info())
        self.assertIsNone(hooks.hold_server_lock())  # a second server for the same lab is refused
        lock.close()
        self.assertIsNone(hooks.server_info())

    def test_session_end_marks_the_agent_gone_until_it_acts_again(self):
        self.assertIsNone(run_hook("SessionEnd"))
        self.assertEqual(hooks.agent_status()["state"], "none", "a session the IDE never saw leaves no mark")
        store.touch_agent_seen()
        self.assertEqual(hooks.agent_status()["state"], "working")
        self.assertIsNone(run_hook("SessionEnd", {"reason": "prompt_input_exit"}))
        self.assertEqual(hooks.agent_status()["state"], "ended")
        time.sleep(0.01)
        store.touch_agent_seen()  # the next session's first action
        self.assertEqual(hooks.agent_status()["state"], "working")

    def test_waiting_age_is_the_age_of_the_oldest_undelivered_message(self):
        self.assertIsNone(hooks.agent_status()["waiting_age"])
        store.post_message("user", "one")
        time.sleep(0.05)
        store.post_message("user", "two")
        age = hooks.agent_status()["waiting_age"]
        self.assertGreaterEqual(age, 0.05)
        self.assertLess(age, 5)
        store.take_unread_for_agent()
        self.assertIsNone(hooks.agent_status()["waiting_age"])

    def test_dead_listener_records_are_cleared(self):
        (paths.state_dir() / "listeners").mkdir()
        (paths.state_dir() / "listeners" / str(2**22 + 12345)).write_text("0")
        self.assertFalse(hooks.listener_alive())
        self.assertEqual(list((paths.state_dir() / "listeners").iterdir()), [])


class SettingsTest(unittest.TestCase):
    def test_hook_settings_shape(self):
        settings = hooks.hook_settings()
        self.assertEqual(sorted(settings),
                         ["FileChanged", "PostToolUse", "SessionEnd", "SessionStart", "Stop", "UserPromptSubmit"])
        commands = [hook for entries in settings.values() for entry in entries for hook in entry["hooks"]]
        self.assertTrue(
            all(hook["command"].startswith('python3 "$CLAUDE_PROJECT_DIR/ide/ide" hook ') for hook in commands)
        )
        waiters = [hook for hook in commands if hook.get("asyncRewake")]
        # Every event but SessionEnd starts the waiter, so one is alive again after it fired
        # and the user then interrupted the turn (an interrupt runs no Stop hook). FileChanged
        # has the waiter and nothing else: it runs when the chat file changes, whatever the
        # agent's turn is doing, and its group has no matcher (a matcher would name a file in
        # the working directory; the watched path comes from the SessionStart hook).
        with_waiter = [
            event
            for event, entries in settings.items()
            if any(hook.get("asyncRewake") for entry in entries for hook in entry["hooks"])
        ]
        self.assertEqual(sorted(with_waiter),
                         ["FileChanged", "PostToolUse", "SessionStart", "Stop", "UserPromptSubmit"])
        self.assertEqual(settings["FileChanged"], [{"hooks": waiters[:1]}])
        self.assertTrue(all(hook["command"].endswith("hook Rewake") for hook in waiters))
        self.assertTrue(all(hook["timeout"] <= 20 for hook in commands if not hook.get("asyncRewake")))


if __name__ == "__main__":
    unittest.main()
