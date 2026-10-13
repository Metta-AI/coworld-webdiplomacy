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
                {"status": "running", "created_at": "2027-01-15T08:00:00Z", "completed_at": None}]}],
            "/v2/rounds": {"entries": [{"id": "round_demo", "round_number": 3, "status": "running",
                                         "created_at": "2027-01-15T08:00:00Z", "completed_at": None}],
                           "next_cursor": None},
        }
        self.responses.update({"/v2/league-policy-memberships": [], "/v2/league-submissions": [],
                               "/v2/rounds/round_demo/episodes": {"entries": [], "next_cursor": None}})
        self.api = Api(self.request)
        self.collector = Collector(self.store, self.api, clock=lambda: self.now)

    def request(self, method, path, params=None):
        self.calls.append((method, path, copy.deepcopy(params)))
        response = self.responses[path]
        if isinstance(response, Exception):
            raise response
        return response if isinstance(response, httpx.Response) else httpx.Response(200, json=copy.deepcopy(response))
