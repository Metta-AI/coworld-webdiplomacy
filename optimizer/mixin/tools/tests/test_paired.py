import math
import statistics
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401  (puts the tools folder on sys.path)
import paired
from helpers import FIXTURES, write_episode
from webdip_episodes import load_dirs

COUNTRIES = [1, 2, 3, 4, 5, 6, 7]  # slot k plays country k+1: England, France, Italy, ...


class PairedDifference(unittest.TestCase):
    def build(self, tmp, games, logs_by_game=None):
        for i, (seating, scores) in enumerate(games):
            write_episode(Path(tmp) / f"g{i}", scores, COUNTRIES, [3] * 7, seating=seating,
                          logs=(logs_by_game or {}).get(i))
        return load_dirs([Path(tmp)])[0]

    def test_hand_computed_difference_and_z(self):
        field = ["f"] * 5
        games = [
            (["A", "B", *field], [0.30, 0.10, 0.12, 0.12, 0.12, 0.12, 0.12]),
            (["B", "A", *field], [0.20, 0.25, 0.11, 0.11, 0.11, 0.11, 0.11]),
            (["A", "B", *field], [0.20, 0.20, 0.12, 0.12, 0.12, 0.12, 0.12]),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            seats = self.build(tmp, games)
        # No field seat played England or France, so par falls back to every seat there.
        par = {"England": statistics.mean([0.30, 0.20, 0.20]), "France": statistics.mean([0.10, 0.25, 0.20])}
        diffs = [
            (0.30 - par["England"]) - (0.10 - par["France"]),
            (0.25 - par["France"]) - (0.20 - par["England"]),
            (0.20 - par["England"]) - (0.20 - par["France"]),
        ]
        report = paired.paired_report(seats, "A", "B")
        mean = statistics.mean(diffs)
        se = statistics.stdev(diffs) / math.sqrt(3)
        self.assertEqual(report["n"], 3)
        self.assertAlmostEqual(report["diff"], round(mean, 4))
        self.assertAlmostEqual(report["se"], round(se, 4))
        self.assertAlmostEqual(report["z"], round(mean / se, 2))
        self.assertEqual(report["diff_by_a_power"]["England"]["n"], 2)

    def test_tainted_games_are_dropped(self):
        games = [(["A", "B", *["f"] * 5], [0.2, 0.1, 0.14, 0.14, 0.14, 0.14, 0.14])] * 3
        logs = {1: {0: [{"event": "exception", "error": "boom"}]}}
        with tempfile.TemporaryDirectory() as tmp:
            seats = self.build(tmp, games, logs)
        self.assertEqual(paired.paired_report(seats, "A", "B")["dropped_tainted"], 1)
        self.assertEqual(paired.paired_report(seats, "A", "B")["n"], 2)
        self.assertEqual(paired.paired_report(seats, "A", "B", keep_tainted=True)["n"], 3)

    def test_verdict_wording(self):
        self.assertEqual(paired.verdict(1, None, "A", "B"), "no result (n < 2)")
        self.assertEqual(paired.verdict(40, 1.99, "A", "B"), "no result (|z| < 2)")
        self.assertEqual(paired.verdict(40, -2.5, "A", "B"), "B ahead")
        self.assertEqual(paired.verdict(40, 2.0, "A", "B"), "A ahead")

    def test_real_local_fixture(self):
        seats, _ = load_dirs([FIXTURES / "local"])
        report = paired.paired_report(seats, "kissinger:SEARCH_OBJECTIVE=share", "kissinger")
        self.assertEqual(report["n"], 3)
        self.assertTrue(report["verdict"].startswith("no result"))


if __name__ == "__main__":
    unittest.main()
