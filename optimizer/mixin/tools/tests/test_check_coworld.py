import unittest

import _path  # noqa: F401  (puts the tools folder on sys.path)
import check_coworld

OLD = """# Changelog

Intro text.

## 2026-10-09 · Coworld 0.7.9 · Pinned countries

**In your optimizer:** nothing.
"""
NEW = OLD.replace("## 2026-10-09", """## 2026-11-02 · Coworld 0.8.0 · New phase rule

**In your optimizer:** update docs/game.md.

## Not an entry

## 2026-10-09""")


class Tests(unittest.TestCase):
    def test_entries_are_keyed_by_heading_and_keep_their_text(self):
        found = check_coworld.entries(NEW)
        self.assertEqual(list(found), ["## 2026-11-02 · Coworld 0.8.0 · New phase rule",
                                       "## 2026-10-09 · Coworld 0.7.9 · Pinned countries"])
        self.assertIn("update docs/game.md", found["## 2026-11-02 · Coworld 0.8.0 · New phase rule"])
        self.assertNotIn("Not an entry", "".join(found.values()))
        self.assertEqual(check_coworld.newest_version(NEW), "0.8.0")

    def test_a_current_lab_reports_nothing(self):
        self.assertEqual(check_coworld.report(OLD, OLD, "0.7.9"), [])
        self.assertEqual(check_coworld.report(OLD, OLD, None), [])   # the CLI could not say

    def test_new_entries_are_listed_with_what_to_do(self):
        lines = check_coworld.report(OLD, NEW, "0.8.0")
        self.assertIn("1 changelog entry since", lines[0])
        self.assertEqual(lines[1], "- 2026-11-02 · Coworld 0.8.0 · New phase rule")
        self.assertIn("--ack", lines[2])
        self.assertEqual(len(lines), 3)

    def test_a_hosted_version_the_changelog_does_not_name_is_reported(self):
        lines = check_coworld.report(OLD, OLD, "0.8.0")
        self.assertEqual(len(lines), 1)
        self.assertIn("hosted webDiplomacy Coworld is 0.8.0", lines[0])

    def test_a_lab_with_no_copy_counts_every_entry(self):
        lines = check_coworld.report(None, NEW, "0.8.0")
        self.assertIn("has no CHANGELOG.md", lines[0])
        self.assertIn("2 changelog entries", lines[1])

    def test_canonical_version(self):
        listing = {"entries": [{"name": "webdiplomacy", "version": "0.7.8", "canonical": False},
                               {"name": "webdiplomacy", "version": "0.7.9", "canonical": True},
                               {"name": "paintbot", "version": "1.0", "canonical": True}]}
        self.assertEqual(check_coworld.canonical_version(listing), "0.7.9")
        self.assertIsNone(check_coworld.canonical_version({"entries": []}))


if __name__ == "__main__":
    unittest.main()
