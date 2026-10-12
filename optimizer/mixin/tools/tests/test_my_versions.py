"""my_versions.py: paging, grouping by policy, and the league marks. No network."""

import unittest

import _path  # noqa: F401  (puts the tools folder on sys.path)
import my_versions


def version(name, number, version_id, created):
    return {"policy_version_id": version_id, "policy_name": name, "version": number, "created_at": created,
            "player_name": "A Player"}


def membership(version_id, league, status="competing", substatus="active", champion=False):
    return {"id": f"lpm_{version_id}_{league}", "status": status, "substatus": substatus, "is_champion": champion,
            "start_time": "2026-10-01T00:00:00Z", "end_time": None if status == "competing" else "2026-10-05T00:00:00Z",
            "league": {"id": f"league_{league}", "name": league}, "division": {"name": "Competition"},
            "policy_version": {"id": version_id}}


VERSIONS = [
    version("old-bot", 1, "id-old-1", "2026-09-01T10:00:00Z"),
    version("night", 1, "id-night-1", "2026-10-12T04:00:00Z"),
    version("old-bot", 2, "id-old-2", "2026-09-02T10:00:00Z"),
    version("night", 2, "id-night-2", "2026-10-12T06:56:00Z"),
]
MEMBERSHIPS = [
    membership("id-old-2", "Press", champion=True),
    membership("id-old-1", "Press", status="disqualified", substatus="superseded"),
    membership("id-old-2", "Gunboat", status="disqualified", substatus="inactive"),
]
WHO = {"subject_type": "player", "subject_id": "ply_1"}


class MyVersions(unittest.TestCase):
    def test_every_page_is_read(self):
        pages = {None: ([{"n": 1}, {"n": 2}], "token-2"), "token-2": ([{"n": 3}], None)}
        asked = []

        def get_page(path, params):
            asked.append(params)
            return pages[params.get("cursor")]

        rows = my_versions.all_pages(get_page, "/v2/policy-versions", {"limit": 2})
        self.assertEqual([row["n"] for row in rows], [1, 2, 3])
        self.assertEqual(asked, [{"limit": 2}, {"limit": 2, "cursor": "token-2"}])

    def test_a_player_asks_for_its_own_rows_and_a_user_for_all_of_theirs(self):
        self.assertEqual(my_versions.owner_filter(WHO), {"player_id": "ply_1"})
        self.assertEqual(my_versions.owner_filter({"subject_type": "user", "subject_id": "u1"}), {"mine": "true"})

    def test_policies_and_versions_are_newest_first(self):
        policies = my_versions.group_versions(VERSIONS, MEMBERSHIPS)
        self.assertEqual([p["policy"] for p in policies], ["night", "old-bot"])
        self.assertEqual([v["version"] for v in policies[0]["versions"]], [2, 1])
        self.assertEqual([v["version"] for v in policies[1]["versions"]], [2, 1])

    def test_only_a_competing_entry_counts_as_in_a_league(self):
        policies = my_versions.group_versions(VERSIONS, MEMBERSHIPS)
        night, old = policies
        self.assertEqual(night["in_league"], 0)
        self.assertEqual(old["in_league"], 1)  # v2 competes in Press; v1's entry ended
        v2 = old["versions"][0]
        self.assertEqual([(e["league"], e["current"]) for e in v2["leagues"]], [("Press", True), ("Gunboat", False)])

    def test_the_report_marks_current_entries_and_hides_ended_ones_unless_asked(self):
        policies = my_versions.group_versions(VERSIONS, MEMBERSHIPS)
        text = my_versions.render(policies, WHO, past=False)
        self.assertIn("4 version(s) in 2 policy name(s), 1 in a league now", text)
        self.assertIn("id-old-2  IN LEAGUE Press / Competition (active, champion)", text)
        self.assertNotIn("was in", text)
        self.assertLess(text.index("night"), text.index("old-bot"))
        with_past = my_versions.render(policies, WHO, past=True)
        self.assertIn("was in Gunboat / Competition (disqualified, inactive)", with_past)
        self.assertIn("id-old-1  was in Press / Competition (disqualified, superseded)", with_past)

    def test_filters(self):
        policies = my_versions.group_versions(VERSIONS, MEMBERSHIPS)
        self.assertEqual([p["policy"] for p in my_versions.select(policies, ["night"], False)], ["night"])
        entered = my_versions.select(policies, [], True)
        self.assertEqual([(p["policy"], [v["version"] for v in p["versions"]]) for p in entered], [("old-bot", [2])])


if __name__ == "__main__":
    unittest.main()
