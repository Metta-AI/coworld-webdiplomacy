"""`ide/ide` commands run as the agent runs them (plain python3, a subprocess), and the chat JSON API."""

import io
import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

from test_store import LabCase

from webdip_ide import hooks, store

IDE = Path(__file__).resolve().parent.parent / "ide"


class CliCase(LabCase):
    def ide(self, *args: str, stdin: str | None = None, check: bool = True) -> subprocess.CompletedProcess:
        env = dict(os.environ, WEBDIP_LAB=str(self.lab))
        result = subprocess.run(
            [sys.executable, "-S", str(IDE), *args], env=env, input=stdin, capture_output=True, text=True, timeout=30
        )
        if check and result.returncode != 0:
            self.fail(f"ide {' '.join(args)} exited {result.returncode}: {result.stderr}")
        return result


class TalkTest(CliCase):
    """`-S` (no site-packages) in `ide()` proves these commands need only the standard library."""

    def test_say_posts_an_agent_message_and_marks_the_agent_seen(self):
        self.ide("say", "hello", "there")
        self.ide("say", stdin="from stdin\n")
        self.assertEqual(
            [(m["sender"], m["text"]) for m in store.messages()], [("agent", "hello there"), ("agent", "from stdin")]
        )
        self.assertIsNotNone(store.agent_seen())

    def test_say_nothing_is_an_error(self):
        self.assertNotEqual(self.ide("say", stdin="", check=False).returncode, 0)

    def test_show_posts_a_card(self):
        notes = self.lab / "notes.md"
        notes.write_text("# Finding\n\n- one\n")
        self.ide("show", "--kind", "result", "--title", "v7 vs v6", "--body-file", str(notes), "--link", "/dashboard")
        self.ide("show", "--title", "plain note", "--body", "text")
        first, second = store.cards()
        self.assertEqual((first["kind"], first["title"], first["link"]), ("result", "v7 vs v6", "/dashboard"))
        self.assertIn("- one", first["body"])
        self.assertEqual((second["kind"], second["link"]), ("note", None))

    def test_show_refuses_a_bad_kind_or_link(self):
        self.assertNotEqual(self.ide("show", "--kind", "poster", "--title", "x", check=False).returncode, 0)
        self.assertNotEqual(
            self.ide("show", "--title", "x", "--link", "javascript:alert(1)", check=False).returncode, 0
        )
        self.assertEqual(store.cards(), [])

    def test_inbox_delivers_once_peek_does_not(self):
        store.post_message("user", "first", {"episode": "ereq_1", "phase": 2})
        self.assertIn("first", self.ide("inbox", "--peek").stdout)
        out = self.ide("inbox").stdout
        self.assertIn("first", out)
        self.assertIn("episode ereq_1, phase 2", out)
        self.assertIn("No unread messages.", self.ide("inbox").stdout)
        self.assertIn("first", self.ide("inbox", "--recent", "3").stdout)

    def test_listen_prints_a_waiting_message_and_exits(self):
        store.post_message("user", "already here")
        result = self.ide("listen", "--timeout", "10")
        self.assertIn("already here", result.stdout)
        self.assertFalse(store.has_unread_for_agent())

    def test_listen_wakes_when_a_message_arrives(self):
        env = dict(os.environ, WEBDIP_LAB=str(self.lab))
        listener = subprocess.Popen(
            [sys.executable, str(IDE), "listen", "--interval", "0.05"], env=env, stdout=subprocess.PIPE, text=True
        )
        try:
            deadline = time.time() + 10
            while not hooks.listener_alive() and time.time() < deadline:
                time.sleep(0.05)
            self.assertTrue(hooks.listener_alive())
            self.assertEqual(hooks.agent_status()["state"], "listening")
            store.post_message("user", "wake up")
            out, _ = listener.communicate(timeout=10)
        finally:
            listener.kill()
        self.assertEqual(listener.returncode, 0)
        self.assertIn("wake up", out)
        self.assertFalse(hooks.listener_alive())

    def test_listen_times_out_quietly(self):
        result = self.ide("listen", "--timeout", "0.2", "--interval", "0.05")
        self.assertIn("No message yet", result.stdout)


class AnnotationCommandTest(CliCase):
    def test_annotate_and_list(self):
        store.add_annotation("ereq_1", "user", "should have supported Munich", tag="blunder", phase=5, territory="MUN")
        self.ide(
            "annotate", "ereq_1", "--phase", "6", "--tag", "suggestion", "--power", "GERMANY", "--text", "try a DMZ"
        )
        out = self.ide("annotations").stdout
        self.assertIn("ereq_1  (2 annotations", out)
        self.assertIn("[blunder] by user (phase 5, MUN): should have supported Munich", out)
        self.assertIn("[suggestion] by agent (phase 6, GERMANY): try a DMZ", out)
        self.assertEqual(len(json.loads(self.ide("annotations", "ereq_1", "--json").stdout)["ereq_1"]), 2)
        self.assertIn("No annotations on ereq_2", self.ide("annotations", "ereq_2").stdout)


class ServerCommandTest(CliCase):
    def test_status_and_url_when_closed(self):
        out = self.ide("status").stdout
        self.assertIn("not running", out)
        self.assertEqual(json.loads(self.ide("status", "--json").stdout)["server"], None)
        self.assertEqual(self.ide("url", check=False).returncode, 1)
        self.assertIn("not running", self.ide("stop").stdout)

    def test_follow_records_the_policy_without_its_version(self):
        self.assertIn("No policy recorded", self.ide("follow").stdout)
        self.assertIn("follow my-policy", self.ide("follow", "my-policy:v2").stdout)
        self.assertEqual(self.ide("follow").stdout.strip(), "my-policy")
        self.assertEqual(store.followed_policy(), "my-policy")

    def test_port_choice(self):
        """A named port is used as it is; otherwise the lab's last port, else the default, else the next free one."""
        import socket

        from webdip_ide import cli, paths

        self.assertEqual(cli._choose_port(4321), 4321)
        with socket.socket() as taken:
            taken.bind((cli.HOST, 0))
            taken.listen()
            busy = taken.getsockname()[1]
            with mock.patch.object(cli, "DEFAULT_PORT", busy), mock.patch.object(sys, "stderr", io.StringIO()) as err:
                chosen = cli._choose_port(None)
            self.assertGreater(chosen, busy)
            self.assertLess(chosen, busy + cli.PORTS_TO_TRY)
            self.assertIn(f"port {busy} is in use", err.getvalue())
        (paths.state_dir() / "port").write_text(f"{chosen}\n")  # what `serve` leaves behind
        with mock.patch.object(cli, "_port_free", return_value=True):
            self.assertEqual(cli._choose_port(None), chosen, "a restart comes back to the lab's last port")

    def test_stop_never_signals_a_pid_the_ide_does_not_answer_for(self):
        """A record left by a dead server, whose pid now belongs to another program (here: this test)."""
        record = self.lab / ".runtime" / "ide" / "server.json"
        record.parent.mkdir(parents=True, exist_ok=True)
        record.write_text(json.dumps({"pid": os.getpid(), "port": 9, "url": "http://127.0.0.1:9", "started": 0}))
        self.assertIn("not running", self.ide("stop").stdout)  # ...and we are still here
        self.assertIn("not running", self.ide("status").stdout)

    def test_hook_command_reads_stdin_and_exits_zero(self):
        store.post_message("user", "via the command")
        result = self.ide("hook", "PostToolUse", stdin=json.dumps({"tool_name": "Bash"}))
        self.assertIn("via the command", json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(self.ide("hook", "PostToolUse", stdin="garbage").stdout, "")


class ChatApiTest(LabCase):
    def setUp(self):
        super().setUp()
        from fastapi.testclient import TestClient

        from webdip_ide.server import create_app

        self.client = TestClient(create_app(), base_url="http://127.0.0.1:8642")

    def test_post_then_poll(self):
        posted = self.client.post(
            "/api/chat", json={"text": "  hello agent ", "context": {"episode": "e1", "phase": 2}}
        )
        self.assertEqual(posted.status_code, 200)
        self.assertEqual(posted.json()["text"], "hello agent")
        store.post_message("agent", "hello user")
        body = self.client.get("/api/chat", params={"after": 1}).json()
        self.assertEqual([m["text"] for m in body["messages"]], ["hello user"])
        self.assertEqual(body["delivered"], 0)
        store.take_unread_for_agent()
        self.assertEqual(self.client.get("/api/chat").json()["delivered"], 1)

    def test_empty_and_oversized_messages_are_refused(self):
        self.assertEqual(self.client.post("/api/chat", json={"text": "   "}).status_code, 400)
        self.assertEqual(self.client.post("/api/chat", json={"text": "x" * 20_001}).status_code, 400)
        self.assertEqual(store.messages(), [])

    def test_other_sites_cannot_post(self):
        cross = self.client.post("/api/chat", json={"text": "x"}, headers={"origin": "http://evil.example"})
        self.assertEqual(cross.status_code, 403)
        rebound = self.client.post("/api/chat", json={"text": "x"}, headers={"host": "evil.example:8642"})
        self.assertEqual(rebound.status_code, 403)
        same = self.client.post("/api/chat", json={"text": "x"}, headers={"origin": "http://127.0.0.1:8642"})
        self.assertEqual(same.status_code, 200)

    def test_a_page_under_another_host_name_cannot_read(self):
        """DNS rebinding: another site's name pointed at 127.0.0.1 must not read chat or pages."""
        store.post_message("user", "private")
        for path in ("/api/chat", "/api/cards", "/api/agent/status", "/"):
            self.assertEqual(self.client.get(path, headers={"host": "evil.example:8642"}).status_code, 403, path)
        self.assertEqual(self.client.get("/api/chat", headers={"host": "localhost:8642"}).status_code, 200)

    def test_cards_and_status(self):
        store.post_card("idea", "One")
        store.post_card("replay", "Two", link="/replays/e1?phase=3")
        self.assertEqual(
            [c["title"] for c in self.client.get("/api/cards", params={"after": 1}).json()["cards"]], ["Two"]
        )
        status = self.client.get("/api/agent/status").json()
        self.assertEqual((status["state"], status["waiting"], status["server"]), ("none", 0, None))


if __name__ == "__main__":
    unittest.main()
