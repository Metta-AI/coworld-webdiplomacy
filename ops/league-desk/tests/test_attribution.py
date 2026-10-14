import copy
from unittest.mock import patch

import httpx
from helpers import DeskTest

from league_desk.api import Api, ApiError
from league_desk.attribution import attempts, daily_spend, seat_models
from league_desk.attribution_metrics import attributed_models, daily_panels, reconciliation
from league_desk.game_metrics import day
from league_desk.spend_metrics import spending_panels
from league_desk.sql import ATTRIBUTION_COLUMNS, attribution_rows, query

LEAGUE = "league_00000000-0000-0000-0000-000000000001"
EPISODE = "00000000-0000-0000-0000-000000000002"
POLICY = "00000000-0000-0000-0000-000000000003"
COWORLD = "cow_00000000-0000-0000-0000-000000000004"


def provider(now, **changes):
    return {"episode": EPISODE, "slot": 0, "model": "invented/resolved", "player_id": "ply_Ada",
            "player": "Same display name", "policy_id": POLICY, "policy": "Invented policy",
            "policy_version_id": POLICY, "version": 1, "created_at": now - 100, "coworld_id": COWORLD,
            "calls": 100, "failed": 1, "usd": 2, "failure_day": day(now), **changes}


class AttributionTests(DeskTest):
    def api_for(self, kind, rows):
        def request(method, path, json=None, timeout=None):
            self.assertEqual((method, path), ("POST", "/sql/query"))
            self.assertEqual(timeout, 25)
            self.assertTrue(json["query"].startswith(("SELECT", "WITH")))
            return httpx.Response(200, json={"columns": ATTRIBUTION_COLUMNS[kind],
                "rows": [[r[k] for k in ATTRIBUTION_COLUMNS[kind]] for r in rows]})
        return Api(request)

    def daily_row(self, **changes):
        return {"league_id": LEAGUE, "source": "tournament", "day": day(self.now),
                "compute": 3, "llm": 2, "week_compute": 3, "week_llm": 2, **changes}

    def test_templates_validate_ids_windows_and_cursors(self):
        for kind in ATTRIBUTION_COLUMNS:
            sql = query(kind, [LEAGUE], start=int(self.now)-86400, end=int(self.now))
            self.assertIn(LEAGUE, sql)
            self.assertIn("LIMIT 500", sql)
            self.assertNotIn("SELECT * FROM credentials", sql)
            with self.assertRaises(ApiError):
                query(kind, ["league_bad' OR true"], start=1, end=100)
            with self.assertRaises(ApiError):
                query(kind, [LEAGUE], start="1; DROP", end=100)
            with self.assertRaises(ApiError):
                query(kind, [LEAGUE], start=1, end=40*86400)
        sql = query("daily_spend", [LEAGUE], start=int(self.now)-30*86400, end=int(self.now))
        self.assertIn("America/Los_Angeles", sql)
        self.assertIn("interval '7 days'", sql)
        self.assertIn("COALESCE(estimated_cost_usd,cost_usd)", sql)
        self.assertIn("job_request_id", query("attempts", [LEAGUE], start=1, end=100))
        with self.assertRaises(ApiError):
            query("seat_models", [LEAGUE], (EPISODE, 0, "x'; SELECT"), start=1, end=100)

    def test_daily_parse_and_48_hour_corrections_replace_snapshot(self):
        rows = [self.daily_row(), self.daily_row(day=day(self.now-2*86400), llm=8)]
        api = self.api_for("daily_spend", rows)
        self.collector.poll("daily_spend", LEAGUE, lambda: daily_spend(api, LEAGUE, self.now), floor=900)
        self.now += 899
        self.collector.poll("daily_spend", LEAGUE, lambda: self.fail("floor bypassed"), floor=900, force=True)
        rows[:] = [self.daily_row(llm=1, week_llm=1)]
        self.now += 2
        self.collector.poll("daily_spend", LEAGUE, lambda: daily_spend(api, LEAGUE, self.now), floor=900)
        actual = self.store.source("daily_spend", LEAGUE)["data"]
        self.assertEqual(actual["rows"], rows)
        self.assertEqual(actual["end"] - actual["start"], 30*86400)
        rows[0]["llm"] = None
        with self.assertRaises(ValueError):
            daily_spend(api, LEAGUE, self.now)

    def test_seat_models_preserve_no_calls_and_stable_ids(self):
        rows = [provider(self.now, usd="2.00"), provider(self.now, slot=1, model="", calls=0, failed=0, usd=0)]
        result = seat_models(self.api_for("seat_models", rows), LEAGUE, self.now)
        self.assertEqual(result["rows"][0]["policy_version_id"], POLICY)
        self.assertEqual(result["rows"][0]["coworld_id"], COWORLD)
        self.assertEqual(result["rows"][1]["usd"], 0)
        rows[0]["failed"] = 101
        with self.assertRaises(ValueError):
            seat_models(self.api_for("seat_models", rows), LEAGUE, self.now)

    def test_attempt_parse_includes_pre_provider_failures_and_refusals(self):
        raw = {"episode": EPISODE, "slot": 0, "model": "invented/requested", "policy_version_id": POLICY,
               "attempts": 120, "not_ok": 25, "refused": 3, "failure_day": day(self.now)}
        result = attempts(self.api_for("attempts", [raw]), LEAGUE, self.now)
        data = seat_models(self.api_for("seat_models", [provider(self.now)]), LEAGUE, self.now)
        model, alerts, seats, labels = attributed_models(data, result, [], 0, self.now, "all")
        self.assertIn("25/120 attempts not OK", alerts[0]["message"])
        self.assertEqual(model["rows"][0][5], 1)
        self.assertEqual(model["rows"][0][8], 25)
        self.assertEqual(seats["rows"][0]["estimated"], 2)
        self.assertEqual(labels[POLICY], "invented/resolved")
        self.assertIn("invented/requested", model["rows"][0][2])
        self.assertFalse(attributed_models(data, {}, [], self.now, self.now, "all")[2]["rows"])
        self.assertFalse(attributed_models(data, result, [], 0, self.now, "cow_other")[2]["rows"])

    def test_multiple_models_do_not_multiply_seats_or_mix_same_labels(self):
        raw = [provider(self.now), provider(self.now, model="invented/other", usd=3),
               provider(self.now, slot=1, player_id="ply_Bert", model="", calls=0, failed=0, usd=0,
                        policy_version_id="00000000-0000-0000-0000-000000000005")]
        data = seat_models(self.api_for("seat_models", raw), LEAGUE, self.now)
        model, _, seats, labels = attributed_models(data, {}, [], 0, self.now, "all")
        self.assertEqual(len(model["rows"]), 2)
        self.assertEqual(seats["rows"][0]["estimated"], 5)
        self.assertEqual(model["rows"][0][3], 1)
        self.assertEqual(labels["00000000-0000-0000-0000-000000000005"], "No provider calls observed")
        self.assertEqual(model["rows"][0][7], "unknown")
        data["rows"].append({**data["rows"][0], "slot": 2, "model": "", "calls": 0, "failed": 0, "usd": 0})
        labels = attributed_models(data, {}, [], 0, self.now, "all")[3]
        self.assertNotIn("No provider calls observed", labels[POLICY])

    def test_daily_reconciliation_and_budget_observations(self):
        data = {"rows": [self.daily_row(compute=20, week_compute=3)], "start": self.now-30*86400}
        api = {"rows": [{"source": "tournament", "compute_cost_usd": 3, "llm_estimated_cost_usd": 2}]}
        self.assertIn("reconcile to the API", reconciliation(data, api))
        api["rows"][0]["compute_cost_usd"] = 3.02
        self.assertIn("mismatch", reconciliation(data, api))
        budget = {"history": [{"data": {"day": day(self.now), "limit": 40}}]}
        daily, comparison = daily_panels(data, api, budget, 0, self.now)
        self.assertIn("mismatch", daily["note"])
        self.assertEqual(daily["chart"]["budgets"][0]["value"], 40)
        self.assertIn("$22.00", daily["sentence"])
        self.assertEqual(comparison["chart"]["data"][0]["series"], "League rounds")
        self.assertIn("pending", reconciliation(data, {}))

    def test_keyset_full_page_and_overflow_never_succeed_partially(self):
        raw = provider(self.now)
        api = self.api_for("seat_models", [raw])
        calls = []
        original = api.select

        def select(*args, **kwargs):
            calls.append(args[2])
            return original(*args, **kwargs) if len(calls) == 1 else {
                "columns": ATTRIBUTION_COLUMNS["seat_models"], "rows": []}
        api.select = select
        with patch("league_desk.sql.SQL_PAGE_SIZE", 1):
            self.assertEqual(len(attribution_rows(api, "seat_models", LEAGUE, 1, 100)), 1)
            self.assertEqual(calls[1], (EPISODE, 0, "invented/resolved"))
            with self.assertRaises(ApiError):
                attribution_rows(self.api_for("daily_spend", [self.daily_row()]), "daily_spend", LEAGUE, 1, 100)

    def test_attempt_timeout_splits_disjoint_creation_windows(self):
        calls = []

        class WindowApi:
            def select(self, kind, ids, after, *, start, end):
                calls.append((start, end))
                if end-start > 86400:
                    raise ApiError("API returned HTTP 408")
                return {"columns": ATTRIBUTION_COLUMNS["attempts"],
                        "rows": [[POLICY, "invented", 10, 2, 1, "2027-01-15"]]}

        rows = attribution_rows(WindowApi(), "attempts", LEAGUE, 1, 2*86400+1)
        self.assertEqual(rows[0]["attempts"], 20)
        self.assertEqual(calls[1][1], calls[2][0])
        self.assertEqual(rows[0]["not_ok"], 4)

    def test_timeout_retains_last_snapshot_and_persisted_floor(self):
        self.store.success("attempts", LEAGUE, {"rows": []}, self.now-901)
        api = Api(lambda *args, **kwargs: httpx.Response(408))
        self.collector.poll("attempts", LEAGUE, lambda: attempts(api, LEAGUE, self.now), floor=900)
        state = self.store.source("attempts", LEAGUE)
        self.assertEqual(state["data"], {"rows": []})
        self.assertIn("408", state["error"])
        self.assertGreaterEqual(state["next_due"], self.now+900)

    def test_standings_costs_include_covered_zeros_once_per_game(self):
        data = seat_models(self.api_for("seat_models", [provider(self.now)]), LEAGUE, self.now)
        self.store.success("seat_models", LEAGUE, data, self.now)
        game = {"id": "ereq_"+EPISODE, "coworld_id": COWORLD, "created_at": self.now-100,
                "completed_at": self.now-1, "status": "completed", "seats": [
                    {"slot": 0, "player_id": "ply_Ada", "player": "Ada", "filler": False}]}
        competition = {"episode_sources": {"round_invented": {"data": {"rows": [game]}}}}
        result = spending_panels(self.store.snapshot(), {"id": LEAGUE, "key": "press"}, self.now, competition)
        self.assertEqual(result["player_costs"]["ply_Ada"], [2])
        self.assertEqual(result["policy_models"][POLICY], "invented/resolved")
        different = copy.deepcopy(data)
        different["rows"][0].update(usd=0, calls=0, failed=0, model="")
        self.store.success("seat_models", LEAGUE, different, self.now)
        result = spending_panels(self.store.snapshot(), {"id": LEAGUE, "key": "press"}, self.now, competition)
        self.assertEqual(result["player_costs"]["ply_Ada"], [0])
        self.assertIn("No provider calls observed", result["spend_panels"]["Models in use"]["sentence"])
