import argparse
import gzip
import json
import os
import statistics
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _path  # noqa: F401  (puts the tools folder on sys.path)
import wd
from helpers import FIXTURES, write_episode
from webdip_episodes import load_dirs


class Metrics(unittest.TestCase):
    def test_par_is_the_mean_of_non_target_seats_at_that_power(self):
        seats, statuses = load_dirs([FIXTURES / "local"])
        report = wd.metrics_report(seats, statuses, policy="kissinger")
        field = [s for s in seats if s.policy != "kissinger"]
        for power in ("France", "Italy", "Turkey"):
            expected = statistics.mean(s.score for s in field if s.power == power)
            self.assertAlmostEqual(report["field_par_per_power"][power]["score"], round(expected, 4))
        target = [s for s in seats if s.policy == "kissinger"]
        par = {p: statistics.mean(s.score for s in field if s.power == p) for p in {s.power for s in target}}
        rel = statistics.mean(s.score - par[s.power] for s in target)
        self.assertAlmostEqual(report["overall"]["score_minus_field_par"], round(rel, 4))
        self.assertEqual(report["overall"]["n"], 3)

    def test_tainted_target_episode_is_dropped_unless_kept(self):
        seats, statuses = load_dirs([FIXTURES / "hosted"])
        dropped = wd.metrics_report(seats, statuses, policy="webdip-calhamer:v1")
        self.assertEqual(dropped["overall"]["n"], 0)
        self.assertEqual(dropped["taint"], {"target_seat_flags": {"exception": 1}, "episodes_dropped": 1,
                                            "kept_tainted": False})
        kept = wd.metrics_report(seats, statuses, policy="webdip-calhamer:v1", keep_tainted=True)
        self.assertEqual(kept["overall"]["n"], 1)
        self.assertEqual(kept["telemetry"]["exceptions"], 1)

    def test_slot_target(self):
        seats, statuses = load_dirs([FIXTURES / "local"])
        report = wd.metrics_report(seats, statuses, slot=0)
        self.assertEqual(report["overall"]["n"], 3)
        self.assertEqual(report["policy"], "slot 0")

    def test_cli_exit_code_without_target(self):
        with mock.patch("sys.stdout"):
            self.assertEqual(wd.main(["metrics", str(FIXTURES / "local"), "--policy", "nobody"]), 2)


class Seats(unittest.TestCase):
    def test_one_json_row_per_seat_with_trajectory(self):
        with mock.patch("builtins.print") as printed:
            wd.main(["seats", str(FIXTURES / "hosted/xreq_fixture/ereq_press")])
        rows = [json.loads(call.args[0]) for call in printed.call_args_list]
        self.assertEqual(len(rows), 7)
        england = next(r for r in rows if r["power"] == "England")
        self.assertEqual(england["centers_by_year"]["1908"], 8)
        self.assertEqual(sorted(england["centers_by_year"]), [str(y) for y in range(1901, 1909)])


class Costs(unittest.TestCase):
    def test_costs_from_llm_call_events(self):
        report = wd.costs_report([FIXTURES])
        self.assertEqual(report["summary"]["games"], 1)
        seat = report["games"][0]["seats"][0]
        self.assertEqual((seat["slot"], seat["calls"], seat["failed_calls"]), (3, 6, 0))
        self.assertAlmostEqual(seat["cost_usd"], 0.001525, places=6)
        self.assertEqual(seat["movement_phases"], 16)

    def test_no_llm_calls(self):
        self.assertIsNone(wd.costs_report([FIXTURES / "local"]))


class Slim(unittest.TestCase):
    def test_drops_map_pngs_and_keeps_gzip(self):
        with tempfile.TemporaryDirectory() as tmp:
            ep = write_episode(Path(tmp) / "g", [1 / 7] * 7, list(range(1, 8)), [3] * 7)
            frames = [{"game": {"turn": t}, "map": "data:image/png;base64," + "A" * 5000} for t in range(3)]
            (ep / "replay").write_bytes(gzip.compress(json.dumps(frames).encode()))
            with mock.patch("builtins.print"):
                wd.main(["slim", tmp])
            data = (ep / "replay").read_bytes()
            self.assertEqual(data[:2], b"\x1f\x8b")
            slimmed = json.loads(gzip.decompress(data))
            self.assertEqual(slimmed, [{"game": {"turn": t}} for t in range(3)])
            self.assertEqual(wd.slim_replay(ep / "replay"), 0)  # idempotent


class LocalRunHelpers(unittest.TestCase):
    MANIFEST = {"game": {"version": "0.7.8", "config_schema": {"properties": {"seed": {}}}},
                "variants": [{"id": "classic-gunboat", "game_config": {"press": "NoPress", "end_year": 1910}}],
                "player": [{"id": "random", "image": "img:downloaded", "run": [], "env": {}}]}

    def args(self, **kw):
        base = {"variant": "classic-gunboat", "maps": False, "config": None, "country": None}
        return argparse.Namespace(**{**base, **kw})

    def test_game_config_from_variant_with_overrides(self):
        config = wd.game_config(self.MANIFEST, self.args(config=["end_year=1904", "seed=5"]))
        self.assertEqual(config, {"press": "NoPress", "end_year": 1904, "render_maps": False})

    def test_country_needs_schema_support(self):
        with self.assertRaises(wd.SetupError):
            wd.game_config(self.MANIFEST, self.args(country="France"))
        manifest = json.loads(json.dumps(self.MANIFEST))
        manifest["game"]["config_schema"]["properties"]["countries"] = {}
        config = wd.game_config(manifest, self.args(country="france"))
        self.assertEqual(config["countries"][0], 2)
        self.assertEqual(sorted(config["countries"]), list(range(1, 8)))

    def test_player_spec_and_bundled_player(self):
        spec = wd.player_spec("img:1", "/opt/.venv/bin/python -m players.launcher sh -c 'a b'", {"K": "v"})
        self.assertEqual(spec["run"], ["/opt/.venv/bin/python", "-m", "players.launcher", "sh", "-c", "a b"])
        self.assertEqual(wd.player_spec("img:1", None, {})["run"], [])
        self.assertEqual(wd.bundled_player(self.MANIFEST, "random")["image"], "img:downloaded")
        with self.assertRaises(wd.SetupError):
            wd.bundled_player(self.MANIFEST, "dumbbot")

    def test_missing_coworld_cli_explains_install(self):
        with mock.patch.dict(os.environ, {"PATH": "", "COWORLD_CMD": ""}):
            with self.assertRaises(wd.SetupError) as raised:
                wd.coworld_command()
        self.assertIn("uv tool install coworld", str(raised.exception))
        self.assertIn("softmax-cli", str(raised.exception))
        with mock.patch.dict(os.environ, {"COWORLD_CMD": "uv run coworld"}):
            self.assertEqual(wd.coworld_command(), ["uv", "run", "coworld"])


if __name__ == "__main__":
    unittest.main()
