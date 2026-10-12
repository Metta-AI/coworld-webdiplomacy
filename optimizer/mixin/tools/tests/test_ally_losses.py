"""ally_losses.py: stances by game year, centres taken, and the pair-year counts. No files."""

import unittest

import _path  # noqa: F401  (puts the tools folder on sys.path)
import ally_losses


def phase(turn, centers):
    return {"turn": turn, "centers": centers}


def commit(turn, stances):
    return {"event": "press_commit", "turn": turn, "press_policy": None if stances is None else {"stances": stances}}


# We are FRANCE. 1901: Germany (ally) takes BEL from us. 1902: England (unnamed) takes BRE,
# Germany (now hostile) takes nothing. Turn 4 is the last phase: 1903 is not counted.
PHASES = [
    phase(0, {"PAR": "FRANCE", "BEL": "FRANCE", "BRE": "FRANCE", "MUN": "GERMANY", "LON": "ENGLAND"}),
    phase(1, {"PAR": "FRANCE", "BEL": "FRANCE", "BRE": "FRANCE", "MUN": "GERMANY", "LON": "ENGLAND"}),
    phase(2, {"PAR": "FRANCE", "BEL": "GERMANY", "BRE": "FRANCE", "MUN": "GERMANY", "LON": "ENGLAND"}),
    phase(3, {"PAR": "FRANCE", "BEL": "GERMANY", "BRE": "FRANCE", "MUN": "GERMANY", "LON": "ENGLAND"}),
    phase(4, {"PAR": "FRANCE", "BEL": "GERMANY", "BRE": "ENGLAND", "MUN": "GERMANY", "LON": "ENGLAND"}),
]
EVENTS = [
    commit(0, {"Germany": "hostile"}),
    commit(1, {"GERMANY": "Ally", "ENGLAND": "neutral"}),  # the year's last commit is the one counted
    commit(2, {"GERMANY": "hostile"}),
    commit(3, None),  # a commit without a policy does not replace the year's stances
]


class AllyLosses(unittest.TestCase):
    def test_the_last_commit_of_a_year_with_a_policy_gives_the_stances(self):
        stances = ally_losses.stances_by_year(EVENTS)
        self.assertEqual(stances[1901], {"GERMANY": "ally", "ENGLAND": "neutral"})
        self.assertEqual(stances[1902], {"GERMANY": "hostile"})
        self.assertEqual(ally_losses.stance_toward(stances, 1902, "ENGLAND"), "unnamed")
        self.assertEqual(ally_losses.stance_toward(stances, 1903, "ENGLAND"), "no commit")

    def test_centres_taken_are_dated_to_the_year_they_changed_hands(self):
        taken = ally_losses.centres_taken(PHASES, "FRANCE")
        self.assertEqual(dict(taken[1901]), {"GERMANY": 1})
        self.assertEqual(dict(taken[1902]), {"ENGLAND": 1})

    def test_losses_and_pair_years_are_split_by_stance(self):
        counts = ally_losses.seat_counts(PHASES, "FRANCE", EVENTS)
        self.assertEqual(dict(counts["lost"]), {"ally": 1, "unnamed": 1})
        # 1901: Germany ally (hit), England neutral. 1902: Germany hostile, England unnamed (hit).
        self.assertEqual(dict(counts["pair_years"]), {"ally": 1, "neutral": 1, "hostile": 1, "unnamed": 1})
        self.assertEqual(dict(counts["pair_years_hit"]), {"ally": 1, "unnamed": 1})

    def test_going_in_uses_the_stance_of_the_year_before(self):
        counts = ally_losses.seat_counts(PHASES, "FRANCE", EVENTS, going_in=True)
        # 1901 has no earlier year; in 1902 England was neutral and Germany an ally going in.
        self.assertEqual(dict(counts["lost"]), {"no commit": 1, "neutral": 1})
        self.assertEqual(dict(counts["pair_years"]), {"no commit": 2, "neutral": 1, "ally": 1})

    def test_the_report_gives_the_rate_beside_its_count(self):
        totals = {}
        ally_losses.add(totals.setdefault("bot:v1", {}), ally_losses.seat_counts(PHASES, "FRANCE", EVENTS))
        text = ally_losses.render(totals, {})
        self.assertIn("seats read: bot:v1 1", text)
        self.assertIn("| ally | 1 (50%) |", text)
        self.assertIn("| ally | 1 of 1 (100.0%) |", text)
        self.assertIn("| hostile | 0 of 1 (0.0%) |", text)


if __name__ == "__main__":
    unittest.main()
