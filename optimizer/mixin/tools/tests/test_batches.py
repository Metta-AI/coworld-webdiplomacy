"""batches.py: cost and wall-clock time per fetched batch, from episode rows and saved create responses."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401  (puts the tools folder on sys.path)
import batches


def episode(root: Path, batch: str, request: str, name: str, created: str, running: str, completed: str,
            cost=0.5, status="completed") -> None:
    ep = root / batch / request / name
    ep.mkdir(parents=True)
    (ep / "episode.json").write_text(json.dumps({
        "id": name, "status": status, "variant_name": "Classic press", "experience_request_id": request,
        "created_at": created, "running_at": running, "completed_at": completed, "cost_usd": cost,
        "participants": []}))


class Batches(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "artifacts"
        self.responses = Path(tmp.name) / "responses"
        self.responses.mkdir()
        episode(self.root, "ab", "xreq_1", "ereq_a", "2026-10-11T13:15:00Z", "2026-10-11T13:17:00Z",
                "2026-10-11T14:18:00Z", cost=0.5)
        episode(self.root, "ab", "xreq_2", "ereq_b", "2026-10-11T13:16:00Z", "2026-10-11T13:46:00Z",
                "2026-10-11T14:55:00Z", cost=0.7, status="failed")
        (self.responses / "ab-r0.json").write_text(json.dumps(
            {"id": "xreq_1", "cost_preview": {"estimated_cost_credits": 1.7}}))

    def rows(self):
        return batches.batch_rows([self.root], batches.read_estimates(self.responses))

    def test_wall_clock_runs_from_the_first_launch_to_the_last_finish(self):
        (row,) = self.rows()
        self.assertEqual((row["batch"], row["games"], row["not_completed"], row["requests"]), ("ab", 2, 1, 2))
        self.assertEqual(row["wall_minutes"], 100.0)
        self.assertEqual(row["game_minutes"], {"median": 65.0, "max": 69.0})
        self.assertEqual(row["wait_minutes"], {"median": 16.0, "max": 30.0})
        self.assertEqual(row["variants"], {"classic-press": 2})

    def test_cost_is_summed_and_the_estimate_says_how_many_requests_it_covers(self):
        (row,) = self.rows()
        self.assertEqual((row["cost_usd"], row["cost_usd_per_game"]), (1.2, 0.6))
        self.assertEqual((row["estimated_credits"], row["requests_with_estimate"]), (1.7, 1))
        text = batches.render([row])
        self.assertIn("| ab | 2 (1 not completed) | classic-press | 10-11 06:15 | 10-11 07:55 | 100 |", text)  # Pacific
        self.assertIn("$1.20 ($0.600) | 1.7 (0.85), 1 of 2 requests |", text)

    def test_rows_without_times_or_cost_do_not_break_the_table(self):
        ep = self.root / "league-press" / "round-0001" / "ereq_c"
        ep.mkdir(parents=True)
        (ep / "episode.json").write_text(json.dumps({"id": "ereq_c", "status": "running", "participants": []}))
        row = next(r for r in self.rows() if r["batch"] == "league-press")
        self.assertEqual((row["wall_minutes"], row["cost_usd"], row["estimated_credits"]), (None, None, None))
        self.assertIn("| league-press | 1 (1 not completed) |", batches.render([row]))

    def test_cli_exits_2_when_there_is_no_hosted_episode(self):
        with tempfile.TemporaryDirectory() as empty, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(batches.main([empty]), 2)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = batches.main([str(self.root), "--responses", str(self.responses), "--json"])
        self.assertEqual((code, json.loads(out.getvalue())[0]["batch"]), (0, "ab"))


if __name__ == "__main__":
    unittest.main()
