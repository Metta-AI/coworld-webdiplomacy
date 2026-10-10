import unittest

import _path  # noqa: F401  (puts the tools folder on sys.path)
import ab_stats

# Reference values computed with scipy 1.x (the engine this module replaces).
A = [0.1, 0.05, 0.2, 0.0, 0.15, 0.08]
B = [0.31, 0.12, 0.0, 0.22, 0.4]


class Tests(unittest.TestCase):
    def test_welch_matches_scipy(self):
        t, p = ab_stats.welch_t(A, B)  # scipy.stats.ttest_ind(B, A, equal_var=False)
        self.assertAlmostEqual(t, 1.4927219991835616, places=10)
        self.assertAlmostEqual(p, 0.19182933908609595, places=10)

    def test_fisher_matches_scipy(self):
        self.assertAlmostEqual(ab_stats.fisher_exact_p(3, 7, 9, 2), 0.02997312285237981, places=12)
        self.assertAlmostEqual(ab_stats.fisher_exact_p(5, 5, 5, 5), 1.0)

    def test_by_correction_matches_scipy(self):
        got = ab_stats.benjamini_yekutieli([0.01, 0.04, 0.03, 0.2])
        for x, y in zip(got, [0.08333333, 0.11111111, 0.11111111, 0.41666667]):
            self.assertAlmostEqual(x, y, places=7)

    def test_t_distribution_limits(self):
        self.assertAlmostEqual(ab_stats.t_two_sided_p(0.0, 10), 1.0)
        self.assertAlmostEqual(ab_stats.t_two_sided_p(1.96, float("inf")), 0.04999579, places=6)
        self.assertAlmostEqual(ab_stats.t_two_sided_p(2.228138852, 10), 0.05, places=6)


class Verdicts(unittest.TestCase):
    def delta(self, n, z, p, base=0.1, cand=0.2):
        d = ab_stats.Delta("score", "all", True, base, cand, n, n, "mean")
        d.raw_p, d.z = p, z
        ab_stats.apply_correction([d])
        return d.verdict

    def test_floors(self):
        self.assertEqual(self.delta(40, 3.0, 0.001), "improved")
        self.assertEqual(self.delta(40, 3.0, 0.001, base=0.2, cand=0.1), "regressed")
        self.assertEqual(self.delta(29, 3.0, 0.001), "no result")  # below the n floor
        self.assertEqual(self.delta(40, 1.9, 0.01), "no result")  # |z| < 2
        self.assertEqual(self.delta(40, 3.0, 0.2), "no result")  # p too large

    def test_render_says_no_result(self):
        d = ab_stats.Delta("score", "all", True, 0.1, 0.12, 5, 5, "mean")
        ab_stats.apply_correction([d])
        text = ab_stats.render_markdown("a", "b", {"all": [1] * 5}, {"all": [1] * 5}, [d], "score", ["all"],
                                        [("score", True, "mean", None)])
        self.assertIn("no result", text)
        self.assertIn("Small sample", text)


if __name__ == "__main__":
    unittest.main()
