from fastapi.testclient import TestClient
from helpers import DeskTest

from league_desk.server import create_app
from league_desk.tournament import planner_data, tournament_panel

POWERS = ["England", "France", "Italy", "Germany", "Austria", "Turkey", "Russia"]
LEAGUE = {"id": "league_demo", "key": "press", "name": "Invented league"}


def seat(slot, player, policy, score, filler=False):
    return {"slot": slot, "player_id": player, "player": player.upper(), "policy_id": policy, "filler": filler,
            "seed": False, "score": score, "policy_label": None}


def game(game_id, seats, status="completed", coworld="cow_new", completed_at=100.0):
    return {"id": game_id, "episode_id": game_id, "coworld_id": coworld, "version": "9.9.1", "variant": "Classic",
            "status": status, "error_type": None, "seats": seats, "created_at": completed_at - 60,
            "dispatched_at": completed_at - 50, "running_at": completed_at - 40, "completed_at": completed_at}


def table(policy_a="pa2", filler_score=0.1):
    # Player a's current policy, a filler, and five other policies; scores sum to 1.
    return [seat(0, "a", policy_a, 0.4), seat(1, "f", "house", filler_score, filler=True)] + [
        seat(i, f"p{i}", f"pol{i}", (0.6 - filler_score) / 5) for i in range(2, 7)]


def results(seats, taints=None):
    return {"state": "ready", "facts": {"taints": taints or [], "score_issue": None, "seats": [
        {"slot": s["slot"], "power": POWERS[s["slot"]], "score": s["score"]} for s in seats]}}


def rating(player, value):
    return {"player_id": player, "player": player.upper(), "division_id": "d", "rating": value, "mu": value,
            "sigma": 1.0, "rounds_played": 3, "failures": 0, "failure_limit": 3, "current_policy_id": None,
            "last_round_id": None, "policies": []}


def snapshot():
    games = [game("g1", table()), game("g2", table("pa1"), completed_at=50.0), game("g3", table()),
             game("g4", table(), status="failed"), game("g5", table(), coworld="cow_old"),
             game("g6", table())]
    state = {
        ("episodes", "round_demo"): {"name": "episodes", "fetched_at": 90.0, "next_due": 390.0,
                                     "data": {"league_id": "league_demo", "round_id": "round_demo", "rows": games}},
        ("artifact_results", "g1"): {"data": results(table())},
        ("artifact_results", "g2"): {"data": results(table("pa1"))},
        ("artifact_results", "g3"): {"data": results(table(), taints=["seat 1 crashed"])},
        ("artifact_results", "g5"): {"data": results(table())},
        # g6 has no results facts: kept with unknown powers.
        ("memberships", "league_demo"): {"name": "memberships", "fetched_at": 90.0, "data": {"rows": [
            {"player_id": "a", "player": "A", "policy_id": "pa2", "policy": "alpha", "version": 2,
             "status": "competing", "substatus": "active", "champion": True, "division_id": "d",
             "created_at": 10.0},
            {"player_id": "a", "player": "A", "policy_id": "pa1", "policy": "alpha", "version": 1,
             "status": "competing", "substatus": "benched", "champion": False, "division_id": "d",
             "created_at": 5.0},
        ] + [{"player_id": f"p{i}", "player": f"P{i}", "policy_id": f"pol{i}", "policy": "beta", "version": 1,
              "status": "competing", "substatus": "active", "champion": True, "division_id": "d",
             "created_at": 10.0}
             for i in range(2, 10)]}},
        ("ratings", "league_demo"): {"name": "ratings", "fetched_at": 90.0, "data": {"rows": [
            rating("a", 30.0)] + [rating(f"p{i}", 20.0 - i) for i in range(2, 10)]}},
        ("seat_models", "league_demo"): {"data": {"rows": [
            {"episode": "g1", "slot": 0, "policy_version_id": "pa2", "usd": 0.25},
            {"episode": "g1", "slot": 0, "policy_version_id": "pa2", "usd": 0.05},
            {"episode": "g3", "slot": 0, "policy_version_id": "pa2", "usd": 0.10}]}},
        ("detail", "g1"): {"data": {"compute": 0.4}},
        ("detail", "g2"): {"data": {"compute": 0.2}},
    }
    return state


class TournamentDataTests(DeskTest):
    def test_scored_games_join_powers_and_exclude_tainted_failed_and_other_versions(self):
        data = planner_data(snapshot(), LEAGUE, "cow_new")
        self.assertEqual(data["fit"]["games"], 3)  # g1, g2, g6; g3 tainted, g4 failed, g5 other version
        self.assertEqual(data["fit"]["excluded"], 1)
        self.assertEqual(data["fit"]["without_powers"], 1)
        self.assertLess(data["fit"]["score_sum_error"], 1e-9)
        first = data["games"][1]["seats"]  # sorted by completion: g2 first, then g1
        self.assertEqual([s["power"] for s in first], list(range(7)))
        self.assertTrue(first[1]["filler"])
        self.assertEqual({s["power"] for s in data["games"][2]["seats"]}, {None})
        self.assertEqual(data["powers"], POWERS)
        self.assertEqual(planner_data(snapshot(), LEAGUE, "all")["fit"]["games"], 4)

    def test_champion_default_mmr_order_and_older_versions(self):
        players = planner_data(snapshot(), LEAGUE, "all")["players"]
        self.assertEqual([p["player_id"] for p in players][:3], ["a", "p2", "p3"])
        self.assertEqual([p["player_id"] for p in players if p["default"]], ["a"] + [f"p{i}" for i in range(2, 8)])
        a = players[0]
        self.assertEqual(a["champion_ids"], ["pa2"])
        self.assertEqual(set(a["policy_ids"]), {"pa1", "pa2"})
        self.assertEqual((a["games"], a["games_any_version"]), (3, 4))
        self.assertEqual(a["mmr"], 30.0)

    def test_cost_and_duration_inputs(self):
        costs = planner_data(snapshot(), LEAGUE, "all")["costs"]
        # One seat-game per episode/slot: g1 slot 0 sums to 0.30, g3 slot 0 is 0.10.
        self.assertAlmostEqual(costs["seat_usd"]["pa2"]["usd"], 0.2)
        self.assertEqual(costs["seat_usd"]["pa2"]["seats"], 2)
        self.assertAlmostEqual(costs["compute_usd"], 0.3)
        self.assertAlmostEqual(costs["median_minutes"], 40 / 60)
        self.assertEqual(costs["in_flight"], 8)

    def test_panel_carries_widget_source(self):
        competition = {"episode_sources": {"round_demo": snapshot()["episodes", "round_demo"]},
                       "game_coverage": "1/1 cached rounds."}
        result = tournament_panel(snapshot(), LEAGUE, competition, 120.0, "all")
        self.assertEqual(result["widget"], {"name": "tournament",
                                            "src": "/tournament-data?league=press&version=all&games=4"})
        self.assertIn("4 scored league games", result["sentence"])
        self.assertEqual(result["missing"], 0)

    def test_route_is_cache_only_json(self):
        state = snapshot()
        self.store.success("discovery", "all", {"coworld_id": "cow_new", "leagues": [LEAGUE]}, self.now)
        for (name, scope), source in state.items():
            # Spend panels need full seat_models/detail rows; this test only checks the planner's.
            if name not in ("seat_models", "detail"):
                self.store.success(name, scope, source["data"], self.now)
        self.calls.clear()
        client = TestClient(create_app(self.store), base_url="http://127.0.0.1")
        response = client.get("/tournament-data?league=press&version=all")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        body = response.json()
        self.assertEqual(body["fit"]["games"], 4)
        self.assertEqual(len(body["games"][0]["seats"]), 7)
        self.assertEqual(self.calls, [])
        self.assertEqual(client.get("/tournament-data?version=cow_missing").status_code, 422)
        page = client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn('data-widget="tournament"', page.text)
        self.assertIn("/static/tournament.js", page.text)
