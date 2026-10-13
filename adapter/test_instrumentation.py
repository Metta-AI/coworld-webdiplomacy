"""Ready timing stays private until the game ends; timing and seat health reach the results."""

import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jsonschema import validate

from adapter.config import EpisodeConfig
from adapter.episode import Episode, TimingProfile

SECRETS = ("Ready", "Saved", "order_status", "first_ready", "api_requests")


class Instrumentation(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.directory)
        created = {"ok": True, "game_id": 1, "seats": []}
        config = EpisodeConfig(tokens=list("abcdefg"), countries=[3, 1, 2, 7, 6, 5, 4], render_maps=False)
        with patch("adapter.episode.php", return_value=created), patch.object(Episode, "tick"):
            self.episode = Episode(config)
        environment = patch.dict(
            "os.environ",
            COGAME_RESULTS_URI=(self.directory / "results.json").as_uri(),
            COGAME_SAVE_REPLAY_URI=(self.directory / "replay.json").as_uri(),
        )
        environment.start()
        self.addCleanup(environment.stop)

    def state(self, turn, phase, order_status, process_time="1700000600"):
        """A `wdc_state` result whose public game file matches the committed phase."""
        board = self.directory / f"game-{turn}-{phase}.json"
        board.write_text(json.dumps({"version": 1, "turn": turn, "phase": phase}))
        game = {
            "id": "1",
            "turn": str(turn),
            "phase": phase,
            "gameOver": "Drawn" if phase == "Finished" else "No",
            "processStatus": "Not-processing",
            "processTime": process_time,
            "startTime": "1700000000",
        }
        countries = range(1, 8)
        return {
            "ok": True,
            "game": game,
            "members": [
                {"countryID": str(c), "status": "Playing", "supplyCenterNo": "3", "unitNo": "3"} for c in countries
            ],
            "private_activity": [
                {"countryID": str(c), "order_status": order_status.get(c, ""), "api_requests": 10 * c}
                for c in countries
            ],
            # An absolute URL replaces /application when joined, so the test reads its own file.
            "files": {"game": {"url": str(board), "version": 1}},
        }

    def tick(self, state, at):
        """Run one tick `at` seconds after game creation; return what it printed."""
        output = io.StringIO()
        with (
            patch("adapter.episode.php", return_value=state),
            patch("adapter.episode.time.monotonic", return_value=self.episode.created_at + at),
            contextlib.redirect_stdout(output),
        ):
            self.episode.tick()
        return output.getvalue()

    def test_first_saved_and_ready_are_sampled_per_phase(self):
        self.tick(self.state(0, "Diplomacy", {3: "Saved", 1: "None"}), at=10)
        self.tick(self.state(0, "Diplomacy", {3: "Saved,Completed,Ready", 2: "Completed", 1: "None"}), at=12.5)
        self.tick(self.state(0, "Diplomacy", {3: "Saved", 1: "None"}), at=14)  # Unready later: first Ready stays.
        self.tick(self.state(0, "Retreats", {2: "Ready"}), at=20)
        diplomacy, retreats = self.episode.seat_activity()["phases"]
        self.assertEqual((diplomacy["turn"], diplomacy["phase"]), (0, "Diplomacy"))
        # Slot 0 is country 3, slot 1 is country 1 (no orders to give), slot 2 is country 2.
        self.assertEqual(diplomacy["seats"][0], {"first_saved_seconds": 0.0, "first_ready_seconds": 2.5})
        self.assertIsNone(diplomacy["seats"][1])
        self.assertEqual(diplomacy["seats"][2], {"first_saved_seconds": 2.5, "first_ready_seconds": None})
        self.assertEqual(diplomacy["seats"][3], {"first_saved_seconds": None, "first_ready_seconds": None})
        self.assertEqual(retreats["seats"][2], {"first_saved_seconds": None, "first_ready_seconds": 0.0})

    def test_order_status_is_published_only_once_the_game_ends(self):
        everyone_ready = {c: "Saved,Completed,Ready" for c in range(1, 8)}
        printed = self.tick(self.state(0, "Diplomacy", everyone_ready), at=5)
        printed += self.tick(self.state(0, "Diplomacy", everyone_ready), at=6)
        live = json.dumps([self.episode.frames, self.episode.public])
        for text in (printed, live):
            for secret in SECRETS:
                self.assertNotIn(secret, text)
        after = [json.loads(line) for line in self.tick(self.state(1, "Finished", {}), at=30).splitlines()]
        self.assertEqual([line["event"] for line in after], ["phase", "seat_activity", "game_over"])
        self.assertEqual(after[1]["phases"][0]["seats"][0], {"first_saved_seconds": 0.0, "first_ready_seconds": 0.0})
        self.assertNotIn("phases", after[2]["gamemaster_calls"])
        replay = (self.directory / "replay.json").read_text()
        results = (self.directory / "results.json").read_text()
        for text in (replay, results, json.dumps(self.episode.public)):
            self.assertNotIn("Ready", text)
            self.assertNotIn("order_status", text)

    def test_results_carry_timing_seat_health_and_phase_deadlines(self):
        with self.episode.lock:
            self.episode.record_connection(0, connected=True)
        self.tick(self.state(0, "Diplomacy", {}), at=5)
        with self.episode.lock:
            self.episode.record_connection(0, connected=False)
            self.episode.record_connection(0, connected=True)
        self.episode.timing.lap("player_connect_wait")
        self.tick(self.state(1, "Finished", {}, process_time=None), at=30)
        results = json.loads((self.directory / "results.json").read_text())
        manifest = json.loads(Path("coworld_manifest_template.json").read_text())
        validate(results, manifest["game"]["results_schema"])
        self.assertEqual(
            results["members"][0], {"countryID": "1", "status": "Playing", "supplyCenterNo": "3", "unitNo": "3"}
        )
        self.assertEqual(results["transitions"][0]["deadline_unix_time"], 1700000600)
        self.assertIsNone(results["transitions"][1]["deadline_unix_time"])
        health = results["seat_health"]
        self.assertEqual([seat["slot"] for seat in health], list(range(7)))
        self.assertEqual([event["event"] for event in health[0]["connections"]], ["connect", "disconnect", "reconnect"])
        self.assertEqual(health[1]["connections"], [])
        # API request counts follow slot order: slot 0 is country 3.
        self.assertEqual([seat["api_requests"] for seat in health], [30, 10, 20, 70, 60, 50, 40])
        self.assertEqual(
            list(results["timing"]), ["player_connect_wait_seconds", "play_seconds", "replay_write_seconds"]
        )
        self.assertIn("results_write_seconds", self.episode.timing.stages)
        phases = [phase["phase"] for phase in results["gamemaster_calls"]["phases"]]
        self.assertEqual(phases, ["Diplomacy", "Finished"])

    def test_gamemaster_calls_are_grouped_by_the_phase_they_started_in(self):
        self.episode.transitions = [
            {"turn": 0, "phase": "Pre-game", "unix_time": 100.0},
            {"turn": 0, "phase": "Diplomacy", "unix_time": 110.0},
            {"turn": 0, "phase": "Diplomacy", "unix_time": 111.0},  # Only the process status changed.
            {"turn": 0, "phase": "Retreats", "unix_time": 170.0},
        ]
        log = self.directory / "gamemaster-timing.log"
        # `$msec $request_time $status`: the first call ends at 109.5 after 0.2 s, so it started in Pre-game.
        log.write_text("109.500 0.200 200\n120.000 0.050 200\n169.900 2.500 200\n175.000 0.100 502\nbad line\n")
        calls = self.episode.gamemaster_calls(log)
        self.assertEqual((calls["count"], calls["max_seconds"], calls["http_errors"]), (4, 2.5, 1))
        self.assertEqual(
            calls["phases"],
            [
                {"turn": 0, "phase": "Pre-game", "count": 1, "max_seconds": 0.2},
                {"turn": 0, "phase": "Diplomacy", "count": 2, "max_seconds": 2.5},
                {"turn": 0, "phase": "Retreats", "count": 1, "max_seconds": 0.1},
            ],
        )

    def test_timing_profile_laps_are_consecutive(self):
        with patch("adapter.episode.time.monotonic", side_effect=[10.0, 12.5, 12.75]):
            profile = TimingProfile()
            profile.lap("storage")
            profile.lap("services")
        self.assertEqual(profile.stages, {"storage_seconds": 2.5, "services_seconds": 0.25})


if __name__ == "__main__":
    unittest.main()
