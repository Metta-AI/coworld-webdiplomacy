import statistics
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401  (puts the tools folder on sys.path)
import compare
from helpers import FIXTURES, write_episode


class CompareGrouping(unittest.TestCase):
    def test_groups_are_all_plus_each_power(self):
        base, cand, deltas = compare.compare(FIXTURES / "local", FIXTURES / "local",
                                             "kissinger", "kissinger:SEARCH_OBJECTIVE=share")
        self.assertEqual(compare.GROUPS,
                         ["all", "England", "France", "Italy", "Germany", "Austria", "Turkey", "Russia"])
        self.assertEqual(len(base["all"]), 3)
        self.assertEqual(sorted(s.power for s in base["all"]), ["France", "Italy", "Turkey"])
        self.assertEqual(sorted(s.power for s in cand["all"]), ["Austria", "Italy", "Russia"])
        self.assertEqual(len(base["France"]), 1)
        groups = {(d.metric, d.group) for d in deltas}
        self.assertIn(("score_vs_par", "Italy"), groups)
        self.assertIn(("taint_rate", "episodes"), groups)
        self.assertNotIn(("taint_rate", "all"), groups)
        # n = 3 per side is under the 30 floor: never a directional verdict.
        self.assertTrue(all(d.verdict in ("no result", "n/a") for d in deltas))

    def test_score_vs_par_uses_one_shared_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            base_dir, cand_dir = Path(tmp) / "base", Path(tmp) / "cand"
            for i in range(2):
                write_episode(base_dir / f"g{i}", [0.1, 0.2, 0.1, 0.1, 0.1, 0.2, 0.2], [1, 2, 3, 4, 5, 6, 7],
                              [3] * 7, seating=["base", *["f"] * 6])
                write_episode(cand_dir / f"g{i}", [0.3, 0.1, 0.1, 0.1, 0.1, 0.1, 0.2], [1, 2, 3, 4, 5, 6, 7],
                              [3] * 7, seating=["cand", *["f"] * 6])
            # England is only ever played by the target seats, so add field England seats.
            write_episode(base_dir / "g9", [0.05, 0.2, 0.1, 0.1, 0.15, 0.2, 0.2], [1, 2, 3, 4, 5, 6, 7], [3] * 7,
                          seating=["f", "base", *["f"] * 5])
            base, cand, deltas = compare.compare(base_dir, cand_dir, "base", "cand")
        by = {(d.metric, d.group): d for d in deltas}
        england_par = 0.05  # the only non-target England seat across both batches
        self.assertAlmostEqual(by[("score_vs_par", "England")].base, 0.1 - england_par)
        self.assertAlmostEqual(by[("score_vs_par", "England")].cand, 0.3 - england_par)
        france_par = statistics.mean([0.2, 0.2, 0.1, 0.1])  # field France seats in both batches
        self.assertAlmostEqual(by[("score_vs_par", "France")].base, 0.2 - france_par)

    def test_tainted_episodes_are_dropped_and_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_episode(root / "ok", [1 / 7] * 7, [1, 2, 3, 4, 5, 6, 7], [3] * 7, seating=["me", *["f"] * 6])
            write_episode(root / "bad", [1 / 7] * 7, [1, 2, 3, 4, 5, 6, 7], [3] * 7, seating=["me", *["f"] * 6],
                          logs={0: [{"event": "decision", "rejected": 1}]})
            write_episode(root / "cancelled", [1 / 7] * 7, [1, 2, 3, 4, 5, 6, 7], [3] * 7, outcome="cancelled",
                          seating=["me", *["f"] * 6])
            kept, field, episodes = compare.load_batch(root, "me")
            self.assertEqual(len(kept), 1)
            self.assertEqual(sum(e["taint"] for e in episodes), 2)
            self.assertEqual(len(compare.load_batch(root, "me", keep_tainted=True)[0]), 3)


if __name__ == "__main__":
    unittest.main()
