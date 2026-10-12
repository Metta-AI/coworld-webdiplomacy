"""run_ab.py --dry-run: the quote from saved create responses, and the line beside batches.py. No network."""

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import _path  # noqa: F401  (puts the tools folder on sys.path)
import run_ab

NOW = datetime(2026, 10, 12, 8, 0, tzinfo=timezone.utc)


def body(games, variant="classic-press", seats=7, budget=14.0):
    return {"target": {"league_id": "league_x", "variant_id": variant}, "num_episodes": games,
            "episode_player_llm_spend_limit_usd": budget, "roster": [{"slot": i} for i in range(seats)]}


def response(responses: Path, name, request, games, credits, created, variant="classic-press", seats=7, per_seat=2.0):
    (responses / f"{name}.json").write_text(json.dumps({
        "id": request, "variant_id": variant, "episode_count": games, "created_at": created,
        "requested": {"num_episodes": games, "roster": [{"slot": i} for i in range(seats)]},
        "cost_preview": {"estimated_cost_credits": credits, "player_pod_llm_spend_limit_usd": per_seat}}))


def episodes(artifacts: Path, batch, request, count, created="2026-10-12T04:30:00Z", done="2026-10-12T05:40:00Z"):
    for i in range(count):
        ep = artifacts / batch / request / f"ereq_{request}_{i}"
        ep.mkdir(parents=True)
        (ep / "episode.json").write_text(json.dumps({
            "id": ep.name, "status": "completed", "variant_name": "Classic press", "experience_request_id": request,
            "created_at": created, "running_at": created, "completed_at": done, "cost_usd": 0.5,
            "participants": []}))


class DryRun(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.responses = Path(tmp.name) / "responses"
        self.responses.mkdir()
        self.artifacts = Path(tmp.name) / "artifacts"
        response(self.responses, "old-r0", "xreq_old", 3, 6.0, "2026-10-12T04:00:00Z")
        response(self.responses, "ab-r0", "xreq_ab", 3, 6.6, "2026-10-12T04:30:00Z")
        response(self.responses, "alone-r0", "xreq_alone", 10, 28.0, "2026-10-12T06:48:00Z")
        response(self.responses, "health", "xreq_health", 1, 2.2, "2026-10-12T04:31:00Z", variant="classic-press-short")
        self.quotes = run_ab.saved_quotes(self.responses)

    def test_a_request_of_a_size_already_quoted_gets_its_newest_quote(self):
        found = run_ab.quote(body(3), self.quotes)
        self.assertEqual((found["basis"], found["low"], found["high"]), ("exact", 6.6, 6.6))

    def test_a_size_never_quoted_gets_the_range_between_the_nearest_sizes(self):
        found = run_ab.quote(body(6), self.quotes)
        self.assertEqual(found["basis"], "between")
        self.assertAlmostEqual(found["low"], 6 * 2.2)   # 6.6 credits for 3 games
        self.assertAlmostEqual(found["high"], 6 * 2.8)  # 28.0 credits for 10 games
        above = run_ab.quote(body(20), self.quotes)
        self.assertEqual((above["basis"], above["low"]), ("nearest", 56.0))

    def test_another_kind_of_request_is_not_priced_from_these(self):
        self.assertEqual(run_ab.quote(body(3, variant="classic-gunboat", budget=0.0), self.quotes)["basis"], "none")
        self.assertEqual(run_ab.quote(body(3, budget=7.0), self.quotes)["basis"], "none")
        self.assertEqual(run_ab.quote(body(1, variant="classic-press-short"), self.quotes)["basis"], "exact")

    def test_the_report_gives_each_group_the_total_and_says_it_is_not_a_fresh_quote(self):
        groups = [("paired", [body(6)] * 14), ("health game", [body(1, variant="classic-press-short")])]
        text = run_ab.dry_run_report(groups, self.quotes, self.artifacts, self.responses, NOW)
        self.assertIn("DRY RUN: nothing launched", text)
        self.assertIn("paired: 14 request(s) x 6 game(s) = 84 game(s) on classic-press; 184.8 to 235.2 credits "
                      "(2.20 to 2.80 a game): no saved quote at 6 a request", text)
        self.assertIn("total: 187.0 to 237.4 credits", text)
        self.assertIn("not a fresh quote", text)
        self.assertIn("no finished batch on classic-press", text)

    def test_the_comparison_reads_finished_batches_only(self):
        episodes(self.artifacts, "ab", "xreq_ab", 3)        # all 3 games of ab-r0.json in: finished
        episodes(self.artifacts, "alone", "xreq_alone", 4)  # 4 of the 10 games of alone-r0.json in: still playing
        episodes(self.artifacts, "last-week", "xreq_old", 3,
                 created="2026-10-01T04:00:00Z", done="2026-10-01T05:00:00Z")
        line = run_ab.finished_line("classic-press", 6 * 2.8, 6 * 2.8, 6, self.artifacts, self.responses, NOW)
        self.assertIn("1 finished batch(es) on classic-press in the last 24 hours, 3 games", line)
        self.assertIn("quoted 2.20 credits a game at create (this dry run: 2.80, above)", line)
        self.assertIn("recorded $0.50 a game after they ran", line)


if __name__ == "__main__":
    unittest.main()
