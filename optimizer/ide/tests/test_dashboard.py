"""The dashboard page and its JSON, on small synthetic labs.

Each test gets its own lab directory: `tools/` is the source lab's tools and
`.runtime/artifacts/` holds games written by the lab's own test helper. The numbers
themselves are tested with the lab (`mixin/tools/tests/test_matchups.py`); here it is the
route: filters, defaults, links, the reading cache and the empty states.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

MIXIN = Path(__file__).resolve().parents[2] / "mixin"
sys.path.insert(0, str(MIXIN / "tools" / "tests"))
from helpers import write_episode  # noqa: E402

COUNTRIES = [1, 2, 3, 4, 5, 6, 7]
FIELD = ["rival-a:v1", "rival-a:v1", "rival-b:v2", "rival-b:v2", "rival-c:v1", "rival-c:v1"]


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.lab = Path(tempfile.mkdtemp(prefix="webdip-ide-test-"))
        self.addCleanup(shutil.rmtree, self.lab, ignore_errors=True)
        (self.lab / "tools").symlink_to(MIXIN / "tools")
        self.artifacts = self.lab / ".runtime" / "artifacts"
        self.artifacts.mkdir(parents=True)
        previous = os.environ.get("WEBDIP_LAB")
        os.environ["WEBDIP_LAB"] = str(self.lab)
        self.addCleanup(lambda: os.environ.pop("WEBDIP_LAB") if previous is None
                        else os.environ.__setitem__("WEBDIP_LAB", previous))
        from webdip_ide.server import create_app

        self.client = TestClient(create_app())
        self.count = 0

    def game(self, batch: str, our_score: float, ours="mine:v1", field=FIELD, variant="Classic press", logs=None):
        """One hosted game: our seat in slot 0 (England), the rest of the score shared by the field."""
        self.count += 1
        rest = (1 - our_score) / 6
        ep = write_episode(self.artifacts / batch / f"ereq_{self.count:03d}", [our_score] + [rest] * 6, COUNTRIES,
                           [5] + [4] * 6, seating=[ours, *field], status="completed", logs=logs)
        row = json.loads((ep / "episode.json").read_text())
        row.update({"created_at": f"2026-10-10T00:{self.count:02d}:00Z", "variant_name": variant})
        (ep / "episode.json").write_text(json.dumps(row))
        return ep

    def lab_with_two_variants(self):
        played = [{"event": "decision"}]
        for score in (0.4, 0.3, 0.5):
            self.game("xreq_press", score, logs={0: played})
        self.game("xreq_press", 0.2, ours="rival-d:v1")  # England's par in press: 0.2
        self.game("league-gunboat", 0.1, ours="mine:v2", variant="Classic gunboat", logs={0: played})
        self.game("league-gunboat", 0.3, ours="rival-d:v1", variant="Classic gunboat")

    def api(self, **params) -> dict:
        response = self.client.get("/api/dashboard", params=params)
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_empty_lab_says_what_to_do(self):
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertIn("No games are on disk yet", response.text)
        self.assertEqual(self.api()["report"], None)

    def test_defaults_pick_our_policy_and_its_larger_variant(self):
        self.lab_with_two_variants()
        data = self.api()
        # "mine" is the newest policy with seat logs; press has 3 of its 4 games.
        self.assertEqual(data["filters"], {"policy": "mine", "version": "", "source": "all",
                                           "variant": "classic-press", "opponent": "", "alone": ""})
        self.assertEqual(data["reading"], 0)
        self.assertEqual(data["report"]["seats"], 3)
        self.assertAlmostEqual(data["report"]["overall"]["vs_par"]["mean"], 0.2)
        self.assertEqual([p["name"] for p in data["policies"]][0], "mine")

    def test_default_policy_is_what_the_lab_shipped(self):
        # Every seat can have a log in a team's lab, so a log does not say which policy is ours.
        self.lab_with_two_variants()
        log = self.lab / "players" / "castlereagh" / "VERSION_LOG.md"
        log.parent.mkdir(parents=True)
        log.write_text("| Version | Id |\n|---|---|\n| rival-b:v2 | `x` |\n| not-on-disk:v1 | `y` |\n")
        self.assertEqual(self.api()["filters"]["policy"], "rival-b")

    def test_filters(self):
        self.lab_with_two_variants()
        pooled = self.api(policy="mine", variant="all")["report"]
        self.assertEqual((pooled["seats"], pooled["mixed_variants"]), (4, True))
        league = self.api(policy="mine", source="league", variant="all")
        self.assertEqual(league["report"]["variants"], {"classic-gunboat": 1})
        self.assertAlmostEqual(league["report"]["overall"]["vs_par"]["mean"], -0.2)
        version = self.api(policy="mine", version="v2")
        self.assertEqual(version["filters"]["version"], "v2")
        self.assertEqual(version["filters"]["variant"], "classic-press")  # the family's default, not v2's
        self.assertEqual(version["report"]["seats"], 0)
        self.assertEqual(self.api(policy="mine:v2", variant="classic-gunboat")["report"]["policy"], "mine:v2")
        self.assertEqual(self.api(policy="mine", opponent="rival-a")["report"]["filters"]["opponent"], "rival-a")
        self.assertEqual(self.api(policy="mine", version="v9")["filters"]["version"], "")  # unknown: all versions
        alone = self.api(policy="mine", alone=1)
        self.assertEqual((alone["filters"]["alone"], alone["report"]["filters"]["alone"]), ("1", True))
        self.assertIn("alone=1", self.client.get("/dashboard", params={"policy": "mine", "alone": 1}).text)

    def test_the_headline_says_what_it_covers_and_puts_the_alone_runs_beside_it(self):
        from webdip_ide import routes_dashboard

        self.lab_with_two_variants()
        self.assertEqual(routes_dashboard.summary()["cover"]["text"], "3 games")
        self.assertIsNone(routes_dashboard.summary()["cover"]["alone"])
        self.assertNotIn("Alone runs only", self.client.get("/").text)
        # A paired run: a second seat of ours in the game.
        self.game("xreq_ab", 0.1, field=["mine:v2", *FIELD[1:]], logs={0: [{"event": "decision"}]})
        cover = routes_dashboard.summary()["cover"]
        self.assertEqual(cover["text"], "4 games, 1 of them a paired run")
        self.assertEqual((cover["alone"]["stat"]["games"], cover["alone"]["mean"]), (3, "+0.200"))
        self.assertIn("alone=1", cover["alone"]["link"])
        home = self.client.get("/").text
        self.assertIn("4 games, 1 of them a paired run, 5 of our seats", home)
        self.assertIn("Alone runs only:", home)
        self.assertIn('<strong class="num">+0.200</strong> per game against par over 3 games', home)
        page = self.client.get("/dashboard", params={"policy": "mine"}).text
        self.assertIn("4 games, 1 of them a paired run", page)
        self.assertIn('<span class="num">+0.200</span> over 3 games</a>, too few games (3 of 16)', page)
        # The alone view is the other number; it says what it left out and offers no third figure.
        alone = self.client.get("/dashboard", params={"policy": "mine", "alone": 1}).text
        self.assertIn("3 games, alone runs only (1 paired run left out)", alone)
        self.assertNotIn("alone runs only: <a", alone)

    def test_a_row_below_the_floor_says_how_far_below_and_which_way_it_leans(self):
        played = [{"event": "decision"}]
        for score in (0.4, 0.3, 0.5, 0.4, 0.4):
            self.game("xreq_press", score, logs={0: played})
        self.game("xreq_press", 0.2, ours="rival-d:v1")  # England's par: 0.2
        stat = self.api(policy="mine")["report"]["by_power"][0]["vs_par"]
        self.assertEqual((stat["verdict"], stat["lean"], stat["games"]), ("too few games", "above par", 5))
        page = self.client.get("/dashboard", params={"policy": "mine"}).text
        self.assertIn('<span class="muted num">5 of 16</span><span class="dash-lean">leaning above par</span>', page)
        self.assertIn("the lab calls nothing a result on fewer than 16", page)
        self.assertIn("a lead to play more games for, not a result", page)

    def test_page_renders_every_section_with_links(self):
        self.lab_with_two_variants()
        response = self.client.get("/dashboard", params={"policy": "mine", "variant": "classic-press"})
        self.assertEqual(response.status_code, 200)
        text = response.text
        for heading in ("By power", "By opponent", "Powers against each opponent", "Version history",
                        "League matches and experience requests", "Supply centres through the game",
                        "What was left out, and what it cost"):
            self.assertIn(heading, text)
        self.assertIn("+0.200 per game against par", text)
        self.assertIn("Too few games to say", text)  # three seats: no verdict
        self.assertIn('href="/replays?policy=mine&amp;opponent=rival-a&amp;variant=classic-press"', text)
        self.assertIn('data-writeup="rival-a"', text)
        self.assertIn("None on disk yet for this policy.", text)  # no league press games: the row stays
        self.assertIn("/static/dashboard.js", text)
        self.assertIn("dashboard_policy=mine", response.headers.get("set-cookie", ""))

    def test_pooled_and_low_data_views_render(self):
        self.lab_with_two_variants()
        pooled = self.client.get("/dashboard", params={"policy": "mine", "variant": "all"})
        self.assertEqual(pooled.status_code, 200)
        self.assertIn("Variants are mixed", pooled.text)
        nothing = self.client.get("/dashboard", params={"policy": "mine", "version": "v2"})
        self.assertEqual(nothing.status_code, 200)
        self.assertIn("No clean games yet for this view.", nothing.text)
        field_policy = self.client.get("/dashboard", params={"policy": "rival-d"})
        self.assertEqual(field_policy.status_code, 200)
        self.assertIn("none of these seats has a log on disk", field_policy.text)

    def test_unknown_policy_falls_back_and_says_so(self):
        self.lab_with_two_variants()
        response = self.client.get("/dashboard", params={"policy": "nobody"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("No policy named <code>nobody</code>", response.text)
        self.assertNotIn("set-cookie", response.headers)

    def test_new_and_changed_games_are_read_and_refresh_redirects(self):
        self.lab_with_two_variants()
        self.assertEqual(self.api(policy="mine")["report"]["seats"], 3)
        ep = self.game("xreq_press", 0.6, logs={0: [{"event": "decision"}]})
        self.assertEqual(self.api(policy="mine")["report"]["seats"], 4)
        results = json.loads((ep / "results.json").read_text())
        results["outcome"] = "cancelled"  # a changed file is read again: the game is now tainted
        (ep / "results.json").write_text(json.dumps(results))
        report = self.api(policy="mine")["report"]
        self.assertEqual((report["seats"], report["taint"]["games_dropped"]), (3, 1))
        shutil.rmtree(ep)
        self.assertEqual(self.api(policy="mine")["report"]["taint"]["games_dropped"], 0)
        self.assertTrue((self.lab / ".runtime" / "ide" / "dashboard_games.pickle").exists())
        response = self.client.get("/dashboard", params={"policy": "mine", "refresh": 1}, follow_redirects=False)
        self.assertEqual((response.status_code, response.headers["location"]), (303, "/dashboard?policy=mine"))
        self.assertEqual(self.api(policy="mine")["report"]["seats"], 3)

    def test_headline_does_not_claim_an_interval_that_reaches_zero(self):
        """z >= 2 is the lab's rule; with 16 games the 95% t interval can still include zero."""
        from webdip_ide import routes_dashboard

        mu = routes_dashboard.matchups()
        # z just over 2 on 15 degrees of freedom, where the t interval needs 2.13.
        values = [0.2 * (-1) ** i + 0.105 for i in range(16)]
        stat = mu.stat([(f"g{i}", v) for i, v in enumerate(values)])
        self.assertEqual(stat["verdict"], "above par")
        self.assertLess(stat["ci"][0], 0)
        reading = routes_dashboard._headline({"overall": {"vs_par": stat}})["reading"]
        self.assertIn("borderline", reading)
        self.assertNotIn("stays above zero", reading)
        clear = mu.stat([(f"g{i}", 0.1 + 0.01 * (i % 3)) for i in range(20)])
        self.assertIn("stays above zero", routes_dashboard._headline({"overall": {"vs_par": clear}})["reading"])

    def test_a_date_that_cannot_be_read_does_not_break_the_page(self):
        self.lab_with_two_variants()
        path = next(self.artifacts.rglob("episode.json"))
        episode = json.loads(path.read_text())
        episode["created_at"] = "not-a-date"
        path.write_text(json.dumps(episode))
        for policy in ("mine", "rival-a"):
            page = self.client.get("/dashboard", params={"policy": policy, "variant": "all"})
            self.assertEqual(page.status_code, 200)


if __name__ == "__main__":
    unittest.main()
