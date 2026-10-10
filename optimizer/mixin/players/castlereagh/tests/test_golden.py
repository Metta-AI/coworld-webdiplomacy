"""The golden behaviour contract: 334 recorded lab decisions, reproduced bit for bit.

Takes about a minute. Set GOLDEN_EVERY=N to check every Nth case while iterating."""

import os
import unittest

import _support  # noqa: F401  (import path)
from castlereagh import golden


class GoldenTest(unittest.TestCase):
    def test_search_reproduces_the_lab_corpus(self):
        every = int(os.environ.get("GOLDEN_EVERY", "1"))
        checked, mismatches = golden.check(str(_support.GOLDEN), lambda i: i % every == 0)
        self.assertGreater(checked, 0)
        self.assertEqual(mismatches, [], f"{len(mismatches)} of {checked} decisions changed")


if __name__ == "__main__":
    unittest.main()
