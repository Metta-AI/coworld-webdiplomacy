"""Pure-logic tests for fetch_league: which episodes are taken, where they land, what is saved.
No network: the `coworld` listing and the downloader are stand-ins."""

import json
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401  (puts the tools folder on sys.path)
import fetch_league
from webdip_episodes import episode_dirs

LEAGUE = {"id": "league_x", "key": "press"}
ROUND = {"id": "round_a", "round_number": 3}


def episode(ereq="ereq_1", status="completed"):
    seats = [("ours", 2, "id-ours", 0), ("filler", 1, "id-filler", 1)]
    return {"id": ereq, "status": status, "round_id": "round_a",
            "participants": [{"policy_name": name, "version": version, "label": f"{name}:v{version}",
                              "policy_version_id": pvid, "position": pos} for name, version, pvid, pos in seats]}


class FakeGet:
    """Stands in for `download`: serves episode artifacts and our own seat's log, 403s the rest."""

    def __init__(self):
        self.paths = []

    def __call__(self, token, path, dest, add_suffix=False):
        self.paths.append(path)
        if "id-filler" in path or path.endswith("/policy-artifact/0"):
            return False
        if add_suffix:
            dest = dest.with_name(dest.name + ".json")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("{}")
        return True


class SeatsPolicy(unittest.TestCase):
    def test_matches_name_label_and_version_id(self):
        for ref in ("ours", "ours:v2", "id-ours", None):
            self.assertTrue(fetch_league.seats_policy(episode(), ref), ref)
        for ref in ("ours:v1", "our", "id-other"):
            self.assertFalse(fetch_league.seats_policy(episode(), ref), ref)

    def test_a_row_without_labels_still_matches_name_and_version(self):
        row = {"participants": [{"policy_name": "ours", "version": 2, "policy_version_id": "id-ours"}]}
        self.assertTrue(fetch_league.seats_policy(row, "ours:v2"))


class Listing(unittest.TestCase):
    def test_walks_rounds_then_episodes_then_the_full_row(self):
        calls = []

        def coworld(*args):
            calls.append(args)
            if args[0] == "rounds":
                return [ROUND]
            if args[1] == "-r":
                return [{"id": "ereq_1"}]
            return episode(args[1])

        found = list(fetch_league.league_episodes("league_x", 5, coworld))
        self.assertEqual(found, [(ROUND, episode())])
        self.assertEqual(calls, [("rounds", "-l", "league_x", "--limit", "5"), ("episodes", "-r", "round_a"),
                                 ("episodes", "ereq_1")])

    def test_league_key(self):
        self.assertEqual(fetch_league.league_key("press")["id"], fetch_league.field.LEAGUES["press"])
        self.assertEqual(fetch_league.league_key(fetch_league.field.LEAGUES["gunboat"])["key"], "gunboat")
        self.assertEqual(fetch_league.league_key("league_other"), {"id": "league_other", "key": "league_other"})


class FetchEpisode(unittest.TestCase):
    def test_saves_the_layout_the_loader_reads_and_marks_the_league(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, get = Path(tmp) / "league-press", FakeGet()
            self.assertEqual(fetch_league.fetch_episode(episode(), ROUND, LEAGUE, out, get=get), "fetched")
            ep_dir = out / "round-0003" / "ereq_1"
            self.assertEqual(sorted(p.name for p in ep_dir.iterdir()),
                             [".done", "episode.json", "game.log", "policy-logs", "replay.json", "results.json"])
            self.assertEqual([p.name for p in (ep_dir / "policy-logs").iterdir()], ["id-ours.0.log"])
            saved = json.loads((ep_dir / "episode.json").read_text())
            self.assertEqual(saved["round_id"], "round_a")  # the league marker the loader reads
            self.assertEqual(saved["league_round"], {"league_id": "league_x", "league": "press",
                                                     "round_id": "round_a", "round_number": 3})
            self.assertEqual(episode_dirs(out), [ep_dir])

    def test_a_finished_episode_is_not_fetched_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, get = Path(tmp), FakeGet()
            fetch_league.fetch_episode(episode(), ROUND, LEAGUE, out, get=get)
            before = len(get.paths)
            self.assertEqual(fetch_league.fetch_episode(episode(), ROUND, LEAGUE, out, get=get), "have")
            self.assertEqual(len(get.paths), before)

    def test_an_episode_whose_downloads_all_fail_is_not_marked_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self.assertEqual(fetch_league.fetch_episode(episode(), ROUND, LEAGUE, out, get=lambda *a, **k: False),
                             "empty")
            self.assertFalse((out / "round-0003" / "ereq_1" / ".done").exists())
            # The next run tries again, and a run that gets the files marks it.
            self.assertEqual(fetch_league.fetch_episode(episode(), ROUND, LEAGUE, out, get=FakeGet()), "fetched")
            self.assertTrue((out / "round-0003" / "ereq_1" / ".done").exists())

    def test_a_running_episode_is_left_for_the_next_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            get = FakeGet()
            state = fetch_league.fetch_episode(episode(status="running"), ROUND, LEAGUE, Path(tmp), get=get)
            self.assertEqual(state, "running")
            self.assertEqual(get.paths, [])
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_skip_leaves_an_artifact_type_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            get = FakeGet()
            fetch_league.fetch_episode(episode(), ROUND, LEAGUE, Path(tmp), frozenset({"replay"}), get=get)
            self.assertFalse(any(path.endswith("/artifacts/replay") for path in get.paths))
            self.assertTrue(any(path.endswith("/artifacts/results") for path in get.paths))


if __name__ == "__main__":
    unittest.main()
