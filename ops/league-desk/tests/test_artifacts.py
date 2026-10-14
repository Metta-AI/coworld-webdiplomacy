import copy
import gzip
import json
from contextlib import contextmanager
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from helpers import DeskTest

from league_desk.api import Api, ApiError
from league_desk.artifacts import collect_artifacts, phase_durations, replay_facts
from league_desk.board_metrics import board_panels, policy_panel, score_facts
from league_desk.optimizer_tools import load_episode, movement_phases, stat
from league_desk.server import create_app


def results():
    return {"outcome": "drawn", "reason": "year_cap", "countries": [2, 1, 3, 4, 5, 6, 7],
            "scores": [.4, .1, .1, .1, .1, .1, .1], "final_state": {"turn": 3},
            "members": [{"countryID": str(i), "supplyCenterNo": str(i)} for i in range(1, 8)],
            "transitions": [{"turn": turn, "phase": phase, "elapsed_seconds": elapsed}
                            for turn, phase, elapsed in [(0, "Diplomacy", 1), (0, "Diplomacy", 2),
                                                         (1, "Diplomacy", 11), (1, "Finished", 31)]]}


def replay():
    territories = [{"id": 1, "name": "Spain", "supply": True},
                   {"id": 2, "name": "Spain (North Coast)", "supply": True, "coast": "Child",
                    "coastParentID": 1},
                   {"id": 3, "name": "Portugal", "supply": True}]
    order = {"countryID": 1, "unitType": "Fleet", "terrID": 3, "type": "Move", "toTerrID": 2,
             "success": False, "dislodged": False}
    phases = [{"turn": 0, "phase": "Diplomacy", "centers": [{"terrID": 1, "countryID": 1}],
               "orders": [order]},
              {"turn": 1, "phase": "Diplomacy", "centers": [{"terrID": 1, "countryID": 2}], "orders": [order]},
              {"turn": 1, "phase": "Finished", "centers": [{"terrID": 1, "countryID": 1}], "orders": []}]
    return [{"variant": {"territories": territories}, "history": {"phases": phases},
             "game": {"turn": 0, "phase": "Diplomacy", "phaseMinutes": 1, "processTime": 999},
             "episode": {"players": [{"name": "Ignore this new optional field"}]}}]


def game():
    return {"id": "ereq_demo", "status": "completed", "coworld_id": "cow_demo", "version": "0.7.11",
            "completed_at": 100,
            "seats": [{"slot": i, "policy_id": "pv_demo", "score": score}
                      for i, score in enumerate(results()["scores"])]}


class ArtifactTests(DeskTest):
    def setUp(self):
        super().setUp()
        self.store.success("episodes", "round_demo", {"league_id": "league_demo", "round_id": "round_demo",
                                                     "rows": [game()]}, self.now)
        self.artifact_calls = []
        self.payloads = {"results": json.dumps(results()).encode(),
                         "replay": gzip.compress(json.dumps(replay()).encode())}

        @contextmanager
        def stream(method, path):
            self.artifact_calls.append((method, path))
            payload = self.payloads[path.rsplit("/", 1)[1]]
            if isinstance(payload, Exception):
                raise payload
            yield payload if isinstance(payload, httpx.Response) else httpx.Response(200, content=payload)
        self.api.stream = stream

    def ingest(self):
        collect_artifacts(self.collector)
        return self.store.snapshot()

    def test_public_only_idempotence_shared_loader_country_mapping(self):
        snapshot = self.ingest()
        self.assertEqual(len(self.artifact_calls), 2)
        self.assertTrue(all(path.endswith(("/results", "/replay")) for _, path in self.artifact_calls))
        source = snapshot["artifact_results", "ereq_demo"]
        facts = source["data"]["facts"]
        self.assertEqual(facts["seats"][0]["power"], "France")
        self.assertEqual(facts["seats"][0]["final_centers"], 2)
        directory = (self.store.directory / source["data"]["path"]).parent
        seats, _ = load_episode(directory)
        self.assertEqual(seats[0].score, facts["seats"][0]["score"])
        self.ingest()
        self.assertEqual(len(self.artifact_calls), 2)
        self.assertEqual(facts["phases"], [{"turn": 0, "phase": "Diplomacy", "seconds": 10},
                                           {"turn": 1, "phase": "Diplomacy", "seconds": 20}])

    def test_missing_replay_retries_independently_and_survives_restart(self):
        self.payloads["replay"] = httpx.Response(404, text="secret signed URL must not persist")
        snapshot = self.ingest()
        self.assertIsNotNone(snapshot["artifact_results", "ereq_demo"]["data"])
        self.assertIsNone(snapshot["artifact_replay", "ereq_demo"]["data"])
        self.assertNotIn("secret", snapshot["artifact_replay", "ereq_demo"]["error"])
        self.store.initialize()
        self.ingest()
        self.assertEqual(len(self.artifact_calls), 2)
        self.now += 61
        self.payloads["replay"] = json.dumps(replay()).encode()
        self.ingest()
        self.assertEqual(len(self.artifact_calls), 3)
        self.assertIsNone(self.store.source("artifact_replay", "ereq_demo")["error"])

    def test_game_that_failed_without_artifacts_stops_retrying_and_is_not_stale(self):
        failed = {**game(), "status": "failed", "completed_at": self.now - 60}
        self.store.success("episodes", "round_demo", {"league_id": "league_demo", "round_id": "round_demo",
                                                     "rows": [failed]}, self.now)
        self.payloads["results"] = self.payloads["replay"] = httpx.Response(404)
        snapshot = self.ingest()
        # Within the first hour a 404 may still be an upload in flight: retry.
        self.assertIn("404", snapshot["artifact_results", "ereq_demo"]["error"])
        self.now = failed["completed_at"] + 3600
        self.artifact_calls.clear()
        snapshot = self.ingest()
        self.assertEqual(len(self.artifact_calls), 2)
        self.assertEqual(snapshot["artifact_results", "ereq_demo"]["data"]["state"], "absent")
        self.assertIsNone(snapshot["artifact_replay", "ereq_demo"]["error"])
        self.now += 7200
        self.ingest()
        self.assertEqual(len(self.artifact_calls), 2)  # Final: never fetched again.
        competition = {"episode_sources": {"round_demo": snapshot["episodes", "round_demo"]},
                       "game_coverage": "fixture", "panel_data": {"Games per day and how they ended": {
                           "chart": {}, "coverage": "", "sources": [], "stale": False}}}
        panels = board_panels(snapshot, None, competition, self.now, 0, "all")
        board = panels["Score by policy and power"]
        self.assertFalse(board["stale"])
        self.assertIn("1 games that did not complete have no artifacts", board["artifact_status"])

    def test_corrupt_replay_does_not_block_results_and_reparse_needs_no_network(self):
        self.payloads["replay"] = b'[{broken'
        snapshot = self.ingest()
        self.assertIsNotNone(snapshot["artifact_results", "ereq_demo"]["data"])
        self.assertIsNone(snapshot["artifact_replay", "ereq_demo"]["data"])
        old = snapshot["artifact_results", "ereq_demo"]["data"]
        self.store.success("artifact_results", "ereq_demo", {**old, "parser_version": 0}, self.now, cadence=0)
        self.ingest()
        self.assertEqual(len(self.artifact_calls), 2)
        self.assertEqual(self.store.source("artifact_results", "ereq_demo")["data"]["parser_version"], 1)

    def test_replay_board_reparses_from_local_file_for_every_version(self):
        snapshot = self.ingest()  # The fixture game is 0.7.11, before instrumentation.
        old = snapshot["artifact_replay", "ereq_demo"]["data"]
        self.assertEqual(old["parser_version"], 2)
        self.store.success("artifact_replay", "ereq_demo", {**old, "parser_version": 1,
                           "facts": {k: v for k, v in old["facts"].items() if k != "board"}}, self.now, cadence=0)
        self.ingest()
        self.assertEqual(len(self.artifact_calls), 2)  # No new download.
        data = self.store.source("artifact_replay", "ereq_demo")["data"]
        self.assertEqual(data["parser_version"], 2)
        self.assertEqual([p["turn"] for p in data["facts"]["board"]["phases"]], [0, 1])

    def test_missing_scores_are_quarantined_not_silently_zero(self):
        payload = results()
        payload["scores"][0] = None
        self.payloads["results"] = json.dumps(payload).encode()
        facts = self.ingest()["artifact_results", "ereq_demo"]["data"]["facts"]
        self.assertEqual(facts["seats"], [])
        self.assertTrue(facts["score_issue"])
        self.assertEqual(facts["reason"], "year_cap")

    def test_failed_cancelled_timeout_and_score_conflict_excluded(self):
        facts = self.ingest()["artifact_results", "ereq_demo"]["data"]["facts"]
        self.assertEqual(len(score_facts(game(), facts)), 7)
        mismatch = game()
        mismatch["seats"][0]["score"] = .9
        self.assertEqual(score_facts(mismatch, facts), [])
        for taint in ("cancelled", "episode_failed", "episode_timeout"):
            self.assertEqual(score_facts(game(), {**facts, "taints": [taint]}), [])
        self.assertEqual(score_facts({**game(), "status": "failed"}, facts), [])

    def test_download_limits_redirect_auth_errors_and_global_rate_floor(self):
        for kind in ("trajectory", "policy-logs"):
            with self.assertRaises(ApiError):
                self.api.artifact("ereq_demo", kind, self.store.directory / "test.part", 10)
        for status in (302, 403):
            self.payloads["replay"] = httpx.Response(status, headers={"location": "https://private.invalid/?secret"})
            with self.assertRaises(ApiError):
                self.api.artifact("ereq_demo", "replay", self.store.directory / "test.part", 10)
        self.payloads["replay"] = b'a'*11
        with self.assertRaisesRegex(ApiError, "size limit"):
            self.api.artifact("ereq_demo", "replay", self.store.directory / "test.part", 10)
        self.payloads["replay"] = httpx.Response(429, headers={"x-ratelimit-retry-after": "500"})
        self.artifact_calls.clear()
        self.ingest()
        self.assertEqual(len(self.artifact_calls), 1)
        self.assertEqual(self.store.retry_not_before(), self.now + 500)
        self.now += 61
        self.ingest()
        self.assertEqual(len(self.artifact_calls), 1)

    def test_partial_stream_and_expanded_gzip_limit_never_commit_ready(self):
        class Broken(httpx.SyncByteStream):
            def __iter__(self):
                yield b'['
                raise httpx.ReadError("private failure")
        self.payloads["replay"] = httpx.Response(200, stream=Broken())
        self.ingest()
        self.assertIsNone(self.store.source("artifact_replay", "ereq_demo")["data"])
        self.now += 61
        self.payloads["replay"] = gzip.compress(b' '*1001)
        with patch("league_desk.artifacts.MAX_ARTIFACT_JSON_BYTES", 1000):
            self.ingest()
        self.assertIsNone(self.store.source("artifact_replay", "ereq_demo")["data"])

    def test_coasts_duplicate_phase_first_board_and_finished_board(self):
        data = replay()
        data[0]["history"]["phases"].insert(1, copy.deepcopy(data[0]["history"]["phases"][0]))
        board = replay_facts(data)["board"]
        # One entry per movement turn: the duplicate and the stale Finished board add nothing.
        self.assertEqual([p["turn"] for p in board["phases"]], [0, 1])
        self.assertEqual(board["phases"][0]["held"], {"1": [1]})
        self.assertEqual(board["phases"][1]["held"], {"2": [1]})
        self.assertNotIn("2", board["provinces"])  # Spain's north coast folds into Spain.
        self.assertEqual(board["provinces"]["1"], ["Spain", True, None])
        self.assertEqual(movement_phases(replay())[0]["orders"][0]["to"], "SPA")
        self.assertFalse(movement_phases(replay())[-1]["end_known"])
        self.assertIsNone(replay_facts(data)["early_finish"])

    def test_cluster_intervals_five_game_floor_and_zero_variance(self):
        seats = [{"game": f"g{i}", "power": "France", "policy_id": "pv_demo", "score": i/10,
                  "survived": True, "solo": False} for i in range(5)]
        france = policy_panel(seats, {}, {"pv_demo"})["chart"]["data"][1]
        self.assertEqual(france["ci"], stat([(s["game"], s["score"] - 1 / 7) for s in seats])["ci"])
        self.assertEqual(policy_panel(seats[:4]*2, {}, {"pv_demo"})["chart"]["data"][1]["games"], 4)
        self.assertIn("0 policy/power", policy_panel(seats[:4]*2, {}, {"pv_demo"})["sentence"])
        self.assertEqual(policy_panel(seats, {}, {"pv_other"})["chart"]["data"], [])
        same = [{**s, "score": .2} for s in seats]
        self.assertIsNone(policy_panel(same, {}, {"pv_demo"})["chart"]["data"][1]["ci"])

    def test_final_incomplete_phase_excluded(self):
        self.assertEqual(phase_durations([{"turn": 0, "phase": "Diplomacy", "elapsed_seconds": 1}]), [])
        with self.assertRaises(ValueError):
            phase_durations([{"turn": 0, "phase": "Diplomacy", "elapsed_seconds": -1}])

    def test_cache_only_routes_and_immutable_age_with_selection(self):
        snapshot = self.ingest()
        competition = {"episode_sources": {"round_demo": snapshot["episodes", "round_demo"]},
                       "game_coverage": "fixture", "panel_data": {"Games per day and how they ended": {
                           "chart": {}, "coverage": "", "sources": [], "stale": False}}}
        panels = board_panels(snapshot, {"id": "league_demo"}, competition, self.now + 1e6, 0, "all")
        self.assertFalse(panels["Score by policy and power"]["stale"])
        self.assertIn("Results 1/1", panels["Score by policy and power"]["artifact_status"])
        filtered = board_panels(snapshot, None, competition, self.now, 101, "all")
        self.assertIn("Results 0/0", filtered["Score by policy and power"]["artifact_status"])
        filtered = board_panels(snapshot, None, competition, self.now, 0, "cow_other")
        self.assertIn("Results 0/0", filtered["Score by policy and power"]["artifact_status"])
        with patch("league_desk.artifacts.read_json_file", side_effect=AssertionError("parsing forbidden")), \
                patch.object(Api, "artifact", side_effect=AssertionError("download forbidden")):
            client = TestClient(create_app(self.store), base_url="http://127.0.0.1:8660")
            self.assertEqual(client.get('/').status_code, 200)
            self.assertEqual(client.get('/fragments').status_code, 200)

    def test_attempt_budget_and_replay_failure_does_not_stale_results_panel(self):
        self.payloads["replay"] = httpx.Response(404)
        snapshot = self.ingest()
        competition = {"episode_sources": {"round_demo": snapshot["episodes", "round_demo"]},
                       "game_coverage": "fixture", "panel_data": {"Games per day and how they ended": {
                           "chart": {}, "coverage": "", "sources": [], "stale": False}}}
        panels = board_panels(snapshot, None, competition, self.now, 0, "all")
        self.assertFalse(panels["Score by policy and power"]["stale"])
        self.assertTrue(panels["The board"]["stale"])
        self.store.success("episodes", "round_demo", {"league_id": "league_demo", "round_id": "round_demo",
            "rows": [{**game(), "id": f"ereq_extra{i}"} for i in range(10)]}, self.now)
        self.artifact_calls.clear()
        self.ingest()
        self.assertEqual(len(self.artifact_calls), 4)
