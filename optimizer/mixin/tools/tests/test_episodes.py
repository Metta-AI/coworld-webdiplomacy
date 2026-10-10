import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401  (puts the tools folder on sys.path)
import webdip_episodes as we
from helpers import FIXTURES, write_episode

PRESS = FIXTURES / "hosted/xreq_fixture/ereq_press"
GUNBOAT = FIXTURES / "hosted/xreq_fixture/ereq_gunboat"


def seat(seats, slot):
    return next(s for s in seats if s.slot == slot)


class LoaderLayouts(unittest.TestCase):
    def test_finds_every_episode_below_a_root(self):
        seats, statuses = we.load_dirs([FIXTURES])
        self.assertEqual(len(statuses), 5)
        self.assertEqual(len(seats), 35)
        self.assertTrue(all(not st["missing"] for st in statuses))

    def test_hosted_fetch_artifacts_layout(self):
        seats, status = we.load_episode(PRESS)
        self.assertEqual(status["episode_status"], "completed")
        self.assertEqual(status["coworld_version"], "0.7.7")
        self.assertEqual(seat(seats, 3).policy, "webdip-castlereagh-press:v1")
        self.assertEqual(seat(seats, 3).power, "France")  # results.countries[3] == 2
        self.assertEqual(seat(seats, 3).log["llm_calls"], 6)  # read from policy-logs/<pvid>.3.log

    def test_gzip_replay_named_bin(self):
        seats, status = we.load_episode(GUNBOAT)
        self.assertNotIn("replay", status["missing"])
        self.assertEqual(seat(seats, 0).centers_by_year[1901], 3)
        self.assertGreater(seat(seats, 0).orders, 0)

    def test_local_layout_uses_seating_labels(self):
        seats, status = we.load_episode(FIXTURES / "local/g-011287fb8a")
        self.assertEqual(status["episode_status"], "local")
        self.assertEqual(seat(seats, 0).policy, "kissinger:SEARCH_OBJECTIVE=share")
        self.assertEqual(seat(seats, 6).policy, "random")
        self.assertEqual(seat(seats, 5).log["decisions"], 7)

    def test_missing_results_is_reported_not_imputed(self):
        with tempfile.TemporaryDirectory() as tmp:
            ep = Path(tmp) / "ereq_x"
            ep.mkdir()
            (ep / "episode.json").write_text('{"id": "ereq_x", "status": "failed"}')
            seats, statuses = we.load_dirs([Path(tmp)])
        self.assertEqual(seats, [])
        self.assertEqual(statuses[0]["missing"], ["results"])


class BytesLiteralLogs(unittest.TestCase):
    def test_hosted_bytes_literal_log_is_decoded(self):
        path = next((GUNBOAT / "policy-logs").glob("*.0.log"))
        self.assertTrue(path.read_text().startswith("b'"))
        rows = we.read_log(path)
        self.assertEqual(sum(r["event"] == "orders_saved" for r in rows), 30)
        self.assertEqual(rows[0]["event"], "orders_saved")
        seats, _ = we.load_episode(GUNBOAT)
        self.assertEqual(seat(seats, 0).log["decisions"], 30)
        self.assertEqual(seat(seats, 0).log["rejected"], 0)


class FinalCenters(unittest.TestCase):
    def test_final_centers_come_from_results_not_the_stale_replay(self):
        # In this game the replay's Finished entry shows Germany with 3 centres and England
        # with 5; results.json members (authoritative) say 0 and 8.
        seats, _ = we.load_episode(PRESS)
        by_power = {s.power: s for s in seats}
        self.assertEqual(by_power["Germany"].final_centers, 0)
        self.assertFalse(by_power["Germany"].survived)
        self.assertEqual(by_power["Germany"].centers_by_year[1908], 0)
        self.assertEqual(by_power["England"].final_centers, 8)
        self.assertEqual(by_power["England"].centers_by_year[1908], 8)
        self.assertEqual(by_power["England"].final_year, 1908)


class TaintFlags(unittest.TestCase):
    def test_exception_in_real_seat_log(self):
        seats, _ = we.load_episode(PRESS)
        self.assertEqual(seat(seats, 2).taint, ["exception"])
        self.assertEqual(seat(seats, 3).taint, [])
        self.assertEqual(seat(seats, 0).taint, [])  # no log: rivals' logs are private

    def test_synthetic_taints(self):
        failing = [{"event": "llm_call", "status": 400, "error": "temperature unsupported"}] * 3
        failing += [{"event": "llm_call", "status": 200, "usage": {"cost": 0.002}}]
        logs = {
            0: [{"event": "decision", "rejected": 2}],
            1: failing,
            2: [{"event": "decision", "rejected": 0}, {"event": "llm_call", "status": 200, "cost_usd": 0.001}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            ep = write_episode(Path(tmp) / "g", [1 / 7] * 7, list(range(1, 8)), [3] * 7, logs=logs)
            seats, _ = we.load_episode(ep)
        self.assertEqual(seat(seats, 0).taint, ["rejected_orders"])
        self.assertEqual(seat(seats, 1).taint, ["llm_failing"])
        self.assertEqual(seat(seats, 1).log["llm_cost_usd"], 0.002)  # usage.cost form
        self.assertEqual(seat(seats, 2).taint, [])
        self.assertEqual(seat(seats, 2).log["llm_cost_usd"], 0.001)  # cost_usd form

    def test_cancelled_and_failed_episodes(self):
        with tempfile.TemporaryDirectory() as tmp:
            cancelled = write_episode(Path(tmp) / "a", [1 / 7] * 7, list(range(1, 8)), [3] * 7, outcome="cancelled")
            failed = write_episode(Path(tmp) / "b", [1 / 7] * 7, list(range(1, 8)), [3] * 7, status="failed")
            self.assertTrue(all(s.taint == ["cancelled"] for s in we.load_episode(cancelled)[0]))
            self.assertTrue(all(s.taint == ["episode_failed"] for s in we.load_episode(failed)[0]))


if __name__ == "__main__":
    unittest.main()
