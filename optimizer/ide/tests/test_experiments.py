"""The experiments pages (`webdip_ide/routes_experiments.py`) on a small synthetic lab.

`tools/` is the source lab's tools; the games are written by the lab's own test helper into the
record's artifact folder, with our two versions in slots 0 and 1 of every game.
"""

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
FIELD = ["rival:v1"] * 5
RECORD = """---
id: 2026-10-11-hold-guard
policy: mine
baseline: mine:v1
candidate: mine:v2
status: {status}        # proposed | running | confirmed | refuted | inconclusive
hypothesis: >
  Refusing a commit that holds more than half of our units (`commit`)
  leaves the search moving them, so the score rises.
decision_rule: >
  Pre-committed: a win is a paired difference (v2 minus v1) of +0.08 or more
  with z >= 2 over 28 balanced paired games. Anything else is no result.
evals: [xreq_aaa, xreq_bbb]               # batch ids, filled as they run
---

# Hold guard

Artifacts: `.runtime/artifacts/2026-10-11-hold-guard`

## Context

`closed_levers.md` was checked. See /replays/ereq_001?phase=3 and <script>alert(1)</script>.

## Verdict

Not read yet.
"""
VERSION_LOG = """# Version log

| Version | Policy version id | Uploaded (UTC) | The one change (and its mechanism) | Config | Validation | Notes |
|---|---|---|---|---|---|---|
| mine:v1 | `aaa` | 2026-10-11 08:27 | Baseline, unchanged | x | unvalidated | |
| mine:v2 | `bbb` | 2026-10-11 13:14 | HOLD_SHARE=0.5: a commit that holds too much is refused | x | unvalidated | |
| mine:v9 | `ccc` | 2026-10-11 14:00 | Something else entirely | x | unvalidated | |
"""
CLOSED = """# Closed levers

Preface text.

---

## Risk aversion                                      closed 2026-10-07
**Mechanism:** weight bad outcomes more heavily.
**Killed by:** −0.055 in the final four-way paired test (48 games).
**Would reopen if:** losses become more costly.
"""
PRACTICES = """# Best practices

## Measuring

- `[mixin]` **Treat |z| < 2 as no result.**
- `[mixin]` **Seat both policies in the same games.**
"""


class ExperimentsTests(unittest.TestCase):
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
        from webdip_ide import episodes, routes_dashboard, routes_experiments, server

        self.dashboard, self.experiments = routes_dashboard, routes_experiments
        episodes._basic.clear()
        self.client = TestClient(server.create_app(), base_url="http://127.0.0.1:8642")

    def record(self, status: str = "running", name: str = "2026-10-11-hold-guard", text: str = RECORD) -> None:
        folder = self.lab / "experiments"
        folder.mkdir(exist_ok=True)
        (folder / f"{name}.md").write_text(text.format(status=status) if "{status}" in text else text)

    def games(self, scores: list[tuple[float, float]], batch: str = "2026-10-11-hold-guard") -> None:
        """One game per (candidate's score, baseline's score); the seat order alternates."""
        for number, (candidate, baseline) in enumerate(scores):
            rest = [(1 - candidate - baseline) / 5] * 5
            first, second = (("mine:v2", candidate), ("mine:v1", baseline))[:: 1 if number % 2 else -1]
            write_episode(self.artifacts / batch / "xreq_aaa" / f"ereq_{batch[-5:]}{number:03d}",
                          [first[1], second[1], *rest], COUNTRIES, [4] * 7, seating=[first[0], second[0], *FIELD])
        self.dashboard.CACHE.sync(60)  # the dashboard's reader has finished

    def test_front_matter_reads_the_record_template(self):
        template = (MIXIN / "experiments" / "_template.md").read_text()
        meta, body = self.experiments.front_matter(template)
        self.assertEqual(meta["status"], "proposed")
        self.assertEqual(meta["evals"], [])
        self.assertTrue(meta["hypothesis"].startswith("One sentence: X happens"))
        self.assertIn("Written BEFORE the run.", meta["decision_rule"])
        self.assertTrue(body.lstrip().startswith("# <Experiment title>"))
        meta, _ = self.experiments.front_matter("---\nstatus: running\nevals:\n  - xreq_a\n  - xreq_b # second\n---\n")
        self.assertEqual(meta["evals"], ["xreq_a", "xreq_b"])

    def test_rule_brief(self):
        brief = self.experiments.rule_brief
        self.assertEqual(brief("a difference of +0.08 or more with z >= 2 over 28 balanced paired games"),
                         "+0.08 or more, z ≥ 2, 28 games")
        self.assertEqual(brief("Paired screen on 28 balanced paired games: +0.05 or more"), "+0.05 or more, 28 games")
        self.assertEqual(brief("ship iff it looks better"), "")

    def test_empty_lab_explains_and_offers_one_request(self):
        page = self.client.get("/experiments")
        self.assertEqual(page.status_code, 200)
        self.assertIn("No experiment records yet.", page.text)
        self.assertIn("a record the agent writes before it runs anything", page.text)
        self.assertEqual(page.text.count("<button type=\"button\" data-draft="), 1)
        self.assertIn("Ask the agent for ideas", page.text)
        self.assertIn("Nothing is refuted yet", page.text)
        self.assertEqual(self.client.get("/api/experiments").json(), [])

    def test_template_is_not_a_record_and_an_unfilled_record_says_so(self):
        template = (MIXIN / "experiments" / "_template.md").read_text()
        self.record(name="_template", text=template)
        self.record(name="2026-10-12-new-idea", text=template)
        rows = self.client.get("/api/experiments").json()
        self.assertEqual([row["id"] for row in rows], ["2026-10-12-new-idea"])
        self.assertEqual((rows[0]["status"], rows[0]["baseline"], rows[0]["hypothesis"]), ("proposed", "", ""))
        page = self.client.get("/experiments/2026-10-12-new-idea")
        self.assertEqual(page.status_code, 200)
        self.assertIn("not filled it in yet", page.text)
        self.assertNotIn("&lt;policy", page.text.split("The record</h2>")[0])  # no template text as if it were a value
        self.assertEqual(self.client.get("/experiments/_template").status_code, 404)

    def test_list_shows_the_record_and_the_lab_tools_number(self):
        self.record()
        scores = [(0.30, 0.10), (0.25, 0.20), (0.20, 0.20), (0.35, 0.05)]
        self.games(scores)
        import paired
        from webdip_episodes import load_dirs

        seats, _ = load_dirs([self.artifacts / "2026-10-11-hold-guard"])
        expected = paired.paired_report(seats, "mine:v2", "mine:v1")
        self.assertEqual(expected["n"], 4)

        row = self.client.get("/api/experiments").json()[0]
        self.assertEqual(row["result"]["paired"], expected)  # the tool's report, not a second calculation
        self.assertEqual((row["result"]["games_in"], row["result"]["planned"]), (4, 28))
        self.assertEqual(row["evals"], ["xreq_aaa", "xreq_bbb"])
        self.assertEqual(row["batch"], "2026-10-11-hold-guard")

        page = self.client.get("/experiments").text
        self.assertIn("Hold guard", page)
        self.assertIn("a win needs +0.08 or more, z ≥ 2, 28 games", page)
        self.assertIn("4 of 28 games in", page)
        self.assertIn("2 batches", page)
        self.assertIn(f"SE {expected['se']:.3f}", page)
        self.assertIn(f"z {expected['z']:+.2f}".replace("-", "−"), page)
        self.assertIn("over 4 paired games", page)
        self.assertIn(expected["verdict"].replace("<", "&lt;"), page)
        self.assertIn("<code>commit</code>", page)  # the hypothesis is rendered, and escaped

    def test_running_record_with_no_games_says_so(self):
        self.record()
        page = self.client.get("/experiments").text
        self.assertIn("0 of 28 games in", page)
        self.assertIn("nothing in <code>.runtime/artifacts/2026-10-11-hold-guard</code>", page)
        view = self.client.get("/experiments/2026-10-11-hold-guard").text
        self.assertIn("0 of 28 games in", view)
        self.assertIn("Ask the agent for the result", view)
        self.assertNotIn("Ask for the candidate-alone check", view)

    def test_record_page_renders_the_record_safely_with_links_and_versions(self):
        self.record(status="inconclusive")
        self.games([(0.30, 0.10), (0.25, 0.20), (0.20, 0.20)])
        (self.lab / "players" / "mine").mkdir(parents=True)
        (self.lab / "players" / "mine" / "VERSION_LOG.md").write_text(VERSION_LOG)
        page = self.client.get("/experiments/2026-10-11-hold-guard")
        self.assertEqual(page.status_code, 200)
        text = page.text
        self.assertIn("<h1>Hold guard</h1>", text)
        self.assertIn("inconclusive", text)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", text)
        self.assertNotIn("<script>alert(1)", text)
        self.assertIn('href="/replays/ereq_001?phase=3"', text)
        self.assertIn('href="/dashboard?policy=mine&amp;version=v2"', text)
        self.assertIn('href="/replays?batch=2026-10-11-hold-guard&amp;policy=mine"', text)
        self.assertIn("3 of 28 games in", text)
        # The version log: the two versions of this record, baseline first, uploaded time in Pacific.
        table = text[text.index("The two versions"):text.index("The record</h2>")]
        self.assertLess(table.index("mine:v1"), table.index("mine:v2"))
        self.assertIn("Oct 11, 6:14 AM", table)
        self.assertIn("HOLD_SHARE=0.5", table)
        self.assertNotIn("mine:v9", table)
        # A closed record offers no request to read or close it.
        self.assertNotIn("Ask the agent for the result", text)
        self.assertNotIn("Ask the agent to close this record", text)

    def test_requests_depend_on_the_state(self):
        self.record()
        # The candidate ahead in every game by a varying margin: a paired win (z >= 2).
        self.games([(0.40, 0.05), (0.38, 0.06), (0.42, 0.04), (0.39, 0.07), (0.41, 0.05), (0.37, 0.06)])
        row = self.client.get("/api/experiments").json()[0]
        self.assertEqual(row["result"]["paired"]["verdict"], "mine:v2 ahead")
        text = self.client.get("/experiments/2026-10-11-hold-guard").text
        for label in ("Ask the agent for the result", "Ask the agent to close this record",
                      "Ask for the candidate-alone check"):
            self.assertIn(label, text)
        self.assertIn("run_ab.py --record 2026-10-11-hold-guard --alone", text)
        self.assertIn("links to /experiments/2026-10-11-hold-guard", text)

    def test_unknown_record_is_a_404_page(self):
        for name in ("nope", "..%2Fsecrets"):
            page = self.client.get(f"/experiments/{name}")
            self.assertEqual(page.status_code, 404)
        self.assertIn("No such experiment", self.client.get("/experiments/nope").text)

    def test_what_is_closed_lists_both_registers(self):
        (self.lab / "closed_levers.md").write_text(CLOSED)
        (self.lab / "best_practices.md").write_text(PRACTICES)
        text = self.client.get("/experiments").text
        self.assertIn("Risk aversion", text)
        self.assertIn("closed 2026-10-07", text)
        self.assertIn("−0.055 in the final four-way paired test (48 games).", text)
        self.assertIn("Measuring", text)
        self.assertIn("2 practices", text)
        self.assertNotIn("Preface text.", text)

    def test_home_names_a_running_experiment(self):
        self.record()
        self.games([(0.30, 0.10), (0.25, 0.20)])
        text = self.client.get("/").text
        self.assertIn("experiment running:", text)
        self.assertIn('<a href="/experiments/2026-10-11-hold-guard">Hold guard</a>', text)
        self.assertIn("2 of 28 games in", text)
        self.record(status="inconclusive")
        self.assertNotIn("experiment running:", self.client.get("/").text)

    def test_navigation_puts_experiments_between_dashboard_and_reports(self):
        text = self.client.get("/experiments").text
        nav = text[text.index("<nav>"):text.index("</nav>")]
        self.assertLess(nav.index("Dashboard"), nav.index("Experiments"))
        self.assertLess(nav.index("Experiments"), nav.index("Reports"))


if __name__ == "__main__":
    unittest.main()
