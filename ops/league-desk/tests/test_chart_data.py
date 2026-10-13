"""Invented chart contract regressions from the P4 presentation review."""
import unittest

from test_competition import rating_row

from league_desk.competition_metrics import exposure, histories, rating_history
from league_desk.game_metrics import round_durations
from league_desk.spend_metrics import model_usage, seat_spend, source_label


class ChartDataTests(unittest.TestCase):
    def test_poll_gaps_connect_observations_but_resets_and_deltas_stay_separate(self):
        history = [{"observed_at": time, "data": {"rows": [rating_row(rounds_played=rounds)], "poll_gap": True}}
                   for time, rounds in ((1, 2), (2, 5), (3, 0))]
        points = rating_history(history)
        self.assertEqual(points[0]["plot_series"], points[1]["plot_series"])
        self.assertNotEqual(points[1]["plot_series"], points[2]["plot_series"])
        self.assertNotEqual(points[0]["segment"], points[1]["segment"])
        history[1]["data"]["rows"][0]["sigma"] = None
        result = histories(rating_history(history))["Rating interval over time"]
        self.assertIn("unavailable at 1/3", result["note"])
        self.assertIsNone(result["chart"]["data"][1]["low"])

    def test_current_round_reference_does_not_rewrite_historical_interval(self):
        result = round_durations([{"number": 1, "created_at": 1, "completed_at": 120,
                                   "status": "completed", "skip_kind": None}],
                                 [{"observed_at": 200, "data": {"round_interval_minutes": 60}}], 300)
        self.assertEqual(result["chart"]["reference"], 60)
        self.assertIsNone(result["chart"]["data"][0]["reference"])

    def test_seat_dots_group_by_identity_and_sort_by_median(self):
        games = [{"id": "game", "seats": [{"slot": n, "player_id": key, "player": "Same display name"}
                                          for n, key in enumerate(["a", "a", "b"])]}]
        usage = {"rows": [{"episode": "game", "slot": n, "estimated": value, "calls": 1, "rejections": 0}
                          for n, value in enumerate([1, 3, 4])]}
        result, keyed, _ = seat_spend(usage, games, 5)
        self.assertEqual(result["chart"]["order"], ["b", "a"])
        self.assertEqual(len(result["chart"]["data"]), 3)
        self.assertEqual(len(keyed), 3)
        self.assertEqual(result["chart"]["reference"], 5)

    def test_models_aggregate_roles_with_source_split_and_failure_rate(self):
        base = {"model": "provider/long-model-name", "role": "player", "source": "xp_request",
                "invocations": 20, "error_count": 3, "estimated_cost_usd": 2, "policy": None, "player": None}
        result, _ = model_usage({"rows": [base, {**base, "role": "other"},
                                         {**base, "model": "provider/expensive", "estimated_cost_usd": 8}]})
        self.assertIn("Failure rate", result["columns"])
        self.assertIn("15.0%", result["rows"][0])
        self.assertEqual(result["chart"]["order"][0], "provider/expensive")
        self.assertEqual(result["chart"]["data"][0]["value"], 4)
        self.assertEqual(result["chart"]["data"][0]["source"], "Experience requests")
        self.assertEqual(source_label("xp__request"), "Experience requests")
        self.assertEqual(source_label("tournament"), "League rounds")

    def test_exposure_is_compact_and_has_no_round_bars(self):
        result = exposure([], [], [], {}, [], 100, 3)
        self.assertIsNone(result["chart"])
        self.assertIn("Median games per player per completed round", [r[0] for r in result["rows"]])
        self.assertLessEqual(len(result["rows"]), 10)
