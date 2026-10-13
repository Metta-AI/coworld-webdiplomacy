import copy
import gzip
import json
from contextlib import contextmanager
from unittest.mock import patch

import httpx
from helpers import DeskTest
from test_artifacts import game, replay, results

from league_desk.api import ApiError
from league_desk.artifacts import collect_artifacts
from league_desk.board_metrics import board_panels
from league_desk.instrument_metrics import instrumentation_panels
from league_desk.instrumentation import log_facts, result_instrumentation, supported


def instrumented_results():
    raw = results()
    raw.update(
        reason="end_year",
        seat_health=[
            {
                "slot": i,
                "connections": [
                    {"event": "connect", "elapsed_seconds": 12 if i == 0 else 2},
                    {"event": "disconnect", "elapsed_seconds": 20},
                    {"event": "reconnect", "elapsed_seconds": 25},
                ],
                "api_requests": 10,
            }
            for i in range(7)
        ],
    )
    raw["transitions"] = [
        {
            "turn": turn,
            "phase": phase,
            "elapsed_seconds": elapsed,
            "unix_time": 1000 + elapsed,
            "deadline_unix_time": deadline,
        }
        for turn, phase, elapsed, deadline in (
            (0, "Diplomacy", 10, 1110),
            (0, "Diplomacy", 11, 1110),
            (0, "Retreats", 60, 1090),
            (1, "Diplomacy", 90, 1190),
            (1, "Finished", 100, None),
        )
    ]
    raw["gamemaster_calls"] = {"phases": [{"turn": 0, "phase": "Diplomacy", "count": 20, "max_seconds": 0.4}]}
    raw["timing"] = {
        k + "_seconds": v
        for k, v in (
            ("storage", 2),
            ("game_creation", 1),
            ("services", 3),
            ("player_connect_wait", 4),
            ("play", 90),
            ("replay_write", 2),
        )
    }
    return raw


def log_lines():
    seats = [
        {"first_saved_seconds": 10, "first_ready_seconds": 25},
        {"first_saved_seconds": None, "first_ready_seconds": None},
        *([None] * 5),
    ]
    return [
        {
            "event": "seat_activity",
            "phases": [
                {"turn": turn, "phase": phase, "seats": seats}
                for turn, phase in ((0, "Diplomacy"), (0, "Retreats"), (1, "Diplomacy"))
            ],
        },
        {
            "event": "timing",
            **instrumented_results()["timing"],
            "results_write_seconds": 1,
            "acknowledgement_wait_seconds": 2,
            "shutdown_seconds": 3,
            "total_seconds": 108,
        },
    ]


def log_bytes():
    return "\n".join(json.dumps(r) for r in log_lines()).encode()


class InstrumentationTests(DeskTest):
    def setUp(self):
        super().setUp()
        self.payloads = {"replay": b"[]"}
        self.artifact_calls = []

        @contextmanager
        def stream(method, path):
            self.artifact_calls.append(path)
            yield httpx.Response(200, content=self.payloads[path.rsplit("/", 1)[1]])

        self.api.stream = stream

    def ingest(self):
        collect_artifacts(self.collector)
        return self.store.snapshot()

    def test_log_parser_whitelist_null_absent_and_cancelled(self):
        blob = b'service ready\n{"event":"other", "secret":"DO NOT CACHE"}\n' + log_bytes()
        facts = log_facts(gzip.compress(blob))
        self.assertNotIn("DO NOT CACHE", str(facts))
        self.assertIsNone(facts["activity"][0]["seats"][2])
        self.assertIsNone(facts["activity"][0]["seats"][1]["first_ready_seconds"])
        self.assertEqual(log_facts(b"no measurements"), {"activity": None, "timing": None})
        stopped = log_facts(b'{"event":"timing","interrupted_seconds":4,"total_seconds":4}')
        self.assertIsNone(stopped["activity"])
        raw = instrumented_results()
        raw["outcome"] = "cancelled"
        for seat in raw["seat_health"]:
            seat["api_requests"] = None
        self.assertIsNone(result_instrumentation(raw)["health"][0]["api_requests"])
        with self.assertRaises(ValueError):
            log_facts(log_bytes() + b'\n{"event":"seat_activity"')
        with self.assertRaises(ValueError):
            log_facts(log_bytes() + b"\n" + log_bytes())
        with patch("league_desk.instrumentation.MAX_ARTIFACT_JSON_BYTES", 10):
            with self.assertRaises(ValueError):
                log_facts(gzip.compress(blob))
        lines = log_lines()
        lines[0]["phases"][0]["seats"][0]["first_ready_seconds"] = -1
        with self.assertRaises(ValueError):
            log_facts(json.dumps(lines[0]).encode())

    def test_result_clocks_deadlines_and_adjudication(self):
        facts = result_instrumentation(instrumented_results())
        self.assertEqual(len(facts["phases"]), 3)
        self.assertEqual(facts["phases"][0]["length"], 100)
        self.assertEqual(facts["phases"][0]["seconds"], 50)
        self.assertTrue(facts["phases"][0]["early"])
        self.assertFalse(facts["phases"][1]["early"])
        self.assertIsNone(facts["phases"][2]["early"])
        self.assertEqual(facts["phases"][0]["adjudication"], 0.4)
        self.assertIsNone(facts["phases"][1]["adjudication"])
        raw = instrumented_results()
        raw["transitions"][1]["deadline_unix_time"] = 1120
        self.assertEqual(result_instrumentation(raw)["phases"][0]["length"], 110)
        raw["transitions"][0]["deadline_unix_time"] = None
        raw["transitions"][1]["deadline_unix_time"] = None
        self.assertIsNone(result_instrumentation(raw)["phases"][0]["length"])

    def data(self, n=5):
        games, result_data, logs = {}, {}, {}
        for i in range(n):
            g = {
                **game(),
                "id": f"ereq_invented{i}",
                "version": "0.7.12",
                "created_at": 0,
                "dispatched_at": 5,
                "running_at": 15,
            }
            g["seats"] = [{**s, "policy_id": f"pv_{s['slot']}"} for s in g["seats"]]
            games[g["id"]] = g
            result_data[g["id"]] = {"instrumentation": result_instrumentation(instrumented_results())}
            logs[g["id"]] = log_facts(log_bytes())
        return games, result_data, logs

    def test_ready_shares_floor_null_seats_and_old_games(self):
        games, data, logs = self.data()
        panels = instrumentation_panels(games, data, logs, {"pv_0": "Invented first", "pv_1": "Invented second"})
        ready = panels["Time to Ready"]
        self.assertEqual(len(ready["rows"]), 4)  # Null seats excluded; two phase types.
        first = next(r for r in ready["rows"] if r[:2] == ["Invented first", "Movement"])
        self.assertEqual(first[3:9], [5, "10.0%", 5, "25.0%", 5, "0/5 (0.0%)"])
        second = next(r for r in ready["rows"] if r[:2] == ["Invented second", "Movement"])
        self.assertEqual(second[8], "5/5 (100.0%)")
        self.assertEqual(len(ready["chart"]["data"]), 4)
        small = instrumentation_panels(*self.data(4), {})["Time to Ready"]
        self.assertFalse(small["chart"]["data"])
        old = next(iter(games.values()))
        old["version"] = "0.7.11"
        ready = instrumentation_panels(games, data, logs, {})["Time to Ready"]
        self.assertIn("4 of 5 games covered", ready["note"])
        self.assertFalse(ready["chart"]["data"])
        self.assertFalse(supported("0.7.12-rc1"))
        self.assertTrue(supported("0.8.0"))

    def test_ready_medians_weight_games_once(self):
        games, data, logs = self.data()
        key = next(iter(games))
        for turn in range(2, 22):
            phase = copy.deepcopy(data[key]["instrumentation"]["phases"][0])
            phase["turn"] = turn
            data[key]["instrumentation"]["phases"].append(phase)
            activity = copy.deepcopy(logs[key]["activity"][0])
            activity["turn"] = turn
            activity["seats"][0]["first_ready_seconds"] = 95
            logs[key]["activity"].append(activity)
        result = instrumentation_panels(games, data, logs, {"pv_0": "Invented"})["Time to Ready"]
        row = next(r for r in result["rows"] if r[:2] == ["Invented", "Movement"])
        self.assertEqual(row[6], "25.0%")
        self.assertEqual(row[7], 5)

    def test_health_and_real_stages_keep_unknowns(self):
        games, data, logs = self.data()
        panels = instrumentation_panels(games, data, logs, {})
        first = panels["Seat health"]["rows"][0]
        self.assertEqual(first[1:6], [5, 5, 5, "5/5 timed seats", 0])
        self.assertEqual(first[7:10], ["10.00", 5, "unknown"])
        self.assertEqual(panels["Seat health"]["rows"][1][6], "5/5 covered games with orders due")
        stages = panels["Where an episode's time goes"]
        self.assertEqual(stages["rows"][0], ["Queue", "5.00", 5])
        self.assertEqual(len(stages["rows"]), 11)
        self.assertIn("not additive", stages["note"])
        phases = panels["Phase timing"]
        self.assertIn("0.40", str(phases["rows"]))
        self.assertIn("1/1", str(instrumentation_panels(*self.data(1), {})["Phase timing"]["rows"]))
        key = next(iter(games))
        logs[key]["timing"] = {"interrupted_seconds": 10}
        data[key]["instrumentation"]["health"][0]["api_requests"] = None
        data[key]["instrumentation"]["health"][0]["connections"] = []
        panels = instrumentation_panels(games, data, logs, {})
        self.assertIn("4 of 5 games covered", panels["Where an episode's time goes"]["note"])
        self.assertEqual(panels["Seat health"]["rows"][0][8], 4)
        self.assertEqual(panels["Seat health"]["rows"][0][5], 1)
        logs.clear()
        self.assertIn("0/0 covered", instrumentation_panels(games, data, logs, {})["Seat health"]["rows"][1][6])

    def test_log_failure_is_independent_and_selection_is_respected(self):
        g = {**game(), "version": "0.7.12"}
        self.store.success("episodes", "round_demo", {"round_id": "round_demo", "rows": [g]}, self.now)
        self.payloads.update(results=json.dumps(instrumented_results()).encode(),
                             replay=json.dumps(replay()).encode(), logs=b"not uploaded yet")
        snapshot = self.ingest()
        competition = {"episode_sources": {"round_demo": snapshot["episodes", "round_demo"]},
                       "game_coverage": "fixture", "panel_data": {"Games per day and how they ended": {
                           "chart": {}, "coverage": "", "sources": [], "stale": False}}}
        panels = board_panels(snapshot, None, competition, self.now, 0, "all")
        self.assertTrue(panels["Time to Ready"]["stale"])
        self.assertFalse(panels["Contested provinces"]["stale"])
        self.assertFalse(panels["Phase timing"]["stale"])
        self.assertFalse(panels["Score by power, all players"]["stale"])
        self.assertIn("1 of 1 games covered", panels["Seat health"]["note"])
        for start, version in ((101, "all"), (0, "cow_other")):
            panels = board_panels(snapshot, None, competition, self.now, start, version)
            self.assertIn("0 of 0 games covered", panels["Seat health"]["note"])
            self.assertFalse(panels["Time to Ready"]["stale"])

    def test_running_games_never_download_activity(self):
        g = {**game(), "version": "0.7.12", "status": "running"}
        self.store.success("episodes", "round_demo", {"round_id": "round_demo", "rows": [g]}, self.now)
        self.ingest()
        self.assertFalse(self.artifact_calls)

    def test_new_log_ledger_is_memory_only_and_independent(self):
        g = {**game(), "version": "0.7.12"}
        self.store.success(
            "episodes", "round_demo", {"round_id": "round_demo", "league_id": "league_demo", "rows": [g]}, self.now
        )
        self.payloads.update(results=json.dumps(instrumented_results()).encode(), logs=log_bytes())
        state = self.ingest()["artifact_logs", "ereq_demo"]["data"]
        self.assertNotIn("path", state)
        self.assertTrue(state["facts"]["activity"])
        self.assertFalse(any(p.is_file() for p in self.store.directory.rglob("logs/*")))
        count = len(self.artifact_calls)
        self.ingest()
        self.assertEqual(count, len(self.artifact_calls))
        with self.assertRaises(ApiError):
            self.api.artifact("ereq_demo", "logs", self.store.directory / "raw.log", 1000)
        self.payloads["logs"] = b"still uploading"
        self.store.failure("artifact_logs", "ereq_demo", "pending", self.now - 100, 60)
        self.ingest()
        self.assertEqual(self.store.source("artifact_logs", "ereq_demo")["data"], state)
        self.assertIn("incomplete", self.store.source("artifact_logs", "ereq_demo")["error"])
        self.assertIsNone(self.store.source("artifact_results", "ereq_demo")["error"])
        self.now = self.store.source("artifact_logs", "ereq_demo")["next_due"] + 1
        self.payloads["logs"] = b'{"event":"timing","interrupted_seconds":4,"total_seconds":4}'
        self.ingest()
        self.assertIsNone(self.store.source("artifact_logs", "ereq_demo")["error"])
