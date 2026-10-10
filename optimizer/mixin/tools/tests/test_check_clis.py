import unittest

import _path  # noqa: F401  (puts the tools folder on sys.path)
import check_clis

LISTING = """coworld v0.1.38.post1.dev750
- coworld
softmax-cli v0.26.39
- softmax
ruff v0.6.0
- ruff
"""


class Tests(unittest.TestCase):
    def test_parse_tool_list(self):
        self.assertEqual(
            check_clis.parse_tool_list(LISTING),
            {"coworld": "0.1.38.post1.dev750", "softmax-cli": "0.26.39", "ruff": "0.6.0"},
        )

    def test_dev_build_of_older_release_is_stale(self):
        found = check_clis.problems(
            check_clis.parse_tool_list(LISTING), {"coworld": "0.1.58", "softmax-cli": "0.26.39"}
        )
        self.assertEqual(len(found), 1)
        self.assertIn("`coworld` is 0.1.38.post1.dev750; the latest release is 0.1.58", found[0])

    def test_current_tools_report_nothing(self):
        installed = {"coworld": "0.1.58", "softmax-cli": "0.26.39"}
        self.assertEqual(check_clis.problems(installed, {"coworld": "0.1.58", "softmax-cli": "0.26.39"}), [])

    def test_missing_tool_and_unreachable_pypi(self):
        found = check_clis.problems({"coworld": "0.1.58"}, {"coworld": None, "softmax-cli": None})
        self.assertEqual(found, ["`softmax` is not installed as a uv tool. Fix: uv tool install softmax-cli"])

    def test_release_tuple(self):
        self.assertLess(check_clis.release_tuple("0.1.9"), check_clis.release_tuple("0.1.10"))
        self.assertEqual(check_clis.release_tuple("0.1.38.post1.dev750"), (0, 1, 38))


if __name__ == "__main__":
    unittest.main()
