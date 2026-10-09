import unittest

from pydantic import ValidationError

from adapter.config import EpisodeConfig
from adapter.episode import Episode, scores, year_complete


class EpisodeRules(unittest.TestCase):
    def test_seed_default_varies_and_explicit_seed_is_preserved(self):
        from unittest.mock import patch

        with patch("adapter.config.secrets.randbits", side_effect=[123, 456]):
            self.assertEqual(EpisodeConfig(tokens=list("abcdefg")).seed, 123)
            self.assertEqual(EpisodeConfig(tokens=list("abcdefg")).seed, 456)
            self.assertEqual(EpisodeConfig(tokens=list("abcdefg"), seed=17).seed, 17)

    def test_year_cap_waits_for_autumn_retreats(self):
        for phase in ("Diplomacy", "Retreats"):
            self.assertFalse(year_complete({"turn": 1, "phase": phase}, 1901))
        self.assertTrue(year_complete({"turn": 1, "phase": "Builds"}, 1901))
        self.assertTrue(year_complete({"turn": 2, "phase": "Diplomacy"}, 1901))

    def test_scores_follow_shuffled_slots_and_exclude_defeated(self):
        members = [
            {"countryID": i, "status": "Drawn" if i < 3 else "Defeated", "supplyCenterNo": 3 if i == 1 else 4}
            for i in range(1, 8)
        ]
        countries = [2, 4, 1, 7, 3, 5, 6]
        self.assertEqual(scores(members, countries, "sum_of_squares"), [16 / 25, 0, 9 / 25, 0, 0, 0, 0])
        self.assertEqual(scores(members, countries, "supply_centers"), [4 / 7, 0, 3 / 7, 0, 0, 0, 0])
        self.assertEqual(scores(members, countries, "draw_size"), [0.5, 0, 0.5, 0, 0, 0, 0])
        members[0]["status"] = "Won"
        self.assertEqual(scores(members, countries, "draw_size"), [0, 0, 1, 0, 0, 0, 0])
        self.assertEqual(scores([], countries, "sum_of_squares", cancelled=True), [1 / 7] * 7)

    def test_tokens_are_unique_and_fit_upstream_column(self):
        for tokens in (["x"] * 7, ["x" * 81] + list("abcdef")):
            with self.assertRaises(ValidationError):
                EpisodeConfig(tokens=tokens)

    def test_countries_must_be_a_permutation_of_upstream_ids(self):
        tokens = list("abcdefg")
        self.assertEqual(EpisodeConfig(tokens=tokens, countries=[7, 6, 5, 4, 3, 2, 1]).countries, [7, 6, 5, 4, 3, 2, 1])
        self.assertIsNone(EpisodeConfig(tokens=tokens).countries)
        for countries in (
            [1, 1, 2, 3, 4, 5, 6],
            [1, 2, 3, 4, 5, 6],
            [1, 2, 3, 4, 5, 6, 7, 1],
            [0, 1, 2, 3, 4, 5, 6],
            [2, 3, 4, 5, 6, 7, 8],
        ):
            with self.assertRaises(ValidationError):
                EpisodeConfig(tokens=tokens, countries=countries)

    def test_episode_uses_pinned_countries_and_otherwise_shuffles_by_seed(self):
        from unittest.mock import patch

        created = {"ok": True, "game_id": 1, "seats": []}
        with patch("adapter.episode.php", return_value=created) as php, patch.object(Episode, "tick"):
            pinned = Episode(EpisodeConfig(tokens=list("abcdefg"), seed=5, countries=[3, 1, 2, 7, 6, 5, 4]))
            self.assertEqual(pinned.countries, [3, 1, 2, 7, 6, 5, 4])
            self.assertEqual(php.call_args.kwargs["payload"]["countries"], [3, 1, 2, 7, 6, 5, 4])
            first = Episode(EpisodeConfig(tokens=list("abcdefg"), seed=5)).countries
            self.assertEqual(Episode(EpisodeConfig(tokens=list("abcdefg"), seed=5)).countries, first)
            self.assertEqual(sorted(first), list(range(1, 8)))
