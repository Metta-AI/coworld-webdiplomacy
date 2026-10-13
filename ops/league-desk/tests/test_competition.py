import copy
from datetime import datetime, timezone

import httpx
from helpers import DeskTest

from league_desk.api import Api, ApiError
from league_desk.collector import Collector
from league_desk.competition import episode, round_row, scan
from league_desk.competition_metrics import (
    exposure,
    histories,
    rating_delta,
    rating_history,
    standings,
    submission_series,
)
from league_desk.game_metrics import (
    day,
    episode_timing,
    game_durations,
    head_to_head,
    player_scores,
    quantile,
    round_durations,
    throughput,
)
from league_desk.panels import competition_panels
from league_desk.store import Store


def iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


def raw_game(now, game_id="ereq_example"):
    return {"id": game_id, "episode_id": "ep_example", "coworld_id": "cow_demo", "coworld_version": "9.9.1",
            "variant_name": "classic-press", "status": "completed", "error_type": None,
            "created_at": iso(now - 600), "dispatched_at": iso(now - 540),
            "running_at": iso(now - 480), "completed_at": iso(now - 60),
            "participants": [{"position": pos, "player_id": player, "player_name": player,
                              "policy_version_id": "pv_" + player, "is_filler": False, "is_seed": False}
                             for pos, player in enumerate(("Ada", "Bert"))],
            "participant_scores": [{"position": 1, "score": .2}, {"position": 0, "score": .8}]}


def rating_row(player="Ada", **changes):
    return {"player_id": player, "player": player, "division_id": "div_demo", "mu": 30, "sigma": 2,
            "rating": 24, "rounds_played": 2, "last_round_id": "round_demo", "policies": ["pv_" + player],
            "failures": 0, "failure_limit": 3, "current_policy_id": "pv_" + player, **changes}


class CompetitionTests(DeskTest):
    def enrich(self):
        self.responses["/v2/leagues/league_demo/settings"]["settings"]["ladder"] = {
            "divisions": [{"division_id": "div_demo", "disqualify_after_consecutive_failures": 3}],
            "scheduler": {"min_episodes_per_entrant": 4}}
        self.responses["/v2/rounds"]["entries"][0].update(
            created_at=iso(self.now - 700), completed_at=iso(self.now - 30), status="completed",
            round_config={"entrant_attributions": [{"subject_type": "player", "subject_id": name}
                                                   for name in ("Ada", "Bert", "Cleo")]})
        self.responses["/v2/rounds/round_demo/episodes"]["entries"] = [raw_game(self.now)]
        self.responses["/v2/league-policy-memberships"] = [{
            "id": "member_demo", "player": {"id": "Ada", "name": "Ada"},
            "policy_version": {"id": "pv_Ada", "policy": {"name": "Invented Policy"}, "version": 1},
            "division": {"id": "div_demo"}, "status": "competing", "substatus": "active",
            "is_champion": True, "created_at": iso(self.now - 800)}]
        self.responses["/v2/league-submissions"] = [{
            "id": "sub_demo", "player": {"id": "Ada", "name": "Ada"},
            "policy_version": {"id": "pv_Ada"}, "status": "processed", "created_at": iso(self.now - 800)}]
        self.responses["/v2/divisions/div_demo/leaderboard/summary"] = {"snapshot_version": "one"}
        self.responses["/v2/divisions/div_demo/leaderboards"] = {
            "default_view_key": "ratings", "views": [{"key": "ratings", "rows": [{
                "subject_type": "player", "subject_id": "Ada", "subject_name": "Ada",
                "policy_version_ids": ["pv_Ada"], "values": {
                    "mu": 30, "sigma": 2, "rating": 24, "rounds_played": 2}}]}]}
        self.responses["/v2/leagues/league_demo/commissioner-state"] = {"version": 1, "state": {"standings": [{
            "division_id": "div_demo", "standing": {"subject_type": "player", "subject_id": "Ada", "ranking": {
                "consecutive_failures": 2, "current_policy_version_id": "pv_Ada", "last_round_id": "round_demo"}}}]}}

    def test_collect_and_restart_deduplicates_ratings_and_scores(self):
        self.enrich()
        self.collector.once()
        snapshot = self.store.snapshot(True)
        self.assertTrue(all(not s["error"] for s in snapshot.values()))
        self.assertEqual(len(snapshot["ratings", "league_demo"]["history"]), 1)
        self.assertEqual(snapshot["episodes", "round_demo"]["data"]["rows"][0]["seats"][0]["score"], .8)
        self.now += 301
        store = Store(self.store.directory)
        store.initialize()
        Collector(store, self.api, clock=lambda: self.now).once()
        self.assertEqual(len(store.snapshot(True)["ratings", "league_demo"]["history"]), 1)
        self.assertTrue(all(c[0] == "GET" for c in self.calls))

    def test_chart_labels_are_escaped_and_page_reads_only_cache(self):
        from fastapi.testclient import TestClient

        from league_desk.server import create_app

        self.enrich()
        label = "<img src=x onerror=bad()>"
        self.responses["/v2/league-policy-memberships"][0]["player"]["name"] = label
        self.responses["/v2/divisions/div_demo/leaderboards"]["views"][0]["rows"][0]["subject_name"] = label
        self.collector.once()
        self.calls.clear()
        response = TestClient(create_app(self.store), base_url="http://127.0.0.1").get("/")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("<img", response.text)
        self.assertIn("&lt;img", response.text)
        self.assertIn(r"\u003cimg", response.text)
        self.assertNotIn("unsafe-inline", response.headers["content-security-policy"])
        self.assertEqual(self.calls, [])

    def test_episode_work_is_bounded_and_remaining_rounds_catch_up(self):
        self.enrich()
        raw = self.responses["/v2/rounds"]["entries"][0]
        self.responses["/v2/rounds"]["entries"] = []
        for index in range(6):
            key = f"round_extra{index}"
            self.responses["/v2/rounds"]["entries"].append({**raw, "id": key})
            self.responses[f"/v2/rounds/{key}/episodes"] = {"entries": [], "next_cursor": None}
        self.collector.once()
        self.assertEqual(sum(key[0] == "episodes" for key in self.store.snapshot()), 4)
        self.now += 61
        self.collector.once()
        self.assertEqual(sum(key[0] == "episodes" for key in self.store.snapshot()), 6)

    def test_rating_race_retains_last_observation(self):
        self.enrich()
        self.collector.once()
        old = self.store.source("ratings", "league_demo")
        self.now += 301
        calls = 0
        request = self.api.request

        def racing(method, path, params=None):
            nonlocal calls
            if path.endswith("/summary"):
                calls += 1
                return httpx.Response(200, json={"snapshot_version": str(calls)})
            return request(method, path, params)

        self.api.request = racing
        self.collector.once()
        new = self.store.source("ratings", "league_demo")
        self.assertEqual(new["data"], old["data"])
        self.assertIn("changed during", new["error"])
        self.assertEqual(calls, 4)

    def test_completion_triggers_rating_poll_before_five_minutes(self):
        self.enrich()
        self.collector.once()
        self.now += 61
        extra = copy.deepcopy(self.responses["/v2/rounds"]["entries"][0])
        extra["id"] = "round_other"
        self.responses["/v2/rounds"]["entries"].append(extra)
        self.responses["/v2/rounds/round_other/episodes"] = {"entries": [], "next_cursor": None}
        self.calls.clear()
        self.collector.once()
        self.assertTrue(any(path.endswith("/leaderboards") for _, path, _ in self.calls))

    def test_bounded_scan_resumes_after_restart_and_preserves_hidden_round(self):
        raw = copy.deepcopy(self.responses["/v2/rounds"]["entries"][0])
        pages = iter([{"entries": [{**raw, "id": "round_a"}], "next_cursor": "b"},
                      {"entries": [{**raw, "id": "round_b"}], "next_cursor": "c"},
                      {"entries": [{**raw, "id": "round_c"}], "next_cursor": None}])
        calls = []

        def request(method, path, params):
            calls.append(params)
            return httpx.Response(200, json=next(pages))

        first = scan(Api(request), "/v2/rounds", {}, round_row, None, self.now)
        self.assertFalse(first["complete"])
        self.store.success("rounds", "league_demo", first, self.now)
        self.store.initialize()
        second = scan(Api(request), "/v2/rounds", {}, round_row,
                      self.store.source("rounds", "league_demo"), self.now + 61)
        self.assertTrue(second["complete"])
        self.assertEqual(calls[-1]["cursor"], "c")
        # A reset can reuse a round number, but cannot overwrite a different round ID.
        self.responses["/v2/rounds"] = {"entries": [{**raw, "id": "round_d"}], "next_cursor": None}
        third = scan(self.api, "/v2/rounds", {}, round_row, {"data": second}, self.now + 122)
        self.assertEqual(len(third["rows"]), 4)
        self.assertEqual(sum(r["listed"] for r in third["rows"]), 1)

    def test_failed_walk_restarts_head_and_never_discards_last_good_rows(self):
        raw = self.responses["/v2/rounds"]["entries"][0]
        old = {"data": {"cursor": "old", "seen": [raw["id"]], "cursors": ["old"],
                        "rows": [round_row(raw)]}, "error": "stale cursor"}
        data = scan(self.api, "/v2/rounds", {}, round_row, old, self.now)
        self.assertNotIn("cursor", self.calls[-1][2])
        self.assertTrue(data["complete"])
        self.responses["/v2/rounds"]["next_cursor"] = "repeat"
        with self.assertRaises(ApiError):
            scan(self.api, "/v2/rounds", {}, round_row, None, self.now)

    def test_episode_page_failure_keeps_last_good_games(self):
        self.enrich()
        self.collector.once()
        old = self.store.source("episodes", "round_demo")["data"]
        self.now += 301
        self.responses["/v2/rounds/round_demo/episodes"] = httpx.Response(500)
        self.collector.once()
        self.assertEqual(self.store.source("episodes", "round_demo")["data"], old)

    def test_rate_limit_stops_inside_competition_group(self):
        self.enrich()
        self.responses["/v2/rounds/round_demo/episodes"] = httpx.Response(
            429, headers={"x-ratelimit-retry-after": "900"})
        self.collector.once()
        self.assertFalse(any(path.endswith("/leaderboards") for _, path, _ in self.calls))
        self.assertEqual(self.store.retry_not_before(), self.now + 900)

    def test_streak_alert_requires_matching_current_active_policy(self):
        self.enrich()
        self.collector.once()
        snapshot = self.store.snapshot(True)
        view = competition_panels(snapshot, {"id": "league_demo"}, self.now)
        self.assertTrue(any("consecutive" in a for a in view["competition_alerts"]))
        snapshot["memberships", "league_demo"]["data"]["rows"][0]["substatus"] = "benched"
        view = competition_panels(snapshot, {"id": "league_demo"}, self.now)
        self.assertFalse(any("consecutive" in a for a in view["competition_alerts"]))

    def test_new_sources_private_fields_are_discarded(self):
        self.enrich()
        for name in ("/v2/league-submissions", "/v2/league-policy-memberships"):
            self.responses[name][0]["notes"] = "secret-private-notes"
        self.collector.once()
        self.assertNotIn("secret-private-notes", str(self.store.snapshot(True)))

    def test_rating_poll_gap_is_observed_without_backfill(self):
        self.enrich()
        self.collector.once()
        self.now += 1201
        self.collector.once()
        history = self.store.snapshot(True)["ratings", "league_demo"]["history"]
        points = rating_history(history)
        self.assertEqual(len(points), 2)
        self.assertTrue(points[-1]["gap"])
        self.assertEqual(points[-1]["segment"], 1)


class MetricsTests(DeskTest):
    def game(self, **changes):
        return {**episode(raw_game(self.now)), **changes}

    def test_score_join_missing_score_filler_and_multiple_owned_seats(self):
        raw = raw_game(self.now)
        raw["participants"].append({**raw["participants"][0], "position": 2})
        raw["participant_scores"].append({"position": 2, "score": .4})
        game = episode(raw)
        self.assertAlmostEqual(player_scores([game])[0]["score"], .6)
        game["seats"][2]["score"] = None
        self.assertEqual([r["player_id"] for r in player_scores([game])], ["Bert"])
        game["seats"][2]["filler"] = True
        self.assertEqual(player_scores([game])[0]["score"], .8)
        raw["participant_scores"].append({"position": 2, "score": 0})
        with self.assertRaises(ValueError):
            episode(raw)

    def test_head_to_head_ties_reverse_denominator_and_five_distinct_games(self):
        games = [self.game(id=f"ereq_{i}") for i in range(5)]
        games[0]["seats"][0]["score"] = .2
        cells = head_to_head(games)["cells"]
        forward = next(r for r in cells if r["a"] == "Ada" and r["b"] == "Bert")
        reverse = next(r for r in cells if r["a"] == "Bert" and r["b"] == "Ada")
        self.assertEqual((forward["n"], reverse["n"], forward["ties"]), (5, 5, 1))
        self.assertEqual((forward["share"], reverse["share"]), (.8, 0))
        self.assertTrue(all(r["share"] is None for r in head_to_head(games[:4])["cells"]))
        self.assertTrue(all(r["share"] is None for r in head_to_head([games[0]] * 10)["cells"]))

    def test_failed_games_and_missing_scores_never_enter_matchups(self):
        game = self.game(status="failed")
        self.assertEqual(head_to_head([game])["cells"], [])
        game = self.game()
        game["seats"][0]["score"] = None
        self.assertFalse(any(r["n"] for r in head_to_head([game])["cells"]))

    def test_linear_percentile_and_singleton(self):
        self.assertEqual(quantile([10, 20], .9), 19)
        self.assertEqual(quantile([7], .9), 7)
        self.assertIsNone(quantile([], .5))
        self.assertIn("7.00", game_durations([self.game()])["sentence"])

    def test_representative_timing_is_one_real_game_not_component_medians(self):
        games = [self.game(id="one", created_at=0, dispatched_at=60, running_at=120, completed_at=720),
                 self.game(id="two", created_at=0, dispatched_at=120, running_at=420, completed_at=600),
                 self.game(id="three", created_at=0, dispatched_at=180, running_at=600, completed_at=900)]
        result = episode_timing(games)
        self.assertEqual([r["value"] for r in result["chart"]["data"]], [1, 1, 10])
        self.assertIn("representative", result["sentence"])
        self.assertIn("No completed", episode_timing([self.game(dispatched_at=None)])["sentence"])
        self.assertIn("No completed", episode_timing([self.game(dispatched_at=self.now + 5)])["sentence"])

    def test_queue_and_filler_readings_use_the_displayed_threshold_inputs(self):
        game = self.game(created_at=0, dispatched_at=360, running_at=420, completed_at=600)
        self.assertIn("Median queue time is 6.00", episode_timing([game])["sentence"])
        game["seats"][0]["filler"] = True
        result = exposure([], [game], [], {}, [], self.now, None)
        self.assertEqual(result["sentence"], "1 of 2 observed seats are fillers.")
        game["seats"][0]["filler"] = False
        self.assertIn("active", exposure([], [game], [], {}, [], self.now, None)["sentence"])

    def test_rounds_censored_skips_and_no_retroactive_interval(self):
        base = {"id": "r", "number": 1, "created_at": 0, "completed_at": 600,
                "status": "completed", "skip_kind": None}
        result = round_durations([base, {**base, "status": "skipped", "skip_kind": "budget"},
                                  {**base, "completed_at": None, "status": "running"}],
                                 [{"observed_at": 1, "data": {"round_interval_minutes": 1}}], 800)
        self.assertEqual(result["rows"][0][-1], "unknown")
        self.assertIn("1 completed rounds", result["sentence"])
        self.assertIn("1 unfinished, 1 skipped", result["note"])
        result = round_durations([base], [{"observed_at": 0, "data": {"round_interval_minutes": 1}}], 800)
        self.assertIn("exceeded", result["sentence"])

    def test_rating_gaps_resets_and_baseline_tolerance(self):
        start = self.now - 86400
        history = [{"observed_at": start, "data": {"rows": [rating_row()]}},
                   {"observed_at": self.now, "data": {"rows": [rating_row(rating=25, rounds_played=3)]}}]
        points = rating_history(history)
        self.assertEqual(rating_delta(points, "div_demo", "Ada", self.now), (1, start))
        self.assertEqual(rating_delta(points, "div_demo", "Ada", self.now + 601), (None, None))
        history[-1]["data"]["rows"][0]["rounds_played"] = 0
        points = rating_history(history)
        self.assertTrue(points[-1]["reset"])
        self.assertEqual(rating_delta(points, "div_demo", "Ada", self.now), (None, None))
        history[-1]["data"]["rows"][0]["rounds_played"] = 5
        self.assertTrue(rating_history(history)[-1]["gap"])

    def test_interval_sentence_widening_before_narrowing(self):
        history = [{"observed_at": self.now, "data": {"rows": [rating_row(), rating_row("Bert")]}},
                   {"observed_at": self.now + 60, "data": {"rows": [rating_row(sigma=3), rating_row("Bert", sigma=1)]}}]
        result = histories(rating_history(history))
        self.assertIn("Ada's", result["Rating interval over time"]["sentence"])
        self.assertIn("widened", result["Rating interval over time"]["sentence"])

    def test_incomplete_submissions_do_not_claim_prior_zero(self):
        result = submission_series([], self.now, False)
        self.assertIn("incomplete", result["sentence"])
        self.assertNotIn("prior", result["sentence"])
        self.assertIn("prior", submission_series([], self.now, True)["sentence"])

    def test_exposure_includes_known_eligible_zero_games_only(self):
        game = self.game()
        rd = {"id": "round_demo", "number": 1, "status": "completed", "entrants": ["Ada", "Cleo"]}
        result = exposure([], [game], [rd], {"round_demo": {"data": {"rows": [game]}}}, [], self.now, 4)
        self.assertEqual([r["games"] for r in result["exposures"]], [1, 0])
        self.assertEqual(exposure([], [game], [rd], {}, [], self.now, None)["exposures"], [])
        rd["entrants"] = None
        self.assertEqual(exposure([], [game], [rd], {}, [], self.now, None)["exposures"], [])

    def test_pacific_day_and_throughput_failed_separate(self):
        self.assertEqual(day(datetime(2027, 1, 2, 1, tzinfo=timezone.utc).timestamp()), "2027-01-01")
        result = throughput([self.game(), self.game(id="other", status="failed")])
        self.assertIn("1 failed games; 1 completed", result["sentence"])
        self.assertEqual(len(result["rows"]), 2)

    def test_empty_and_missing_rating_model_cost_are_not_zero(self):
        member = {"player": "Ada", "player_id": "Ada", "division_id": "div_demo", "status": "competing",
                  "policy": "Invented", "version": 1, "substatus": "benched"}
        result = standings([member], [], [], [], [], self.now, False)
        self.assertEqual(result["rows"][0][2], "unknown")
        self.assertEqual(result["rows"][0][-2:], ["not observed", "unknown"])
        self.assertEqual(result["chart"]["data"], [])
