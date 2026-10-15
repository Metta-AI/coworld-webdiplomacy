import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from league_desk.api import Api
from league_desk.collector import Collector
from league_desk.store import Store


class DeskTest(unittest.TestCase):
    def setUp(self):
        for target in ("httpx.HTTPTransport.handle_request", "socket.create_connection"):
            guard = patch(target, side_effect=AssertionError("Network is forbidden in tests"))
            guard.start()
            self.addCleanup(guard.stop)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = Store(Path(directory.name) / ".runtime")
        self.store.initialize()
        self.now = 1800000000.0
        self.calls = []
        self.responses = {
            "/v2/games": [{"id": "game_demo", "coworld_name": "webdiplomacy", "canonical_coworld_id": "cow_demo"}],
            "/v2/leagues": [{"id": "league_demo", "name": "Invented league",
                             "commissioner_config": {"default_variant_id": "classic-press"}}],
            "/v2/coworlds/cow_demo": {"id": "cow_demo", "name": "webdiplomacy", "version": "9.9.1",
                                      "canonical": True, "manifest": {"secret": "must-not-store"}},
            "/v2/budgets": {"as_of": "2027-01-15T08:00:00Z", "resets_at": "2027-01-16T07:00:00Z",
                            "leagues": [{"league_id": "league_demo", "daily_budget_usd": 40,
                                         "spent_today_usd": 4, "projected_today_usd": 12,
                                         "remaining_today_usd": 36, "status": "ok", "email": "not-for-cache"}]},
            "/v2/leagues/league_demo/settings": {"settings": {"round_interval_minutes": 45,
                                                              "episode_player_pod_llm_spend_limit_usd": 1.5}},
            "/v2/leagues/health": [{"league_id": "league_demo", "rounds": [
                {"status": "running", "created_at": "2027-01-15T08:00:00Z", "completed_at": None}],
                "budgets": [{"checked_at": "2027-01-15T08:00:00Z", "refusal_cause": None}]}],
            "/v2/leagues/league_demo/owner-status": {"credits": {
                "pool_credits": 250.0, "granted_today_credits": 400.0, "play_charged_today_credits": 150.0,
                "paid_today_credits": 0.0, "expected_net_credits": 250.0}, "budget": {"secret": "not-for-cache"}},
            "/v2/rounds": {"entries": [{"id": "round_demo", "round_number": 3, "status": "running",
                                         "created_at": "2027-01-15T08:00:00Z", "completed_at": None}],
                           "next_cursor": None},
        }
        self.responses.update({"/v2/league-policy-memberships": [], "/v2/league-submissions": [],
                               "/v2/rounds/round_demo/episodes": {"entries": [], "next_cursor": None}})
        self.responses.update({"/v2/coworlds/summaries": [], "/admin/llm-coworld-usage": {"period": "week", "rows": []},
                               "/admin/costs/leagues": {"period": "week", "leagues": []}})
        self.api = Api(self.request)
        original_select = self.api.select

        def select(kind, ids, after=None, **kwargs):
            from league_desk.sql import ATTRIBUTION_COLUMNS
            if kind in ATTRIBUTION_COLUMNS:
                return {"columns": ATTRIBUTION_COLUMNS[kind], "rows": []}
            return original_select(kind, ids, after, **kwargs)

        self.api.select = select
        self.collector = Collector(self.store, self.api, clock=lambda: self.now)

    def request(self, method, path, params=None, json=None, timeout=None):
        self.calls.append((method, path, copy.deepcopy(params)))
        if path == "/sql/query":
            return httpx.Response(200, json={"columns": ["episode", "slot", "calls", "estimated", "rejections"],
                                             "rows": [], "row_count": 0})
        response = self.responses[path]
        if isinstance(response, Exception):
            raise response
        return response if isinstance(response, httpx.Response) else httpx.Response(200, json=copy.deepcopy(response))
