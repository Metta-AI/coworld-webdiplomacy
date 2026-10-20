import unittest

import _path  # noqa: F401  (puts the tools folder on sys.path)
import field


def seat(**overrides):
    base = {"position": 0, "policy_version_id": "pv-1", "label": "alpha-bot:v3", "is_filler": False,
            "player_name": "Alpha", "owner_name": "David B"}
    return {**base, **overrides}


class SeatName(unittest.TestCase):
    def test_human_owned_player_is_player_then_owner(self):
        self.assertEqual(field.seat_name(seat()), "Alpha (David B)")

    def test_player_without_human_owner_is_the_player_alone(self):
        self.assertEqual(field.seat_name(seat(owner_name=None)), "Alpha")

    def test_filler_and_playerless_seats_have_no_name_here(self):
        self.assertIsNone(field.seat_name(seat(is_filler=True)))
        self.assertIsNone(field.seat_name(seat(player_name=None)))

    def test_add_episode_records_the_seat_name(self):
        rows = {}
        field.add_episode(rows, 7, {"participants": [seat()], "participant_scores": [{"position": 0, "score": 0.5}]})
        self.assertEqual(rows["alpha-bot:v3"]["seat_name"], "Alpha (David B)")


if __name__ == "__main__":
    unittest.main()
