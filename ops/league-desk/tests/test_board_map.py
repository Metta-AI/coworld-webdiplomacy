from unittest.mock import patch

from fastapi.testclient import TestClient
from helpers import DeskTest

from league_desk.api import Api
from league_desk.artifacts import board_facts, contested_provinces
from league_desk.board_map import board_map_panel, centre_scores, map_entries, map_report, phase_key, win_shares
from league_desk.instrumentation import result_instrumentation
from league_desk.server import create_app

TERRITORIES = [
    {"id": 1, "name": "Spain", "supply": True, "homeCountryID": None},
    {"id": 2, "name": "Spain (North Coast)", "supply": False, "coast": "Child", "coastParentID": 1},
    {"id": 3, "name": "Portugal", "supply": True, "homeCountryID": None},
    {"id": 4, "name": "Gascony", "supply": False, "homeCountryID": None},
    {"id": 5, "name": "Paris", "supply": True, "homeCountryID": "2"},
    {"id": 6, "name": "London", "supply": True, "homeCountryID": "1"},
]


def order(country, at, kind="Hold", to=None, success=False):
    return {"countryID": country, "terrID": at, "type": kind, "toTerrID": to, "success": success}


def last_frame():
    first = {"turn": 0, "phase": "Diplomacy",
             "centers": [{"terrID": 1, "countryID": 0}, {"terrID": 3, "countryID": "0"},
                         {"terrID": 5, "countryID": 2}, {"terrID": 6, "countryID": 1}],
             "units": [{"countryID": 2, "terrID": 4, "retreating": False},
                       {"countryID": 1, "terrID": 3, "retreating": False}],
             "orders": [
                 order(2, 4, "Move", 2),           # France into Spain via its coast ...
                 order(1, 3, "Move", 1),           # ... and England too: Spain is contested.
                 order(3, 9, "Move", 3, True),     # Italy into Portugal, whose English unit failed to leave.
                 order(1, 6),                      # England holds London ...
                 order(4, 9, "Move", 6),           # ... against Germany: contested.
                 order(2, 5, "Move", 4, True),     # France into Gascony, held by France: not contested.
                 order(5, 9, "Move", 5),           # Austria into Paris, which France left: not contested.
             ]}
    second = {"turn": 1, "phase": "Diplomacy",
              "centers": [{"terrID": 1, "countryID": 2}, {"terrID": 3, "countryID": 3},
                          {"terrID": 5, "countryID": 2}, {"terrID": 6, "countryID": 1}],
              "units": [{"countryID": 2, "terrID": 4, "retreating": True}], "orders": []}
    later = [{"turn": 1, "phase": "Retreats", "centers": [], "units": [], "orders": []},
             {"turn": 1, "phase": "Finished", "centers": [{"terrID": 1, "countryID": 1}], "units": [], "orders": []}]
    return {"variant": {"territories": TERRITORIES}, "history": {"phases": [first, second, *later]}}


def results_facts(scores, solo=None):
    powers = ["England", "France", "Italy", "Germany", "Austria", "Turkey", "Russia"]
    return {"score_issue": None, "taints": [], "outcome": "won" if solo else "drawn", "reason": "year_cap",
            "draw_survivors": None if solo else 7, "phases": [], "gamemaster": {},
            "instrumentation": result_instrumentation({}), "seats": [
        {"slot": i, "power": power, "score": score, "solo": power == solo, "survived": True, "final_centers": 1}
        for i, (power, score) in enumerate(zip(powers, scores, strict=True))]}


def api_game(game_id, players, completed_at=100, status="completed"):
    return {"id": game_id, "status": status, "completed_at": completed_at, "coworld_id": "cow_demo",
            "version": "0.7.12", "created_at": completed_at - 30, "dispatched_at": completed_at - 20,
            "running_at": completed_at - 10, "error_type": None, "variant": "Classic press", "seats": [
                {"slot": i, "player_id": player and f"ply_{player}", "player": player, "filler": player == "Fill",
                 "seed": False, "policy_id": f"pv_{i}", "policy_label": None, "score": None}
                for i, player in enumerate(players)]}


ADA_ENGLAND = ["Ada", "Bert", "Bert", "Bert", "Bert", "Bert", "Fill"]
TIED = [.4, .4, .1, .1, 0, 0, 0]
FRANCE_SOLO = [0, 1, 0, 0, 0, 0, 0]


def snapshot_for(games, facts):
    board = board_facts(last_frame())
    snapshot = {}
    for game, result in zip(games, facts, strict=True):
        snapshot["artifact_results", game["id"]] = {"data": {"state": "ready", "facts": result}}
        snapshot["artifact_replay", game["id"]] = {"data": {"state": "ready", "facts": {"board": board}}}
    return snapshot


class BoardFactsTests(DeskTest):
    def test_contest_rule_held_board_and_coasts(self):
        board = board_facts(last_frame())
        first, second = board["phases"]
        self.assertEqual(first["contested"], [1, 3, 6])
        # Supply centres by owner (unowned excluded), other provinces by the unit standing there.
        self.assertEqual(first["held"], {"1": [6], "2": [4, 5]})
        # A retreating unit holds nothing; Retreats and the stale Finished board are not phases.
        self.assertEqual(second["held"], {"1": [6], "2": [1, 5], "3": [3]})
        self.assertEqual(len(board["phases"]), 2)
        self.assertEqual(set(board["provinces"]), {"1", "3", "4", "5", "6"})
        self.assertEqual(board["provinces"]["5"], ["Paris", True, 2])
        # One power's own bounce is not a contest.
        self.assertEqual(contested_provinces([order(1, 3, "Move", 1), order(1, 4, "Move", 1)], int), [])

    def test_phase_keys_scores_and_split_wins(self):
        self.assertEqual([phase_key(t) for t in (0, 1, 2)], ["S1901", "A1901", "S1902"])
        provinces = board_facts(last_frame())["provinces"]
        scores = centre_scores({"1": [6], "2": [1, 4, 5]}, provinces)  # Gascony is not a centre.
        self.assertAlmostEqual(scores["2"], 4 / 5)
        self.assertAlmostEqual(scores["1"], 1 / 5)
        self.assertEqual(scores["3"], 0)
        self.assertEqual(centre_scores({}, provinces)["4"], 1 / 7)
        self.assertEqual(win_shares({"1": .4, "2": .4, "3": .2}), {"1": .5, "2": .5, "3": 0})


class BoardReportTests(DeskTest):
    def report_inputs(self):
        games = {g["id"]: g for g in (api_game("g1", ADA_ENGLAND, 100), api_game("g2", ADA_ENGLAND, 200))}
        conflict = api_game("g3", ADA_ENGLAND)
        conflict["seats"][0]["score"] = .9  # The API disagrees with results: quarantined.
        games["g3"] = conflict
        waiting = api_game("g4", ADA_ENGLAND)
        games["g4"] = waiting
        snapshot = snapshot_for(games.values(), [results_facts(TIED), results_facts(FRANCE_SOLO, "France"),
                                                 results_facts(TIED), results_facts(TIED)])
        del snapshot["artifact_replay", "g4"]  # Scored, but no parsed board yet.
        return snapshot, games

    def test_all_players_contest_held_score_and_win(self):
        snapshot, games = self.report_inputs()
        entries, pending = map_entries(snapshot, games)
        self.assertEqual((len(entries), pending), (2, 1))
        report = map_report(entries)
        self.assertEqual(report["games"], 2)
        self.assertEqual([b["key"] for b in report["phases"]], ["S1901", "A1901"])
        spring, final = report["phases"][0], report["all"]
        self.assertEqual(spring["contest"]["1"], [2, 2])
        self.assertEqual(final["contest"]["1"], [2, 4])  # Contested phases over all game-phases.
        self.assertEqual(final["held"]["5"], {"2": 4})
        self.assertEqual(spring["held"]["4"], {"2": 2})
        # In a phase, the most supply centres wins; France leads alone in autumn (Spain and Paris).
        self.assertEqual(spring["win"]["1"]["rate"], .5)
        self.assertEqual(report["phases"][1]["win"]["2"]["rate"], 1)
        self.assertAlmostEqual(spring["score"]["1"]["mean"], .5)
        # Final: a tie at the top splits one win; a solo takes it whole.
        self.assertEqual(final["win"]["1"], {"rate": .25, "wins": .5, "solos": 0, "n": 2})
        self.assertEqual(final["win"]["2"], {"rate": .75, "wins": 1.5, "solos": 1, "n": 2})
        self.assertAlmostEqual(final["score"]["2"]["mean"], .7)
        self.assertEqual(report["provinces"]["5"], {"name": "Paris", "supply": True, "home": 2})
        # Fillers are not players.
        self.assertEqual([(p["name"], p["games"]) for p in report["players"]], [("Ada", 2), ("Bert", 2)])
        panel = board_map_panel(report, pending)
        self.assertIn("2 scored games", panel["sentence"])
        self.assertIn("1 scored games await a parsed replay", panel["note"])
        self.assertEqual(panel["games"], 2)

    def test_player_filter_uses_only_their_powers_and_games(self):
        snapshot, games = self.report_inputs()
        games["g5"] = api_game("g5", ["Bert"] * 6 + ["Ada"], 300)
        snapshot.update(snapshot_for([games["g5"]], [results_facts(TIED)]))
        entries, _ = map_entries(snapshot, games)
        ada = map_report(entries, "ply_Ada")
        self.assertEqual(ada["games"], 3)
        self.assertEqual(ada["player"], "ply_Ada")
        final = ada["all"]
        self.assertEqual(set(final["score"]), {"1", "7"})  # England twice, Russia once.
        self.assertEqual(final["score"]["1"]["n"], 2)
        self.assertEqual(final["win"]["1"]["rate"], .25)
        self.assertEqual(final["win"]["7"], {"rate": 0, "wins": 0, "solos": 0, "n": 1})
        self.assertEqual(final["contest"]["1"], [3, 6])  # Every game Ada was in.
        bert = map_report(entries, "ply_Bert")
        self.assertEqual(bert["all"]["score"]["2"]["n"], 3)
        self.assertNotIn("7", bert["phases"][0]["score"])  # Bert never played Russia.
        self.assertEqual(map_report(entries, "ply_nobody")["games"], 0)


class BoardRouteTests(DeskTest):
    def test_route_is_cache_only_selection_aware_and_widget_is_linked(self):
        self.store.success("discovery", "all", {"leagues": [{"key": "press", "id": "league_demo",
                                                             "name": "Invented league"}]}, self.now)
        games = [api_game("ereq_a", ADA_ENGLAND, self.now - 100), api_game("ereq_b", ADA_ENGLAND, self.now - 3 * 86400)]
        self.store.success("episodes", "round_demo", {"league_id": "league_demo", "round_id": "round_demo",
                                                     "rows": games}, self.now)
        for (name, scope), value in snapshot_for(games, [results_facts(TIED), results_facts(FRANCE_SOLO, "France")]
                                                 ).items():
            self.store.success(name, scope, value["data"], self.now)
        with patch("league_desk.artifacts.read_json_file", side_effect=AssertionError("parsing forbidden")), \
                patch.object(Api, "artifact", side_effect=AssertionError("download forbidden")), \
                patch("league_desk.server.time.time", return_value=self.now):
            client = TestClient(create_app(self.store), base_url="http://127.0.0.1:8660")
            report = client.get("/board-map?league=press&range=all").json()
            self.assertEqual((report["games"], report["pending"]), (2, 0))
            self.assertEqual(client.get("/board-map?league=press&range=24h").json()["games"], 1)
            self.assertEqual(client.get("/board-map?league=gunboat&range=all").json()["games"], 0)
            player = client.get("/board-map?league=press&range=all&player=ply_Ada").json()
            self.assertEqual(list(player["all"]["score"]), ["1"])
            self.assertEqual(client.get("/board-map?version=cow_unknown").status_code, 422)
            page = client.get("/?league=press&range=all").text
            self.assertIn('data-widget="board-map"', page)
            self.assertIn('data-src="/board-map?league=press&amp;range=all&amp;version=all&amp;games=2"', page)
            self.assertNotIn('data-swap="Contested provinces"', page)
            self.assertNotIn('data-swap="Score by power, all players"', page)
            self.assertIn('data-swap="Score by policy and power"', page)
