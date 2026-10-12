"""Reading games for the dashboard and the replay index (`webdip_ide/reader.py`) on a small synthetic lab."""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from lab_source import lab_source

MIXIN = lab_source()
sys.path.insert(0, str(MIXIN / "tools" / "tests"))
from helpers import write_episode  # noqa: E402

COUNTRIES = [1, 2, 3, 4, 5, 6, 7]
SEATING = ["mine:v1", "rival-a:v1", "rival-a:v1", "rival-b:v2", "rival-b:v2", "rival-c:v1", "rival-c:v1"]


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.lab = Path(tempfile.mkdtemp(prefix="webdip-ide-test-"))
        self.addCleanup(shutil.rmtree, self.lab, ignore_errors=True)
        (self.lab / "tools").symlink_to(MIXIN / "tools")
        self.artifacts = self.lab / ".runtime" / "artifacts"
        self.artifacts.mkdir(parents=True)
        previous = os.environ.get("WEBDIP_LAB")
        os.environ["WEBDIP_LAB"] = str(self.lab)
        self.addCleanup(lambda: os.environ.pop("WEBDIP_LAB") if previous is None
                        else os.environ.__setitem__("WEBDIP_LAB", previous))  # fmt: skip
        from webdip_ide import episodes, reader, routes_dashboard

        self.episodes, self.reader, self.dashboard = episodes, reader, routes_dashboard
        episodes._basic.clear()
        self.games = [
            write_episode(self.artifacts / "xreq_press" / f"ereq_{number:03d}", [0.4] + [0.1] * 6, COUNTRIES,
                          [5] + [4] * 6, seating=SEATING, status="completed", logs={0: [{"event": "decision"}]})
            for number in (1, 2, 3)
        ]  # fmt: skip

    def todo(self) -> dict:
        return {ep: self.reader.fingerprint(ep) for ep in self.games}

    def count_parses(self) -> list[str]:
        """Every episode directory parsed from now on, in order."""
        parsed = []
        original = self.reader.load_game

        def counted(tools, ep):
            parsed.append(Path(ep).name)
            return original(tools, ep)

        self.reader.load_game = counted
        self.addCleanup(setattr, self.reader, "load_game", original)
        return parsed

    def test_fingerprint_of_a_directory_that_is_going_away(self):
        ep = self.games[0]
        (ep / "dangling.log").symlink_to(ep / "no-such-file")  # as a file removed mid-scan looks
        self.assertNotIn("dangling.log", [item[1] for item in self.reader.fingerprint(ep)])
        self.assertEqual(self.reader.fingerprint(ep / "removed"), ())

    def test_a_large_batch_is_read_in_worker_processes(self):
        self.addCleanup(setattr, self.reader, "POOL_MIN", self.reader.POOL_MIN)
        self.reader.POOL_MIN = 2
        games = self.reader.each_game(self.todo())
        read = [next(games)]
        self.assertIsNotNone(self.reader._pool)  # worker processes are doing the parsing
        read += list(games)
        self.assertEqual([ep for ep, _, _ in read], self.games)
        for ep, game, error in read:
            self.assertIsNone(error)
            self.assertEqual((game.episode, len(game.seats), game.seats[0].policy), (ep.name, 7, "mine:v1"))
        self.assertIsNone(self.reader._pool)  # the workers are stopped when the batch is done

    def test_an_unreadable_game_is_reported_and_the_rest_are_read(self):
        (self.games[1] / "results.json").write_text("{not json")
        read = list(self.reader.each_game(self.todo()))
        self.assertEqual([game is not None for _, game, _ in read], [True, False, True])
        self.assertIn("JSONDecodeError", read[1][2])

    def test_the_dashboard_and_the_index_share_one_parse_of_a_game(self):
        parsed = self.count_parses()
        self.dashboard.CACHE.sync(60)
        self.assertEqual(self.episodes.deepen(wait=True), (3, 3))
        self.assertEqual(sorted(parsed), ["ereq_001", "ereq_002", "ereq_003"])
        row = next(row for row in self.episodes.index() if row["id"] == "ereq_001")
        self.assertTrue(row["indexed"])
        self.assertEqual(row["seats"][0]["log"]["decisions"], 1)  # the deep row has what the log says

        # A file of one game changes: both read it again, once between them.
        path = self.games[0] / "episode.json"
        os.utime(path, (path.stat().st_atime, path.stat().st_mtime + 5))
        self.assertEqual(self.dashboard.CACHE.sync(60)[1], 0)
        self.assertEqual(self.episodes.deepen(wait=True), (3, 3))
        self.assertEqual(parsed[3:], ["ereq_001"])


if __name__ == "__main__":
    unittest.main()
