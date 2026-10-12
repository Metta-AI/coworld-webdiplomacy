"""centre_losses.py: one row per lost centre, stances by game year, and the pair-year counts. No files."""

import unittest

import _path  # noqa: F401  (puts the tools folder on sys.path)
import centre_losses


def phase(turn, centers):
    return {"turn": turn, "centers": centers}


def commit(turn, stances, trust=None):
    policy = None if stances is None else {"stances": stances, **({"trust": trust} if trust else {})}
    return {"event": "press_commit", "turn": turn, "press_policy": policy}


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
    # the year's last commit is the one counted
    commit(1, {"GERMANY": "Ally", "ENGLAND": "neutral"}, trust={"England": 0.7, "GERMANY": 0.2}),
    commit(2, {"GERMANY": "hostile"}),
    commit(3, None),  # a commit without a policy does not replace the year's stances
    {"event": "press_out", "turn": 1, "to": "GERMANY", "text": "Belgium is mine, agreed?"},
    {"event": "press_out", "turn": 2, "to": "ENGLAND", "text": "Stay out of the Channel."},
    {"event": "press_in", "turn": 3, "frm": "ENGLAND", "to": "us", "text": "Of course."},
]
HOMES = {"PAR": "FRANCE", "BRE": "FRANCE", "MUN": "GERMANY", "LON": "ENGLAND"}


class CentreLosses(unittest.TestCase):
    def test_the_last_commit_of_a_year_with_a_policy_gives_the_stances(self):
        stances = centre_losses.stances_by_year(EVENTS)
        self.assertEqual(stances[1901], {"GERMANY": "ally", "ENGLAND": "neutral"})
        self.assertEqual(stances[1902], {"GERMANY": "hostile"})
        self.assertEqual(centre_losses.stance_toward(stances, 1902, "ENGLAND"), "unnamed")
        self.assertEqual(centre_losses.stance_toward(stances, 1903, "ENGLAND"), "no commit")

    def test_centres_taken_are_dated_to_the_year_they_changed_hands(self):
        taken = centre_losses.centres_taken(PHASES, "FRANCE")
        self.assertEqual(dict(taken[1901]), {"GERMANY": 1})
        self.assertEqual(dict(taken[1902]), {"ENGLAND": 1})

    def test_each_lost_centre_is_one_row_with_what_we_thought_of_the_taker(self):
        belgium, brest = centre_losses.seat_losses(PHASES, "FRANCE", EVENTS, HOMES)
        self.assertEqual(belgium, {
            "year": 1901, "centre": "BEL", "kind": "gained centre", "taker": "GERMANY",
            "stance_before": "no commit", "stance_that_year": "ally", "trust_before": "no commit",
            "talks": "only we wrote",
        })
        self.assertEqual(brest, {
            "year": 1902, "centre": "BRE", "kind": "home centre", "taker": "ENGLAND",
            "stance_before": "neutral", "stance_that_year": "unnamed", "trust_before": "trusted",
            "talks": "both wrote",
        })

    def test_trust_and_talks_have_a_value_when_nothing_was_said_or_set(self):
        policies = centre_losses.policies_by_year(EVENTS)
        self.assertEqual(centre_losses.trust_toward(policies, 1901, "GERMANY"), "distrusted")
        self.assertEqual(centre_losses.trust_toward(policies, 1902, "ENGLAND"), "no number")
        talks = centre_losses.talks_by_year(EVENTS)
        self.assertEqual(centre_losses.talks_with(talks, 1902, "GERMANY"), "silence")
        self.assertEqual(centre_losses.talks_with(talks, 1905, "GERMANY"), "silence")

    def test_losses_and_pair_years_are_split_by_stance(self):
        counts = centre_losses.seat_counts(PHASES, "FRANCE", EVENTS)
        self.assertEqual(dict(counts["lost"]), {"ally": 1, "unnamed": 1})
        # 1901: Germany ally (hit), England neutral. 1902: Germany hostile, England unnamed (hit).
        self.assertEqual(dict(counts["pair_years"]), {"ally": 1, "neutral": 1, "hostile": 1, "unnamed": 1})
        self.assertEqual(dict(counts["pair_years_hit"]), {"ally": 1, "unnamed": 1})

    def test_going_in_uses_the_stance_of_the_year_before(self):
        counts = centre_losses.seat_counts(PHASES, "FRANCE", EVENTS, going_in=True)
        # 1901 has no earlier year; in 1902 England was neutral and Germany an ally going in.
        self.assertEqual(dict(counts["lost"]), {"no commit": 1, "neutral": 1})
        self.assertEqual(dict(counts["pair_years"]), {"no commit": 2, "neutral": 1, "ally": 1})

    def totals(self):
        totals = {}
        losses = [{"episode": "ereq_1", "power": "FRANCE", **loss}
                  for loss in centre_losses.seat_losses(PHASES, "FRANCE", EVENTS, HOMES)]
        centre_losses.add(totals.setdefault("bot:v1", {}), centre_losses.seat_counts(PHASES, "FRANCE", EVENTS), losses)
        return totals

    def test_the_report_gives_the_share_beside_each_count(self):
        text = centre_losses.render(self.totals(), {})
        self.assertIn("seats read: bot:v1 1", text)
        self.assertIn("centres lost (per seat): bot:v1 2 (2.00)", text)
        self.assertIn("| ally | 1 (50%) |", text)  # stance that year
        self.assertIn("| trusted | 1 (50%) |", text)
        self.assertIn("| both wrote | 1 (50%) |", text)
        self.assertIn("| home centre | 1 (50%) |", text)
        self.assertIn("| GERMANY | 1 (50%) |", text)
        self.assertIn("| BRE | 1 (50%) |", text)
        self.assertIn("| ally | 1 of 1 (100.0%) |", text)
        self.assertIn("| hostile | 0 of 1 (0.0%) |", text)

    def test_rows_list_every_lost_centre(self):
        text = centre_losses.render_rows(self.totals())
        self.assertIn("| bot:v1 | ereq_1 | France | 1902 | BRE (home centre) | England | neutral | unnamed "
                      "| trusted | both wrote |", text)
        self.assertEqual(len(text.splitlines()), 4)


if __name__ == "__main__":
    unittest.main()
