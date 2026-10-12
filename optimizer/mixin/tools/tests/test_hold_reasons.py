"""hold_reasons.py: who chose a hold, where the unit stood, and the cuts by policy size. No files."""

import unittest

import _path  # noqa: F401  (puts the tools folder on sys.path)
import hold_reasons


def order(text, at, kind="hold"):
    return {"text": text, "at": at, "type": kind, "power": "FRANCE"}


CENTERS = {"PAR": "FRANCE", "BEL": "GERMANY"}
ORDERS = [order("A PAR H", "PAR"), order("A BEL H", "BEL"), order("A BUR H", "BUR"), order("F BRE/NC H", "BRE"),
          order("A MAR - SPA", "MAR", "move")]
POLICY = {"require_orders": ["F BRE H"], "forbid_moves_into": ["RUH", "MUN", "PIE", "TYR", "BOH"],
          "stances": {"GERMANY": "Ally", "ITALY": "hostile"}}


class HoldReasons(unittest.TestCase):
    def test_each_hold_is_sorted_by_who_chose_it_and_where_it_stood(self):
        counts = hold_reasons.phase_counts(ORDERS, POLICY, CENTERS, "FRANCE")
        self.assertEqual((counts["orders"], counts["holds"]), (5, 4))
        self.assertEqual(dict(counts["kinds"]), {kind: 1 for kind in hold_reasons.KINDS})  # coast dropped to match

    def test_policy_sizes_are_capped(self):
        counts = hold_reasons.phase_counts(ORDERS, POLICY, CENTERS, "FRANCE")
        self.assertEqual((counts["forbidden"], counts["allies"]), (4, 1))
        self.assertEqual(hold_reasons.phase_counts(ORDERS, {}, CENTERS, "FRANCE")["forbidden"], 0)

    def test_the_report_gives_shares_of_orders(self):
        total = hold_reasons.new_total()
        total["seats"] = 1
        hold_reasons.add(total, hold_reasons.phase_counts(ORDERS, POLICY, CENTERS, "FRANCE"))
        text = hold_reasons.render({"bot:v1": total})
        self.assertIn("| holds | 4 (80%) |", text)
        self.assertIn("| fixed by the agent | 1 (20%) |", text)
        self.assertIn("| 4 or more | 80% of 5 |", text)
        self.assertIn("| 0 | no orders |", text)


if __name__ == "__main__":
    unittest.main()
