"""The experiments pages (`webdip_ide/routes_experiments.py`) on a small synthetic lab.

`tools/` is the source lab's tools; the games are written by the lab's own test helper into the
record's artifact folder, with our two versions in slots 0 and 1 of every game.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from lab_source import lab_source

MIXIN = lab_source()
sys.path.insert(0, str(MIXIN / "tools" / "tests"))
from helpers import write_episode  # noqa: E402

COUNTRIES = [1, 2, 3, 4, 5, 6, 7]
FIELD = ["rival:v1"] * 5
RECORD = """---
id: 2030-01-02-example-lever
policy: mine
baseline: mine:v1
candidate: mine:v2
status: {status}        # proposed | running | confirmed | refuted | inconclusive
hypothesis: >
  Setting EXAMPLE_SETTING (`commit`) changes the orders,
  so the score rises.
decision_rule: >
  Pre-committed: a win is a paired difference (v2 minus v1) of +0.08 or more
  with z >= 2 over 28 balanced paired games. Anything else is no result.
evals: [xreq_aaa, xreq_bbb]               # batch ids, filled as they run
---

# Example lever

Artifacts: `.runtime/artifacts/somewhere-else`

## Context

`closed_levers.md` was checked. See /replays/ereq_001?phase=3 and <script>alert(1)</script>.

## Verdict

Not read yet.
"""
VERSION_LOG = """# Version log

| Version | Policy version id | Uploaded (UTC) | The one change (and its mechanism) | Config | Validation | Notes |
|---|---|---|---|---|---|---|
| mine:v1 | `aaa` | 2030-01-02 08:27 | Baseline, unchanged | x | unvalidated | |
| mine:v2 | `bbb` | 2030-01-02 13:14 | EXAMPLE_SETTING=1: the one change | x | unvalidated | |
| mine:v9 | `ccc` | 2030-01-02 14:00 | Something else entirely | x | unvalidated | |
"""
CLOSED = """# Closed levers

Preface text.

---

## Example refuted lever                              closed 2030-01-05
**Mechanism:** the synthetic change.
**Killed by:** −0.111 over 99 synthetic paired games.
**Would reopen if:** the test fixture changes.
"""
PRACTICES = """# Best practices

## Measuring

- **First practice.** How to do it. *(Evidence: 2030-01-02-example-lever)*
- **Second practice.** How to do it.
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

    def record(self, status: str = "running", name: str = "2030-01-02-example-lever", text: str = RECORD) -> None:
        folder = self.lab / "experiments"
        folder.mkdir(exist_ok=True)
        (folder / f"{name}.md").write_text(text.format(status=status) if "{status}" in text else text)

    def games(self, scores: list[tuple[float, float]], batch: str = "2030-01-02-example-lever") -> None:
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
        self.assertEqual(meta["artifacts"], [])  # empty: the record's own folder
        self.assertTrue(meta["cost"].startswith("<"))  # a placeholder, shown as not written
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
        self.record(name="2030-01-04-new-idea", text=template)
        rows = self.client.get("/api/experiments").json()
        self.assertEqual([row["id"] for row in rows], ["2030-01-04-new-idea"])
        self.assertEqual((rows[0]["status"], rows[0]["baseline"], rows[0]["hypothesis"]), ("proposed", "", ""))
        page = self.client.get("/experiments/2030-01-04-new-idea")
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

        seats, _ = load_dirs([self.artifacts / "2030-01-02-example-lever"])
        expected = paired.paired_report(seats, "mine:v2", "mine:v1")
        self.assertEqual(expected["n"], 4)

        row = self.client.get("/api/experiments").json()[0]
        self.assertEqual(row["result"]["paired"], expected)  # the tool's report, not a second calculation
        self.assertEqual((row["result"]["games_in"], row["result"]["planned"]), (4, 28))
        self.assertEqual(row["evals"], ["xreq_aaa", "xreq_bbb"])
        self.assertEqual(row["batch"], "2030-01-02-example-lever")
        self.assertEqual(row["artifacts"], ["2030-01-02-example-lever"])  # the body's `Artifacts:` line is not read

        page = self.client.get("/experiments").text
        self.assertIn("Example lever", page)
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
        self.assertIn("nothing in <code>.runtime/artifacts/2030-01-02-example-lever</code>", page)
        view = self.client.get("/experiments/2030-01-02-example-lever").text
        self.assertIn("0 of 28 games in", view)
        self.assertIn("Ask the agent for the result", view)
        self.assertNotIn("Ask for the candidate-alone check", view)

    def test_record_page_renders_the_record_safely_with_links_and_versions(self):
        self.record(status="inconclusive")
        self.games([(0.30, 0.10), (0.25, 0.20), (0.20, 0.20)])
        (self.lab / "players" / "mine").mkdir(parents=True)
        (self.lab / "players" / "mine" / "VERSION_LOG.md").write_text(VERSION_LOG)
        page = self.client.get("/experiments/2030-01-02-example-lever")
        self.assertEqual(page.status_code, 200)
        text = page.text
        self.assertIn("<h1>Example lever</h1>", text)
        self.assertIn("inconclusive", text)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", text)
        self.assertNotIn("<script>alert(1)", text)
        self.assertIn('href="/replays/ereq_001?phase=3"', text)
        self.assertIn('href="/dashboard?policy=mine&amp;version=v2"', text)
        self.assertIn('href="/replays?batch=2030-01-02-example-lever&amp;policy=mine"', text)
        self.assertIn("3 of 28 games in", text)
        # The version log: the two versions of this record, baseline first, uploaded time in Pacific.
        table = text[text.index("The two versions"):text.index("The record</h2>")]
        self.assertLess(table.index("mine:v1"), table.index("mine:v2"))
        self.assertIn("Jan 2, 2030, 5:14 AM", table)
        self.assertIn("EXAMPLE_SETTING=1", table)
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
        text = self.client.get("/experiments/2030-01-02-example-lever").text
        for label in ("Ask the agent for the result", "Ask the agent to close this record",
                      "Ask for the candidate-alone check"):
            self.assertIn(label, text)
        self.assertIn("run_ab.py --record 2030-01-02-example-lever --alone", text)
        self.assertIn("links to /experiments/2030-01-02-example-lever", text)
        # These buttons only fill the message box, and the page says so.
        self.assertIn("A click puts the request in the message box; nothing is sent until you press Enter.", text)

    def alone_games(self, arm: str, count: int, version: str) -> None:
        folder = self.artifacts / f"2030-01-02-example-lever-alone-{arm}" / f"xreq_{arm}"
        for number in range(count):
            write_episode(folder / f"ereq_alone{arm}{number:03d}", [0.4] + [0.1] * 6, COUNTRIES, [4] * 7,
                          seating=[version, "rival:v1", *FIELD])
        self.dashboard.CACHE.sync(60)

    def test_a_launched_alone_check_shows_its_progress_and_is_not_offered_again(self):
        win = [(0.40, 0.05), (0.38, 0.06), (0.42, 0.04), (0.39, 0.07), (0.41, 0.05), (0.37, 0.06)]
        button, url = "Ask for the candidate-alone check", "/experiments/2030-01-02-example-lever"
        self.record()
        self.games(win)
        self.assertIn(button, self.client.get(url).text)
        # `run_ab.py --alone` has created the two arms: their ids are in the record, no game is in yet.
        launched = RECORD.replace("evals: [xreq_aaa, xreq_bbb]",
                                  "evals: [xreq_aaa, xreq_bbb, xreq_a, xreq_b]\nalone_a: [xreq_a]\nalone_b: [xreq_b]")
        self.record(text=launched)
        text = " ".join(self.client.get(url).text.split())
        self.assertNotIn(button, text)
        self.assertIn("Candidate-alone check, already launched: the candidate playing alone, no games in yet; "
                      "the baseline playing alone, no games in yet.", text)
        self.assertIn("Ask the agent for the result", text)  # the other requests stay
        # Games come in. The tool saved what it asked for in arm A; arm B was launched some other way.
        responses = self.lab / ".runtime" / "requests" / "responses"
        responses.mkdir(parents=True)
        for rotation, asked in enumerate((5, 5)):
            (responses / f"2030-01-02-example-lever-alone-a-r{rotation}.json").write_text(
                json.dumps({"id": f"xreq_a{rotation}", "episode_count": asked}))
        self.alone_games("a", 3, "mine:v2")
        self.alone_games("b", 1, "mine:v1")
        text = " ".join(self.client.get(url).text.split())
        self.assertIn("the candidate playing alone, 3 of 10 games in; the baseline playing alone, 1 game in so far.",
                      text)
        self.assertNotIn(button, text)
        # Games on disk are enough, whatever the record lists.
        self.record()
        text = " ".join(self.client.get(url).text.split())
        self.assertIn("Candidate-alone check, already launched:", text)
        self.assertNotIn(button, text)
        self.assertEqual(self.client.get("/api/experiments").json()[0]["result"]["games_in"], len(win))

    def test_the_cards_api_carries_each_records_status_for_the_idea_cards(self):
        """An idea card links to its record; `chat.js: ideaActions` offers "Test this idea" only while
        that record is proposed, and a link to the result afterwards."""
        from webdip_ide import store

        store.post_card("idea", "Example lever", link="/experiments/2030-01-02-example-lever")
        self.assertEqual(self.client.get("/api/cards").json()["records"], {})  # no record yet: the card asks for one
        self.record(status="proposed")
        self.assertEqual(self.client.get("/api/cards").json()["records"], {"2030-01-02-example-lever": "proposed"})
        self.record(status="inconclusive")
        answer = self.client.get("/api/cards", params={"after": 1}).json()
        self.assertEqual((answer["cards"], answer["records"]), ([], {"2030-01-02-example-lever": "inconclusive"}))
        script = self.client.get("/static/chat.js").text
        self.assertIn('status !== "proposed"', script)
        self.assertIn("see the result", script)

    def test_a_record_that_names_two_folders_reads_both(self):
        """A follow-on record whose rule pools its games with an earlier record's (`artifacts: [a, b]`)."""
        first = [(0.30, 0.10), (0.25, 0.20), (0.20, 0.20)]
        more = [(0.35, 0.05), (0.10, 0.30)]
        self.record(status="inconclusive")
        self.games(first)
        pooled = RECORD.replace("id: 2030-01-02-example-lever", "id: 2030-01-03-example-more").replace(
            "evals: [xreq_aaa, xreq_bbb]",
            "evals: [xreq_ccc]\nartifacts: [`.runtime/artifacts/2030-01-02-example-lever/`]",  # its own folder is added
        )
        self.record(status="inconclusive", name="2030-01-03-example-more", text=pooled)
        self.games(more, batch="2030-01-03-example-more")
        import paired
        from webdip_episodes import load_dirs

        seats, _ = load_dirs([self.artifacts / "2030-01-02-example-lever", self.artifacts / "2030-01-03-example-more"])
        expected = paired.paired_report(seats, "mine:v2", "mine:v1")
        self.assertEqual(expected["n"], 5)

        rows = {row["id"]: row for row in self.client.get("/api/experiments").json()}
        both = rows["2030-01-03-example-more"]
        self.assertEqual(both["artifacts"], ["2030-01-02-example-lever", "2030-01-03-example-more"])
        self.assertEqual(both["result"]["folders"], {"2030-01-02-example-lever": 3, "2030-01-03-example-more": 2})
        self.assertEqual(both["result"]["paired"], expected)  # what `paired.py <a> <b>` prints
        self.assertEqual(rows["2030-01-02-example-lever"]["result"]["games_in"], 3)  # the first record is unchanged
        self.assertEqual(rows["2030-01-02-example-lever"]["artifacts"], ["2030-01-02-example-lever"])

        listing = self.client.get("/experiments").text
        self.assertIn("5 of 28 games in", listing)
        self.assertIn("from 2 folders: 2030-01-02-example-lever (3), 2030-01-03-example-more (2)", listing)
        view = self.client.get("/experiments/2030-01-03-example-more").text
        self.assertIn("<code>.runtime/artifacts/2030-01-02-example-lever</code> (3 games)", view)
        self.assertIn("<code>.runtime/artifacts/2030-01-03-example-more</code> (2 games)", view)
        self.assertIn('href="/replays?batch=2030-01-02-example-lever&amp;policy=mine"', view)
        self.assertIn('href="/replays?batch=2030-01-03-example-more&amp;policy=mine"', view)

    def test_artifact_folders(self):
        """The same rule as `tools/run_ab.py: artifact_dirs`: the listed folders, then always the record's own."""
        folders = self.experiments.artifact_folders
        self.assertEqual(folders(None, "rec"), ["rec"])
        self.assertEqual(folders([], "rec"), ["rec"])  # empty: the record's own folder alone
        self.assertEqual(folders(["earlier"], "rec"), ["earlier", "rec"])  # its own folder is appended
        self.assertEqual(folders(["rec", "later"], "rec"), ["rec", "later"])  # listed first, it stays first
        self.assertEqual(folders(["a", "`.runtime/artifacts/b/`", "a", "'c'", "../x y"], "rec"), ["a", "b", "c", "rec"])
        self.assertEqual(folders("a", "rec"), ["rec"])  # not a list: the default

    def test_the_tool_and_the_page_read_the_same_folders(self):
        import run_ab

        for listed in ("", "artifacts: []\n", "artifacts: [old]\n", "artifacts: [rec, `.runtime/artifacts/b/`, c]\n"):
            text = f"---\nid: rec\n{listed}---\n\nArtifacts: `.runtime/artifacts/ignored`\n"
            meta, _ = self.experiments.front_matter(text)
            self.assertEqual([folder.name for folder in run_ab.artifact_dirs(text, "rec")],
                             self.experiments.artifact_folders(meta.get("artifacts"), "rec"), listed)

    def test_a_proposed_record_reads_as_an_idea_with_its_cost_and_one_request(self):
        spend = "28 press games, about 50 credits by the platform's estimate, about 70 minutes"
        proposed = RECORD.replace("candidate: mine:v2", "candidate: n/a").replace(
            "evals: [xreq_aaa, xreq_bbb]", f"cost: {spend}\nevals: []")
        self.record(status="proposed", text=proposed)
        row = self.client.get("/api/experiments").json()[0]
        self.assertEqual((row["status"], row["candidate"], row["cost"]),
                         ("proposed", "", spend))
        listing = self.client.get("/experiments").text
        self.assertIn("28 press games, about 50 credits by the platform&#39;s estimate, about 70 minutes", listing)
        self.assertIn("Not run. Nothing has been built or launched for it.", listing)
        self.assertIn(">Run this</button>", listing)
        self.assertNotIn("0 of 28 games in", listing)
        view = self.client.get("/experiments/2030-01-02-example-lever").text
        self.assertIn("This is a proposed experiment", view)
        self.assertIn("Not run yet.", view)
        self.assertNotIn("0 of 28 games in", view)
        self.assertIn(">Run this</button>", view)
        self.assertIn("tools/run_ab.py --record 2030-01-02-example-lever)", view)
        self.assertIn("tell me what it will cost before you launch", view)
        self.assertIn("Check closed_levers.md, open_levers.md and the earlier records in experiments/", view)
        for label in ("Ask the agent for the result", "Ask the agent to close this record"):
            self.assertNotIn(label, view)
        # Without a `cost:` the page falls back to the size the rule names.
        self.record(status="proposed", text=proposed.replace(f"cost: {spend}\n", ""))
        self.assertIn("28 games, by the rule; the record does not say what they cost",
                      self.client.get("/experiments").text)

    def test_a_row_written_by_ship_py_is_found_whatever_name_was_uploaded(self):
        """`tools/ship.py` logs every upload in `players/castlereagh/VERSION_LOG.md`, under the uploaded name."""
        import ship

        log = self.lab / "players" / "castlereagh" / "VERSION_LOG.md"
        log.parent.mkdir(parents=True)
        header = (MIXIN / "players" / "_VERSION_LOG_template.md").read_text()
        rows = [ship.version_log_row(name, version, "pv", "2030-01-02 13:14", "The change", "press", "", None,
                                     "tag", "", "ply_1") for name, version in (("mine", 2), ("mine-search", 1))]
        log.write_text(ship.insert_row(ship.insert_row(header, rows[0]), rows[1]))
        self.assertEqual(self.dashboard.shipped_policies()[:2], ["mine-search", "mine"])  # newest first
        found = self.experiments.version_rows(["mine:v2", "mine-search:v1"])
        self.assertEqual([row["version"] for row in found], ["mine:v2", "mine-search:v1"])
        self.assertEqual(found[0]["log"], "players/castlereagh/VERSION_LOG.md")

    def test_unknown_record_is_a_404_page(self):
        for name in ("nope", "..%2Fsecrets"):
            page = self.client.get(f"/experiments/{name}")
            self.assertEqual(page.status_code, 404)
        self.assertIn("No such experiment", self.client.get("/experiments/nope").text)

    def test_what_is_closed_lists_both_registers(self):
        (self.lab / "closed_levers.md").write_text(CLOSED)
        (self.lab / "best_practices.md").write_text(PRACTICES)
        text = self.client.get("/experiments").text
        self.assertIn("Example refuted lever", text)
        self.assertIn("closed 2030-01-05", text)
        self.assertIn("−0.111 over 99 synthetic paired games.", text)
        self.assertIn("Measuring", text)
        self.assertIn("2 practices", text)
        self.assertNotIn("Preface text.", text)

    def test_tested_with_no_result_is_a_third_list(self):
        self.assertIn("Nothing here yet: <code>open_levers.md</code>", self.client.get("/experiments").text)
        (self.lab / "open_levers.md").write_text(
            "# Tested, no result yet\n\nPreface.\n\n```\n## <lever name>     tested YYYY-MM-DD\n```\n\n---\n\n"
            "## Example lever, second dose                     tested 2030-01-06\n"
            "**Mechanism:** the synthetic change, again.\n"
            "**Read:** +0.011, SE 0.022, z 0.50 over 99 synthetic paired games.\n"
            "**Could see:** about 0.05.\n")
        text = self.client.get("/experiments").text
        section = text[text.index("Tested, no result yet"):text.index("Refuted levers")]
        self.assertIn("Example lever, second dose", section)
        self.assertIn("tested 2030-01-06", section)
        self.assertIn("+0.011, SE 0.022, z 0.50 over 99 synthetic paired games.", section)
        self.assertIn('<span class="count">1</span>', section)  # the format example in the preface is not an entry
        # The request to close a record sends an inconclusive result there.
        self.record()
        self.assertIn("or to open_levers.md if it is inconclusive",
                      self.client.get("/experiments/2030-01-02-example-lever").text)

    def test_home_names_a_running_experiment(self):
        self.record()
        self.games([(0.30, 0.10), (0.25, 0.20)])
        text = self.client.get("/").text
        self.assertIn("experiment running:", text)
        self.assertIn('<a href="/experiments/2030-01-02-example-lever">Example lever</a>', text)
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
