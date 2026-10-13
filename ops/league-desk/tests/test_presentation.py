import copy
from unittest.mock import patch

import test_competition
from fastapi.testclient import TestClient
from helpers import DeskTest
from test_competition import raw_game

from league_desk.competition import episode
from league_desk.panels import competition_panels
from league_desk.server import create_app
from league_desk.spend_metrics import spending_panels


class PresentationTests(DeskTest):
    def populate(self):
        test_competition.CompetitionTests.enrich(self)
        self.collector.once()
        self.calls.clear()

    def client(self):
        return TestClient(create_app(self.store), base_url="http://127.0.0.1:8660")

    def test_fragments_are_cache_only_and_validate_filters(self):
        self.populate()
        with patch("coworld.api_client.CoworldApiClient.from_login", side_effect=AssertionError("login")):
            response = self.client().get("/fragments?range=30d&version=cow_demo&player=Ada")
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="desk-content"', response.text)
        self.assertNotIn('<html', response.text)
        self.assertIn("Ratings stay cumulative", response.text)
        self.assertIn("All Coworld versions; the version control does not apply", response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(self.calls, [])
        for query in ("range=bad", "version=absent", "league=absent"):
            self.assertEqual(self.client().get("/fragments?" + query).status_code, 422)

    def test_refresh_requires_same_origin_and_coalesces(self):
        client = self.client()
        for origin in (None, "null", "https://evil.invalid", "http://localhost:8660", "http://127.0.0.1:8661"):
            headers = {"origin": origin} if origin else {}
            self.assertEqual(client.post("/refresh", headers=headers).status_code, 403)
        for _ in range(3):
            response = client.post("/refresh", headers={"origin": "http://127.0.0.1:8660"})
            self.assertEqual(response.status_code, 202)
        self.assertTrue(self.store.take_refresh())
        self.assertFalse(self.store.take_refresh())
        self.assertEqual(self.calls, [])

    def test_manual_poll_refreshes_fast_groups_but_not_slow_or_failed_sources(self):
        self.populate()
        self.now += 1
        self.collector.manual = True
        self.collector.once()
        self.assertTrue(any(path == "/v2/budgets" for _, path, _ in self.calls))
        self.assertFalse(any(path.startswith("/admin/") or path == "/sql/query" for _, path, _ in self.calls))
        self.store.failure("budgets", "all", "API returned HTTP 429", self.now, 60)
        self.calls.clear()
        self.collector.once()
        self.assertFalse(any(path == "/v2/budgets" for _, path, _ in self.calls))
        self.store.defer(self.now + 60)
        self.calls.clear()
        self.collector.once()
        self.assertEqual(self.calls, [])

    def test_schema_one_migration_preserves_snapshots_and_history(self):
        self.store.success("ratings", "league_demo", {"rows": []}, self.now, observed=True)
        with self.store.connection() as db:
            db.execute("ALTER TABLE control DROP COLUMN refresh_requested")
            db.execute("PRAGMA user_version=1")
        self.store.initialize()
        self.assertEqual(len(self.store.snapshot(True)["ratings", "league_demo"]["history"]), 1)
        self.store.request_refresh()
        self.assertTrue(self.store.take_refresh())
        self.store.initialize()
        self.assertFalse(self.store.take_refresh())

    def test_time_and_version_filters_preserve_current_state_and_now_count(self):
        self.populate()
        snapshot = self.store.snapshot(True)
        old = episode(raw_game(self.now - 10 * 86400, "ereq_old"))
        old.update(coworld_id="cow_old", version="9.9.0")
        snapshot["episodes", "round_demo"]["data"]["rows"].append(old)
        league = {"id": "league_demo", "key": "press"}
        all_data = competition_panels(snapshot, league, self.now, 0, "all")
        selected = competition_panels(snapshot, league, self.now, 0, "cow_old")
        recent = competition_panels(snapshot, league, self.now, self.now - 86400, "cow_old")
        self.assertEqual(all_data["panel_data"]["Competing players"]["rows"][0][5], 2)
        self.assertEqual(selected["panel_data"]["Competing players"]["rows"][0][5], 1)
        self.assertEqual(recent["panel_data"]["Competing players"]["rows"][0][5], 0)
        self.assertEqual(selected["day_games"], all_data["day_games"])
        self.assertEqual(selected["panel_data"]["Competing players"]["rows"][0][2], "24.00")

    def test_rating_filters_select_observations_without_recomputing_mmr(self):
        self.populate()
        snapshot = self.store.snapshot(True)
        source = snapshot["ratings", "league_demo"]
        old = copy.deepcopy(source["history"][0])
        old["observed_at"] -= 10 * 86400
        old["data"]["canonical_id"] = "cow_old"
        old["data"]["rows"][0]["last_round_id"] = "round_old"
        source["history"].insert(0, old)
        data = competition_panels(snapshot, {"id": "league_demo"}, self.now, 0, "cow_old")
        chart = data["panel_data"]["MMR over time"]
        self.assertEqual(len(chart["chart"]["data"]), 1)
        self.assertEqual(chart["chart"]["data"][0]["value"], 24)
        self.assertIn("History starts at first run", chart["note"])

    def test_standings_cells_share_scale_and_have_source_table(self):
        self.populate()
        response = self.client().get("/")
        self.assertIn('class="data sources"', response.text)
        self.assertIn("Last 20 observations", response.text)
        self.assertIn("Shared rating interval scale", response.text)
        self.assertIn("Coverage</summary>", response.text)

    def test_request_filter_only_requires_selected_version_and_complete_current_window(self):
        self.populate()
        snapshot = self.store.snapshot(True)
        self.store.success("versions", "all", {"rows": [{"id": "cow_demo"}, {"id": "cow_old"}]}, self.now)
        row = {"id": "xreq_demo", "variant": "classic-press", "coworld_id": "cow_demo",
               "created_at": self.now - 60, "completed_at": self.now, "status": "completed",
               "requester_id": "invented", "requester": "Invented requester", "seen_at": self.now}
        self.store.success("requests", "cow_demo", {"rows": [row], "backfilled": True, "complete": True}, self.now)
        snapshot = self.store.snapshot(True)
        league = {"id": "league_demo", "key": "press"}
        competition = competition_panels(snapshot, league, self.now)
        selected = spending_panels(snapshot, league, self.now, competition, 0, "cow_demo")
        self.assertNotIn("coverage incomplete", selected["spend_panels"]["Requests per day"]["sentence"])
        snapshot["requests", "cow_demo"]["data"]["complete"] = False
        selected = spending_panels(snapshot, league, self.now, competition, 0, "cow_demo")
        self.assertIn("coverage incomplete", selected["spend_panels"]["Requests per day"]["sentence"])

    def test_unfinished_seat_costs_use_creation_window(self):
        self.populate()
        snapshot = self.store.snapshot(True)
        game = snapshot["episodes", "round_demo"]["data"]["rows"][0]
        game.update(status="running", completed_at=None, created_at=self.now - 2 * 86400)
        snapshot["seats", "league_demo"]["data"] = {"rows": [{
            "episode": game["id"], "slot": 0, "estimated": 1, "calls": 1, "rejections": 0}]}
        league = {"id": "league_demo", "key": "press"}
        competition = competition_panels(snapshot, league, self.now)
        result = spending_panels(snapshot, league, self.now, competition, self.now - 86400)
        self.assertEqual(result["spend_panels"]["LLM spend per seat per game"]["rows"], [])
