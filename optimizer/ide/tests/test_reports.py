"""The reports pages: listing by kind, front matter, the Markdown renderer and its safety."""

import json
import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from webdip_ide import episodes, reports_markdown, routes_reports
from webdip_ide.server import create_app

PROFILE = """---
title: How rival-bot plays
date: 2026-10-11
policy: ours:v3
opponent: rival-bot:v2
games: 56
sources: .runtime/artifacts/batch, classic-press
---

# How rival-bot plays

It opens the same way **every** game as Turkey.

## Patterns

| As | n | First target |
|---|---:|---|
| Turkey | 21 | Russia |

- **Evidence:** 21 of 21 games. [Autumn 1901](/replays/ereq_abc?phase=1), and /replays/ereq_def?phase=3
- <script>alert(1)</script> and [bad](javascript:alert(1))
"""


def write_episode(root: Path, name: str, policies: list[str]) -> None:
    ep = root / ".runtime" / "artifacts" / "batch" / name
    ep.mkdir(parents=True)
    countries = list(range(1, len(policies) + 1))
    (ep / "results.json").write_text(json.dumps({
        "scores": [0.1] * len(policies), "countries": countries, "outcome": "drawn", "reason": "end_year",
        "members": [{"countryID": str(c), "supplyCenterNo": "3"} for c in countries],
        "final_state": {"turn": "4", "phase": "Finished"}}))
    participants = [{"position": i, "policy_name": p.split(":v")[0], "version": int(p.split(":v")[1])}
                    for i, p in enumerate(policies)]
    (ep / "episode.json").write_text(json.dumps({"id": name, "status": "completed", "participants": participants}))


class ReportsPages(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.lab = Path(tmp.name)
        (self.lab / "tools").symlink_to(Path(__file__).resolve().parents[2] / "mixin" / "tools")
        previous = os.environ.get("WEBDIP_LAB")
        os.environ["WEBDIP_LAB"] = str(self.lab)
        self.addCleanup(lambda: os.environ.pop("WEBDIP_LAB") if previous is None
                        else os.environ.__setitem__("WEBDIP_LAB", previous))
        episodes._basic.clear()
        self.client = TestClient(create_app())

    def write(self, kind: str, slug: str, text: str) -> None:
        folder = self.lab / "reports" / kind
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{slug}.md").write_text(text)

    def test_empty_lab_keeps_the_tables_and_says_there_is_nothing(self):
        page = self.client.get("/reports")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Opponent profiles", page.text)
        self.assertIn("Matchup write-ups", page.text)
        self.assertIn("No opponent profiles yet.", page.text)
        self.assertIn("No matchup write-ups yet.", page.text)
        self.assertIn("Ask the agent for a matchup write-up", page.text)

    def test_list_shows_front_matter_by_kind(self):
        self.write("opponents", "rival-bot", PROFILE)
        matchup = "---\ntitle: Why ours loses\npolicy: ours:v3\nopponent: field\n---\nBody"
        self.write("matchups", "ours-vs-field", matchup)
        page = self.client.get("/reports").text
        self.assertIn('href="/reports/opponents/rival-bot"', page)
        self.assertIn("How rival-bot plays", page)
        self.assertIn("rival-bot:v2", page)
        self.assertIn("2026-10-11", page)
        self.assertIn('href="/reports/matchups/ours-vs-field"', page)
        self.assertIn("file changed", page)  # the matchup has no date: say what the shown time is
        only = self.client.get("/reports?kind=matchups").text
        self.assertNotIn("How rival-bot plays", only)
        self.assertEqual(self.client.get("/reports?kind=nonsense").status_code, 404)

    def test_policies_without_a_profile_get_an_ask_button(self):
        write_episode(self.lab, "ereq_1", ["rival-bot:v2", "other-bot:v1", "ours:v3"])
        write_episode(self.lab, "ereq_2", ["rival-bot:v3", "other-bot:v1", "ours:v3"])
        self.write("opponents", "rival-bot", PROFILE)
        page = self.client.get("/reports").text
        self.assertIn('aria-label="Ask the agent for a profile of other-bot"', page)
        self.assertNotIn('aria-label="Ask the agent for a profile of rival-bot"', page)
        # The profile names v2; the data also holds v3.
        self.assertIn("newer version on disk", page)
        view = self.client.get("/reports/opponents/rival-bot").text
        self.assertIn("rival-bot:v3", view)
        self.assertIn("ask for a refresh", view)
        # Nothing says which policy is ours yet, so ours is listed too, and the page says why.
        self.assertIn('aria-label="Ask the agent for a profile of ours"', page)
        self.assertIn("nothing in this lab says yet", page)

    def test_our_own_policies_are_not_offered_an_opponent_profile(self):
        from webdip_ide import store

        write_episode(self.lab, "ereq_1", ["rival-bot:v2", "other-bot:v1", "ours:v3", "ours-search:v1"])
        store.set_followed_policy("ours")  # the agent recorded it
        log = self.lab / "players" / "castlereagh" / "VERSION_LOG.md"
        log.parent.mkdir(parents=True)
        log.write_text("| Version | id |\n|---|---|\n| ours-search:v1 | `x` |\n")  # the lab uploaded it
        page = self.client.get("/reports").text
        self.assertIn('aria-label="Ask the agent for a profile of other-bot"', page)
        for name in ("ours", "ours-search"):
            self.assertNotIn(f'aria-label="Ask the agent for a profile of {name}"', page)
        self.assertIn('Left out as ours: <span class="mono">ours, ours-search</span>', page)

    def test_unreadable_episodes_are_reported_not_passed_off_as_full_coverage(self):
        broken = self.lab / ".runtime" / "artifacts" / "batch" / "ereq_broken"
        broken.mkdir(parents=True)
        (broken / "results.json").write_text("{not json")
        self.write("opponents", "rival-bot", PROFILE)
        page = self.client.get("/reports").text
        self.assertIn("1 episode on disk could not be read", page)
        self.assertNotIn("Every policy in the fetched episodes has a profile", page)

    def test_a_gunboat_profile_in_its_own_file_covers_the_policy_it_names(self):
        write_episode(self.lab, "ereq_1", ["rival-bot:v2", "rival-bot-press:v1", "ours:v3"])
        gunboat = PROFILE.replace("games: 56", "games: 56\nvariant: classic-gunboat")
        self.write("opponents", "rival-bot-gunboat", gunboat)
        page = self.client.get("/reports").text
        self.assertNotIn('aria-label="Ask the agent for a profile of rival-bot"', page)
        self.assertIn('aria-label="Ask the agent for a profile of rival-bot-press"', page)
        self.assertIn("classic-gunboat", page)

    def test_report_page_renders_markdown_and_links_replays(self):
        self.write("opponents", "rival-bot", PROFILE)
        page = self.client.get("/reports/opponents/rival-bot")
        self.assertEqual(page.status_code, 200)
        text = page.text
        self.assertEqual(text.count("<h1>"), 1)  # the body's own title is not repeated
        self.assertIn("<strong>every</strong>", text)
        self.assertIn('<th class="num">n</th>', text)
        self.assertIn('<td class="num">21</td>', text)
        self.assertIn('<a href="/replays/ereq_abc?phase=1">Autumn 1901</a>', text)
        self.assertIn('<a href="/replays/ereq_def?phase=3" class="path">/replays/ereq_def?phase=3</a>', text)
        self.assertIn("Ask the agent to refresh this report", text)
        self.assertIn("reports/opponents/rival-bot.md", text)

    def test_buttons_that_send_at_once_say_so(self):
        write_episode(self.lab, "ereq_1", ["rival-bot:v2", "other-bot:v1", "ours:v3"])
        self.write("opponents", "rival-bot", PROFILE)
        page = self.client.get("/reports").text
        self.assertIn("sends its request to the agent at once; nothing waits in the message box", page)
        self.assertIn('title="Sends the request at once: the agent runs the skill again', page)  # a refresh
        self.assertIn('title="Sends the request at once: the agent writes an opponent profile of other-bot"', page)
        self.assertIn("A click sends the request at once.", page)  # beside the matchup button
        view = self.client.get("/reports/opponents/rival-bot").text
        self.assertIn("A click sends the request at once; nothing waits in the message box.", view)

    def test_report_html_is_escaped_and_bad_links_stay_text(self):
        self.write("opponents", "rival-bot", PROFILE)
        text = self.client.get("/reports/opponents/rival-bot").text
        self.assertNotIn("<script>alert(1)</script>", text)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", text)
        self.assertNotIn('href="javascript:', text)

    def test_unknown_reports_and_path_tricks_are_404(self):
        (self.lab / "secret.md").write_text("# secret")
        self.write("opponents", "rival-bot", PROFILE)
        for url in ("/reports/opponents/nobody", "/reports/other/rival-bot", "/reports/opponents/..%2F..%2Fsecret",
                    "/reports/opponents/.hidden"):
            self.assertEqual(self.client.get(url).status_code, 404, url)

    def test_json_list(self):
        self.write("opponents", "rival-bot", PROFILE)
        rows = self.client.get("/api/reports").json()
        self.assertEqual([(r["kind"], r["slug"], r["games"]) for r in rows], [("opponents", "rival-bot", "56")])
        self.assertNotIn("body", rows[0])


class Markdown(unittest.TestCase):
    def test_front_matter(self):
        meta, body = reports_markdown.split_front_matter('---\ntitle: "A: B"\nGames: 7\n---\n# Hi\n')
        self.assertEqual(meta, {"title": "A: B", "games": "7"})
        self.assertEqual(body.strip(), "# Hi")
        self.assertEqual(reports_markdown.split_front_matter("# No front matter"), ({}, "# No front matter"))
        self.assertEqual(reports_markdown.split_front_matter("---\nnever closed")[0], {})

    def test_blocks(self):
        html = reports_markdown.render(
            "# T\n\npara one\nstill one\n\n## H2\n\n1. first\n2. second\n   - nested\n\n> quoted\n\n---\n\n"
            "```\n<b>code</b> | x\n```\n"
        )
        self.assertIn("<h1>T</h1>", html)
        self.assertIn("<p>para one still one</p>", html)
        self.assertIn("<ol><li>first</li><li>second<ul><li>nested</li></ul></li></ol>", html)
        self.assertIn("<blockquote><p>quoted</p></blockquote>", html)
        self.assertIn("<hr>", html)
        self.assertIn("<pre><code>&lt;b&gt;code&lt;/b&gt; | x</code></pre>", html)

    def test_list_items_keep_their_continuation_lines(self):
        html = reports_markdown.render("- **Evidence:** 21 of 21\n  games as Turkey\n- next")
        self.assertIn("<li><strong>Evidence:</strong> 21 of 21 games as Turkey</li><li>next</li>", html)

    def test_inline(self):
        inline = reports_markdown.render_inline
        self.assertEqual(inline("a **b** *c* `d*e*`"), "a <strong>b</strong> <em>c</em> <code>d*e*</code>")
        self.assertEqual(inline("some_policy_name_v2 and 2 * 3 * 4"), "some_policy_name_v2 and 2 * 3 * 4")
        self.assertEqual(inline("x < y & z"), "x &lt; y &amp; z")
        self.assertIn('target="_blank" rel="noopener noreferrer"', inline("[site](https://example.com/a?b=1&c=2)"))
        self.assertIn('href="https://example.com/a?b=1&amp;c=2"', inline("[site](https://example.com/a?b=1&c=2)"))
        self.assertEqual(inline("[x](//evil.example)"), "[x](//evil.example)")
        self.assertEqual(inline("[x](data:text/html,hi)"), "[x](data:text/html,hi)")
        self.assertEqual(inline('[x](/a"onclick="y)'), '<a href="/a&quot;onclick=&quot;y">x</a>')
        self.assertEqual(inline("see docs/replays/x and a/replays/y"), "see docs/replays/x and a/replays/y")
        self.assertEqual(inline("one<br>two"), "one<br>two")

    def test_a_link_label_keeps_its_code_and_bold(self):
        html = reports_markdown.render_inline("[`ep-1` **lost**](/replays/ep-1) then [x](/replays/`y`)")
        self.assertIn('<a href="/replays/ep-1"><code>ep-1</code> <strong>lost</strong></a>', html)
        self.assertNotIn("\x00", html)
        self.assertNotIn('href="/replays/<', html)  # a code span is never part of an address

    def test_hostile_text_cannot_stall_or_break_the_page(self):
        deep = "\n".join(" " * (2 * level) + "- x" for level in range(3000))
        self.assertEqual(reports_markdown.render(deep).count("<li>"), 3000)  # was a RecursionError
        for run in ("**a " * 5000, "[a](" * 5000, "[" * 20000, "x" * 1_000_000 + " <script>"):
            html = reports_markdown.render(run)
            self.assertNotIn("<script", html)
        self.assertNotIn("\x00", reports_markdown.render("```\n\x00\n```\n\x000\x00 `a`"))

    def test_tables(self):
        source = "| as | n | note |\n|---|---|---|\n| Turkey | 21 | a `b|c` d |\n| Italy | 3* | - |"
        html = reports_markdown.render(source)
        self.assertIn('<th class="num">n</th>', html)
        self.assertIn("<td>Turkey</td>", html)
        self.assertIn('<td class="num">3*</td>', html)
        self.assertIn("<code>b|c</code>", html)
        self.assertIn("<th>note</th>", html)

    def test_profile_slug_matches_the_lab_tool(self):
        import sys

        from lab_source import lab_source

        sys.path.insert(0, str(lab_source() / "tools"))
        import opponent_profile

        for name in ("House-Bot:v2", "My_Bot.press:v10", "plain"):
            self.assertEqual(routes_reports._slug(name), opponent_profile.slug(name))


if __name__ == "__main__":
    unittest.main()
