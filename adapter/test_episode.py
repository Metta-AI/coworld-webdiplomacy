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

    def test_players_name_every_seat_or_none(self):
        tokens = list("abcdefg")
        self.assertEqual(EpisodeConfig(tokens=tokens).players, [])
        named = EpisodeConfig(tokens=tokens, players=[{"name": f"P{i}"} for i in range(7)])
        self.assertEqual(named.players[6].name, "P6")
        for players in ([{"name": "P"}] * 6, [{"name": ""}] * 7, [{"name": "P", "owner": "x"}] * 7):
            with self.assertRaises(ValidationError):
                EpisodeConfig(tokens=tokens, players=players)

    def test_platform_writes_seat_names_into_this_schema(self):
        # The platform fills players[].name only when the schema has this inline shape.
        from coworld.manifest_validation import game_config_with_named_players

        names = [f"Player {i} (Owner)" for i in range(7)]
        named = game_config_with_named_players(
            {"seed": 1}, names, EpisodeConfig.model_json_schema(), player_owners=["Owner"] * 7
        )
        self.assertEqual([player.name for player in EpisodeConfig(tokens=list("abcdefg"), **named).players], names)

    def test_seat_names_reach_only_the_saved_replay(self):
        from unittest.mock import patch

        created = {"ok": True, "game_id": 1, "seats": []}
        config = EpisodeConfig(
            tokens=list("abcdefg"), countries=[3, 1, 2, 7, 6, 5, 4], players=[{"name": f"P{i}"} for i in range(7)]
        )
        with patch("adapter.episode.php", return_value=created) as php, patch.object(Episode, "tick"):
            episode = Episode(config)
        self.assertNotIn("players", php.call_args.kwargs["payload"])
        live = {"game": {}, "episode": {"seed": 1}}
        episode.frames = [live]
        saved = episode.saved_frames()
        self.assertEqual(saved[0]["episode"]["players"][0], {"slot": 0, "countryID": 3, "name": "P0"})
        self.assertEqual(live, {"game": {}, "episode": {"seed": 1}})
        episode.config = EpisodeConfig(tokens=list("abcdefg"))
        self.assertIs(episode.saved_frames(), episode.frames)

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
