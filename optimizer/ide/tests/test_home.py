"""The home page's worklist (`webdip_ide/routes_home.py`) on a small synthetic lab.

`tools/` is the source lab's tools and `.runtime/artifacts/` holds games written by the lab's own
test helper: our policy "mine" in slot 0 (England) of every game, with a seat log.
"""

import json
import os
import re
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from lab_source import lab_source

MIXIN = lab_source()
sys.path.insert(0, str(MIXIN / "tools" / "tests"))
from helpers import write_episode  # noqa: E402

COUNTRIES = [1, 2, 3, 4, 5, 6, 7]
FIELD = ["rival-a:v1", "rival-a:v1", "rival-b:v2", "rival-b:v2", "rival-c:v1", "rival-c:v1"]
SCORES = [0.30, 0.02, 0.45, 0.10, 0.00, 0.20, 0.05, 0.15, 0.25]  # game 1 is the oldest


class HomeTests(unittest.TestCase):
    def setUp(self):
        self.lab = Path(tempfile.mkdtemp(prefix="webdip-ide-test-"))
        self.addCleanup(shutil.rmtree, self.lab, ignore_errors=True)
        (self.lab / "tools").symlink_to(MIXIN / "tools")
        self.artifacts = self.lab / ".runtime" / "artifacts"
        self.artifacts.mkdir(parents=True)
        previous = os.environ.get("WEBDIP_LAB")
        os.environ["WEBDIP_LAB"] = str(self.lab)
        self.addCleanup(lambda: os.environ.pop("WEBDIP_LAB") if previous is None
                        else os.environ.__setitem__("WEBDIP_LAB", previous))  # fmt: skip
        from webdip_ide import episodes, routes_dashboard, routes_home, server, store

        self.episodes, self.dashboard, self.home, self.store = episodes, routes_dashboard, routes_home, store
        episodes._basic.clear()
        self.client = TestClient(server.create_app(), base_url="http://127.0.0.1:8642")

    def game(self, number: int, score: float, policy: str = "mine:v1", status: str = "completed", log=True) -> str:
        rest = (1 - score) / 6
        ep = write_episode(self.artifacts / "xreq_press" / f"ereq_{number:03d}", [score] + [rest] * 6, COUNTRIES,
                           [5] + [4] * 6, seating=[policy, *FIELD], status=status,
                           logs={0: [{"event": "decision"}]} if log else None)
        row = json.loads((ep / "episode.json").read_text())
        row.update({"created_at": f"2026-10-10T00:{number:02d}:00Z", "variant_name": "Classic press"})
        (ep / "episode.json").write_text(json.dumps(row))
        return ep.name

    def lab_with_games(self) -> None:
        for number, score in enumerate(SCORES, start=1):
            self.game(number, score)
        self.game(10, 0.0, status="failed")  # a crash: counted, never ranked
        self.game(20, 0.2, policy="rival-d:v1", log=False)  # someone else as England, so England has a par
        self.dashboard.CACHE.sync(60)  # the dashboard's reader has finished
        self.episodes.deepen(wait=True)  # and the replay browser's

    def rows(self, text: str) -> list[str]:
        """Episode ids of the worklist's rows, in page order."""
        table = text[text.index('<table class="home-games">'):text.index("</table>")]
        return re.findall(r'title="Episode id (ereq_\d+)', table)

    def test_empty_lab(self):
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("No games on disk yet", page.text)
        self.assertNotIn("Still reading games", page.text)
        self.assertIn('id="agent-panel"', page.text)  # every page carries the agent panel
        self.assertIn('id="agent-input"', page.text)

    def test_headline_is_the_dashboards_own(self):
        self.lab_with_games()
        page = self.client.get("/").text
        summary = self.dashboard.summary()
        self.assertEqual((summary["policy"], summary["variant"], summary["pending"]), ("mine", "classic-press", 0))
        # The same sentence and the same n the dashboard page leads with: nothing is computed again here.
        dashboard = self.client.get("/dashboard").text
        for text in (summary["headline"]["lead"], summary["headline"]["reading"]):
            self.assertIn(text, page)
            self.assertIn(text, dashboard)
        stat = summary["stat"]
        self.assertEqual((stat["games"], stat["n"]), (9, 9))
        self.assertIn(f'{stat["games"]} games, {stat["n"]} of our seats', page)
        self.assertIn(stat["verdict"], page)
        self.assertIn("Policy we follow · mine · classic-press", page)

    def test_the_followed_policy_is_the_shared_cookie(self):
        self.lab_with_games()
        self.game(11, 0.6, policy="other:v1")
        self.dashboard.CACHE.sync(60)
        self.client.cookies.set("dashboard_policy", "mine")
        self.assertIn("Policy we follow · mine ·", self.client.get("/").text)
        self.client.cookies.set("dashboard_policy", "other")
        page = self.client.get("/").text
        self.assertIn("Policy we follow · other ·", page)
        self.assertEqual(self.rows(page), ["ereq_011"])

    def test_the_newer_of_the_browsers_pick_and_the_agents_follow_wins(self):
        import os
        import time

        from webdip_ide import paths, store

        self.lab_with_games()
        self.game(11, 0.6, policy="other:v1")
        self.dashboard.CACHE.sync(60)
        # The user picked "other" on the dashboard a while ago...
        picked = self.client.get("/dashboard", params={"policy": "other"})
        self.assertIn("dashboard_policy_at=", picked.headers.get("set-cookie", ""))
        self.assertIn("Policy we follow · other ·", self.client.get("/").text)
        # ...then told the agent "my policy is mine": every page follows it, the old pick included.
        store.set_followed_policy("mine")
        later = time.time() + 60
        os.utime(paths.state_dir() / "followed_policy", (later, later))
        self.assertIn("Policy we follow · mine ·", self.client.get("/").text)
        self.assertIn('<option value="mine" selected>', self.client.get("/replays").text)
        self.assertIn('<option value="mine" selected>', self.client.get("/dashboard").text)
        # A pick made after that wins again.
        os.utime(paths.state_dir() / "followed_policy", (later - 3600, later - 3600))
        self.client.get("/replays", params={"policy": "other"})
        self.assertIn("Policy we follow · other ·", self.client.get("/").text)
        # A pick from before the time was kept (no second cookie) loses to a recorded policy.
        self.client.cookies.delete("dashboard_policy_at")
        self.assertIn("Policy we follow · mine ·", self.client.get("/").text)

    def test_five_lowest_then_two_highest_without_the_crash(self):
        self.lab_with_games()
        page = self.client.get("/").text
        self.assertEqual(self.rows(page), ["ereq_005", "ereq_002", "ereq_007", "ereq_004", "ereq_008",
                                           "ereq_003", "ereq_001"])  # fmt: skip
        self.assertNotIn("Episode id ereq_010", page)
        self.assertIn("1 more crashed or was cut short", page)
        self.assertIn("0.000 <span class=\"bad\">−0.143</span>", page)
        self.assertIn('href="/replays/ereq_005?seat=0"', page)
        work = self.home.worklist("mine", "classic-press")
        self.assertEqual((work["considered"], work["tainted"]), (9, 1))
        self.assertEqual(self.home.worklist("mine", "classic-gunboat")["worst"], [])

    def test_few_games_are_not_listed_twice(self):
        for number, score in enumerate(SCORES[:3], start=1):
            self.game(number, score)
        work = self.home.worklist("mine")
        self.assertEqual([r["episode"]["id"] for r in work["worst"]], ["ereq_002", "ereq_001", "ereq_003"])
        self.assertEqual(work["best"], [])

    def test_who_lied_links_to_the_turn_it_was_said(self):
        self.lab_with_games()
        out = self.lab / ".runtime" / "press" / "ereq_005"
        out.mkdir(parents=True)
        flagged = [
            {"message": "prv-9", "turn": 5, "category": "betrayed", "quote": "later lie"},
            {"message": "prv-4", "turn": 3, "category": "deceived", "quote": "BUR stays empty"},
            {"message": "prv-5", "turn": 1, "category": "doubted_wrongly", "quote": "not a lie"},
        ]
        ours = {"message": "prv-1", "turn": 0, "category": "we_broke_our_word", "quote": "x"}
        powers = {"FRANCE": {"flagged": flagged}, "ITALY": {"flagged": [flagged[2]]}, "ENGLAND": {"flagged": [ours]}}
        (out / "audit.json").write_text(json.dumps({"slot": 0, "summary": {"powers": powers}}))
        self.assertEqual(self.home.liars("ereq_005", 0),
                         [{"power": "France", "count": 2, "turn": 3, "quote": "BUR stays empty"}])
        self.assertIsNone(self.home.liars("ereq_005", 2), "an audit of seat 0 says nothing about seat 2")
        self.assertIsNone(self.home.liars("ereq_002", 0))
        page = self.client.get("/").text
        self.assertIn('href="/replays/ereq_005?seat=0&amp;turn=3"', page)
        self.assertIn("France 2</a>", page)
        self.assertIn("no audit", page)
        # A rewritten audit is read again.
        time.sleep(0.01)
        (out / "audit.json").write_text(json.dumps({"slot": 0, "summary": {"powers": {}}}))
        os.utime(out / "audit.json", (time.time() + 5, time.time() + 5))
        self.assertEqual(self.home.liars("ereq_005", 0), [])

    def test_turning_point(self):
        seat = {"centers_by_year": {1901: 5, 1902: 6, 1903: 3, 1904: 3, 1905: 5}}
        self.assertEqual(self.home.turning_point(seat, worst=True), {"turn": 5, "text": "6 to 3 centres in 1903"})
        self.assertEqual(self.home.turning_point(seat, worst=False), {"turn": 9, "text": "3 to 5 centres in 1905"})
        self.assertIsNone(self.home.turning_point({"centers_by_year": {1901: 4, 1902: 5}}, worst=True))
        self.assertIsNone(self.home.turning_point({}, worst=True))

    def test_notes_not_yet_sent(self):
        self.lab_with_games()
        first = self.store.add_annotation("ereq_005", "user", "lost Munich")
        self.store.add_annotation("ereq_005", "user", "and Berlin")
        self.store.add_annotation("ereq_002", "agent", "the agent's own note is not the user's to send")
        self.assertEqual(self.home.unsent_notes(), {"count": 2, "games": [("ereq_005", 2)]})
        self.assertIn('<strong class="num">2</strong> of your notes have not been sent', self.client.get("/").text)
        self.store.post_message("user", "A note", {"episode": "ereq_005", "annotations": [first["id"]]})
        self.assertEqual(self.home.unsent_notes(), {"count": 1, "games": [("ereq_005", 1)]})

    def test_reports_since_the_last_sitting(self):
        now = 1_000_000.0
        self.assertEqual(self.home._sitting("", now), (None, "1000000:"))  # a first visit: nothing is "new"
        self.assertEqual(self.home._sitting("999900:", now), (None, "1000000:"))  # a reload in the same sitting
        self.assertEqual(self.home._sitting("990000:", now), (990000.0, "1000000:990000"))  # back after a break
        self.assertEqual(self.home._sitting("999900:990000", now), (990000.0, "1000000:990000"))  # and a reload
        self.assertEqual(self.home._sitting("nonsense", now), (None, "1000000:"))

        folder = self.lab / "reports" / "matchups"
        folder.mkdir(parents=True)
        (folder / "mine-vs-field.md").write_text("---\ntitle: Why mine loses\n---\n\n# Why mine loses\n")
        changed = (folder / "mine-vs-field.md").stat().st_mtime
        self.assertEqual(self.home.reports(None), {"total": 1, "new": []})
        self.assertEqual(self.home.reports(changed + 10)["new"], [])
        new = self.home.reports(changed - 10)["new"]
        self.assertEqual([(r["title"], r["link"]) for r in new],
                         [("Why mine loses", "/reports/matchups/mine-vs-field")])  # fmt: skip
        self.client.cookies.set("home_visit", f"{changed - 5000:.0f}:")
        page = self.client.get("/").text
        self.assertIn('<strong class="num">1</strong> report written since you were last here', page)
        self.assertIn('<a href="/reports/matchups/mine-vs-field">Why mine loses</a>', page)

    def test_the_page_does_not_wait_for_the_readers(self):
        for number, score in enumerate(SCORES, start=1):
            self.game(number, score)
        started = time.time()
        summary = self.dashboard.summary()  # nothing read yet: returns at once with what there is
        self.assertLess(time.time() - started, 2.0)
        if summary["pending"]:
            self.assertIsNone(summary["headline"])
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertEqual(len(self.rows(page.text)), 7, "the worklist comes from the index, which is already there")


if __name__ == "__main__":
    unittest.main()
