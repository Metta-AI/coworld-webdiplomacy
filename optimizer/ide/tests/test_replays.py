"""The episode index, the viewer's data and the annotation API, on the lab's trimmed fixtures.

Each test gets its own lab directory: `tools/` is the source lab's tools, and
`.runtime/artifacts/` holds copies of `optimizer/mixin/tools/tests/fixtures`. Those replays
are trimmed (no map coordinates, no `messages`, no unit types on orders), which is also the
"old or partial replay" case the viewer must survive.
"""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

MIXIN = Path(__file__).resolve().parents[2] / "mixin"
FIXTURES = MIXIN / "tools" / "tests" / "fixtures"

PRIVATE_PRESS = {
    "event": "private_press",
    "archive": {
        "messages": [
            {"id": 1, "turn": 0, "phase": "Diplomacy", "timeSent": 10, "fromCountryID": 4, "toCountryID": 5,
             "message": "I keep out of Tyrolia &mdash; Germany"},
            {"id": 2, "turn": 1, "phase": "Builds", "timeSent": 20, "fromCountryID": 5, "toCountryID": 4,
             "message": "Agreed."},
        ]
    },
}  # fmt: skip


def audit_for(slot: int, our_power: str) -> dict:
    """A hand-written audit.json in the shape `press_audit.py verify` writes."""
    claim = {
        "kind": "promise", "quote": "I keep out of Tyrolia", "outcome": "broken", "category": "betrayed",
        "relied": True, "window": [0, 1], "condition": "none",
        "evidence": ["GERMANY A MUN - TYR (Autumn 1901, succeeded)"],
    }  # fmt: skip
    return {
        "episode": "ereq_press", "slot": slot, "policy": "ours:v1", "our_power": our_power, "belief_logged": True,
        "summary": {
            "our_power": our_power, "messages": 2, "messages_with_claims": 1,
            "powers": {"GERMANY": {
                "messages": 1, "claims": 1, "held": 0, "did_not_hold": 1, "unverifiable": 0, "held_share": 0.0,
                "asked": 0, "complied": 0, "categories": {"betrayed": 1}, "betrayal_events": 1,
                "flagged": [{"message": "prv-1", "turn": 0, "category": "betrayed", "quote": "I keep out of Tyrolia"}],
            }},
        },
        "messages": [{"id": "prv-1", "from": "GERMANY", "to": "AUSTRIA", "turn": 0, "claims": [claim]},
                     {"id": "prv-2", "from": "AUSTRIA", "to": "GERMANY", "turn": 2, "claims": []}],
        "phases": [],
    }  # fmt: skip


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.lab = Path(tempfile.mkdtemp(prefix="webdip-ide-test-"))
        self.addCleanup(shutil.rmtree, self.lab, ignore_errors=True)
        (self.lab / "tools").symlink_to(MIXIN / "tools")
        artifacts = self.lab / ".runtime" / "artifacts"
        shutil.copytree(FIXTURES / "hosted", artifacts / "batch-a")
        shutil.copytree(FIXTURES / "local", artifacts / "local-runs")
        previous = os.environ.get("WEBDIP_LAB")
        os.environ["WEBDIP_LAB"] = str(self.lab)
        self.addCleanup(lambda: os.environ.pop("WEBDIP_LAB") if previous is None else os.environ.update(
            WEBDIP_LAB=previous))  # fmt: skip

        from webdip_ide import episodes, server

        self.episodes = episodes
        episodes._basic.clear()
        episodes._views.clear()
        # The write routes only answer on a loopback host name (see routes_chat.require_same_origin).
        self.client = TestClient(server.create_app(), base_url="http://127.0.0.1:8642")
        self.press_dir = artifacts / "batch-a" / "xreq_fixture" / "ereq_press"

    def row(self, episode: str) -> dict:
        return next(r for r in self.episodes.index() if r["id"] == episode)

    # ----- index -----

    def test_index_lists_every_episode_without_reading_replays(self):
        calls = []
        we = self.episodes.tool("webdip_episodes")
        original = we.load_episode
        we.load_episode = lambda ep: calls.append(ep) or original(ep)
        self.addCleanup(setattr, we, "load_episode", original)

        rows = self.episodes.index()

        self.assertEqual(calls, [], "the basic index must not load replays or logs")
        ids = {r["id"] for r in rows}
        self.assertLessEqual({"ereq_press", "ereq_gunboat", "g-011287fb8a"}, ids)
        self.assertEqual(rows, sorted(rows, key=lambda r: r["time"], reverse=True))

    def test_row_fields(self):
        press, gunboat, local = self.row("ereq_press"), self.row("ereq_gunboat"), self.row("g-011287fb8a")
        self.assertEqual((press["batch"], press["source"], press["variant"]), ("batch-a", "xp", "Classic press"))
        self.assertTrue(press["press"])
        self.assertFalse(gunboat["press"])
        self.assertEqual(local["source"], "local")
        self.assertEqual(len(press["seats"]), 7)
        self.assertEqual({s["slot"] for s in press["seats"] if s["has_log"]}, {2, 3})
        seat = press["seats"][0]
        self.assertEqual(seat["policy"], "field-press-a:v1")
        self.assertIn(seat["power"], self.episodes.tool("webdip_episodes").POWERS.values())
        self.assertIsInstance(seat["final_centers"], int)
        self.assertFalse(press["audit"])
        self.assertEqual(press["annotations"], 0)

    def test_followed_seats(self):
        press = self.row("ereq_press")
        logged, guessed = self.episodes.followed_seats(press)
        self.assertEqual(([s["slot"] for s in logged], guessed), ([2, 3], False))
        by_name, _ = self.episodes.followed_seats(press, "field-press-a")
        self.assertEqual([s["slot"] for s in by_name], [0])
        self.assertEqual(self.episodes.followed_seats(press, "nobody:v1")[0], [])
        # Every seat logged (or none): a log says nothing, so the first seat's policy is a guess.
        every = {**press, "seats": [{**s, "has_log": True} for s in press["seats"]]}
        seats, guessed = self.episodes.followed_seats(every)
        self.assertTrue(guessed)
        self.assertEqual(seats[0]["slot"], 0)

    def test_deep_pass_adds_log_taint_and_centre_history_and_is_saved(self):
        self.assertFalse(self.row("ereq_press")["indexed"])
        done, total = self.episodes.deepen(wait=True)
        self.assertEqual(done, total)
        press = self.row("ereq_press")
        self.assertTrue(press["indexed"])
        self.assertTrue(any(s["centers_by_year"] for s in press["seats"]))
        self.assertTrue(all(isinstance(y, int) for s in press["seats"] for y in s["centers_by_year"]))
        self.assertTrue((self.lab / ".runtime" / "ide" / "episode_index.json").exists())
        for seat in press["seats"]:
            self.assertIsInstance(self.episodes.flags(press, seat), list)

    def test_index_sees_a_changed_results_file(self):
        self.assertEqual(self.row("ereq_press")["outcome"], "drawn")
        path = self.press_dir / "results.json"
        results = json.loads(path.read_text())
        results["outcome"] = "cancelled"
        path.write_text(json.dumps(results))
        os.utime(path, (path.stat().st_atime, path.stat().st_mtime + 5))
        row = self.row("ereq_press")
        self.assertEqual(row["outcome"], "cancelled")
        self.assertIn("cancelled", row["taint"])

    # ----- pages -----

    def test_browser_page_and_filters(self):
        page = self.client.get("/replays")
        self.assertEqual(page.status_code, 200)
        self.assertIn("/replays/ereq_press?seat=", page.text)
        self.assertIn("/replays/ereq_gunboat", page.text)
        only_press = self.client.get("/replays", params={"variant": "Classic press"}).text
        self.assertIn("/replays/ereq_press", only_press)
        self.assertNotIn("/replays/ereq_gunboat", only_press)
        followed = self.client.get("/replays", params={"policy": "field-press-a", "source": "xp"}).text
        self.assertIn("/replays/ereq_press", followed)
        self.assertNotIn("/replays/g-011287fb8a", followed)
        none = self.client.get("/replays", params={"annotated": "yes"}).text
        self.assertIn("No episode matches these filters.", none)

    def test_viewer_page_and_unknown_episode(self):
        page = self.client.get("/replays/ereq_press?phase=3")
        self.assertEqual(page.status_code, 200)
        self.assertIn('data-episode="ereq_press"', page.text)
        self.assertIn('data-phase="3"', page.text)
        missing = self.client.get("/replays/ereq_nope")
        self.assertEqual(missing.status_code, 200)
        self.assertIn("No such episode", missing.text)
        self.assertEqual(self.client.get("/api/replays/ereq_nope").status_code, 404)

    # ----- viewer data -----

    def test_view_is_compact_and_survives_a_replay_without_coordinates(self):
        response = self.client.get("/api/replays/ereq_press", params={"seat": 3})
        self.assertEqual(response.status_code, 200)
        view = response.json()
        replay = json.loads((self.press_dir / "replay.json").read_text())
        history = replay[-1]["history"]["phases"]
        self.assertEqual(len(view["phases"]), len(history))
        self.assertEqual(view["phases"][0]["label"], "Spring 1901 · Movement")
        self.assertEqual(view["phases"][-1]["phase"], "Finished")
        self.assertEqual(view["seat"], 3)
        self.assertNotIn("map", json.dumps(view["phases"][0]))
        self.assertTrue(any("no map coordinates" in p for p in view["problems"]))
        self.assertTrue(view["decisions"], "the seat's decision lines are attached to their phases")
        # The Finished entry is stale; the chart's last point is results.json's final count.
        finals = {str(s["country"]): s["final_centers"] for s in view["seats"]}
        self.assertEqual(view["phases"][-1]["sc"], finals)
        self.assertTrue(view["phases"][-1]["stale_board"])
        self.assertLess(len(response.content), 400_000)

    def test_gunboat_and_local_views(self):
        gunboat = self.client.get("/api/replays/ereq_gunboat").json()
        self.assertEqual(gunboat["messages"], [])
        self.assertIsNone(gunboat["audit"])
        self.assertFalse(gunboat["episode"]["press"])
        local = self.client.get("/api/replays/g-011287fb8a").json()
        self.assertTrue(local["phases"])
        unlogged = self.client.get("/api/replays/ereq_press", params={"seat": 99}).json()
        self.assertIn(unlogged["seat"], (2, 3), "an unknown seat falls back to a followed one")

    def test_episode_without_a_replay(self):
        (self.press_dir / "replay.json").unlink()
        view = self.client.get("/api/replays/ereq_press").json()
        self.assertEqual(view["phases"], [])
        self.assertTrue(any("no replay" in p for p in view["problems"]))
        self.assertEqual(self.client.get("/replays/ereq_press").status_code, 200)

    def test_private_press_and_audit_overlay(self):
        log = next((self.press_dir / "policy-logs").glob("*.3.log"))
        with open(log, "a") as out:
            out.write(json.dumps(PRIVATE_PRESS) + "\n")
        before = self.client.get("/api/replays/ereq_press", params={"seat": 3}).json()
        self.assertEqual([m["id"] for m in before["messages"]], ["prv-1", "prv-2"])
        self.assertEqual(before["messages"][0]["text"], "I keep out of Tyrolia — Germany")
        self.assertIsNone(before["audit"])
        first, second = before["messages"]
        self.assertEqual(before["phases"][first["pi"]]["label"], "Spring 1901 · Movement")
        # Press sent during builds is about the next movement turn.
        self.assertEqual(before["phases"][second["pi"]]["label"], "Spring 1902 · Movement")
        self.assertEqual(self.client.get("/api/replays/ereq_press/audit-status").json(), {"stamp": 0.0})

        our_power = next(s["power"] for s in before["seats"] if s["slot"] == 3).upper()
        out = self.lab / ".runtime" / "press" / "ereq_press"
        out.mkdir(parents=True)
        (out / "audit.json").write_text(json.dumps(audit_for(3, our_power)))

        self.assertGreater(self.client.get("/api/replays/ereq_press/audit-status").json()["stamp"], 0)
        after = self.client.get("/api/replays/ereq_press").json()  # no seat named: the audit's seat
        self.assertEqual(after["seat"], 3)
        self.assertTrue(after["audit"]["joined"])
        claim = after["messages"][0]["claims"][0]
        self.assertEqual((claim["outcome"], claim["category"]), ("broken", "betrayed"))
        # Settled where the evidence says: Autumn 1901, not the turn it was said in.
        self.assertEqual(after["phases"][claim["settled"]]["label"], "Autumn 1901 · Movement")
        markers = [e for e in after["events"] if e["kind"] == "betrayed"]
        self.assertEqual([(m["pi"], m["power"]) for m in markers], [(claim["settled"], "Germany")])
        self.assertEqual(after["audit"]["powers"]["GERMANY"]["flagged"][0]["pi"], claim["settled"])
        self.assertEqual(after["verdicts"]["words"]["betrayed"], "we relied on it: betrayed")
        self.assertTrue(self.row("ereq_press")["audit"])

        other = self.client.get("/api/replays/ereq_press", params={"seat": 2}).json()
        self.assertFalse(other["audit"]["joined"], "an audit for seat 3 must not be laid over seat 2's press")
        self.assertEqual([c for m in other["messages"] for c in m["claims"]], [])

    # ----- annotations -----

    def test_annotations_api(self):
        url = "/api/replays/ereq_press/annotations"
        self.assertEqual(self.client.get(url).json(), [])
        made = self.client.post(url, json={"text": " Lost Munich here ", "tag": "blunder", "phase": 4,
                                           "power": "Germany", "territory": "MUN"})  # fmt: skip
        self.assertEqual(made.status_code, 200)
        note = made.json()
        self.assertEqual((note["author"], note["text"], note["phase"], note["territory"]),
                         ("user", "Lost Munich here", 4, "MUN"))  # fmt: skip
        self.assertEqual(self.client.get(url).json(), [note])
        self.assertEqual(self.client.get("/api/replays/ereq_press").json()["annotations"], [note])
        self.assertEqual(self.row("ereq_press")["annotations"], 1)
        self.assertIn("/replays/ereq_press", self.client.get("/replays", params={"annotated": "yes"}).text)

        self.assertEqual(self.client.post(url, json={"text": "  "}).status_code, 422)
        self.assertEqual(self.client.post(url, json={"text": "x", "tag": "not-a-tag"}).status_code, 422)
        self.assertEqual(self.client.post("/api/replays/ereq_nope/annotations", json={"text": "x"}).status_code, 404)
        cross_site = self.client.post(url, json={"text": "x"}, headers={"origin": "http://evil.example"})
        self.assertEqual(cross_site.status_code, 403)

        self.assertEqual(self.client.delete(f"{url}/{note['id']}").status_code, 200)
        self.assertEqual(self.client.delete(f"{url}/{note['id']}").status_code, 404)
        self.assertEqual(self.client.get(url).json(), [])


if __name__ == "__main__":
    unittest.main()
