import copy
from unittest.mock import patch

import httpx
from helpers import DeskTest
from test_competition import iso, raw_game

from league_desk.api import Api, ApiError
from league_desk.competition import episode
from league_desk.freshness import age_label, annotate
from league_desk.spend_metrics import (
    model_usage,
    override_frequency,
    request_durations,
    request_series,
    seat_spend,
    source_spend,
    spending_panels,
    unit_costs,
)
from league_desk.spending import costs, models, overrides, request_history, request_row, seats
from league_desk.sql import OVERRIDES, query, select_rows
from league_desk.store import Store

GAME = "ereq_00000000-0000-0000-0000-000000000001"
OTHER = "ereq_00000000-0000-0000-0000-000000000002"
REQUEST = "xreq_00000000-0000-0000-0000-000000000003"


class SlowPollTests(DeskTest):
    def test_slow_floor_survives_failure_restart_and_force(self):
        calls = []

        def fetch():
            calls.append(1)
            raise ApiError("API returned HTTP 500")

        self.collector.poll("costs", "league_demo", fetch, cadence=900, floor=900)
        self.assertEqual(self.store.source("costs", "league_demo")["next_due"], self.now + 900)
        Store(self.store.directory).initialize()
        self.now += 899
        self.collector.poll("costs", "league_demo", fetch, cadence=900, floor=900, force=True)
        self.assertEqual(len(calls), 1)
        self.now += 1
        self.collector.poll("costs", "league_demo", fetch, cadence=900, floor=900, force=True)
        self.assertEqual(len(calls), 2)

    def test_reservation_survives_process_interruption_before_response(self):
        def interrupted():
            raise SystemExit()

        with self.assertRaises(SystemExit):
            self.collector.poll("models", "all", interrupted, floor=900)
        self.assertEqual(self.store.source("models", "all")["attempted_at"], self.now)
        self.now += 60
        self.collector.poll("models", "all", lambda: self.fail("floor bypassed"), floor=900, force=True)

    def test_successful_cost_refresh_replaces_instead_of_accumulates(self):
        payload = {
            "period": "week",
            "leagues": [
                {
                    "league_id": "league_demo",
                    "source": "tournament",
                    "compute_cost_usd": 2,
                    "llm_estimated_cost_usd": 3,
                    "combined_estimated_cost_usd": 5,
                }
            ],
        }
        self.responses["/admin/costs/leagues"] = payload
        for _ in range(2):
            self.collector.poll("costs", "league_demo", lambda: costs(self.api, "league_demo"), cadence=900, floor=900)
            self.now += 901
        data = self.store.source("costs", "league_demo")["data"]
        self.assertEqual(data["rows"][0]["combined_estimated_cost_usd"], 5)
        self.assertIn("$5.00", source_spend(data)["sentence"])
        self.assertIn("unavailable", source_spend({})["sentence"])

    def test_inconsistent_cost_components_retain_last_good_data(self):
        self.responses["/admin/costs/leagues"] = {
            "period": "week",
            "leagues": [
                {
                    "league_id": "league_demo",
                    "source": "tournament",
                    "compute_cost_usd": 2,
                    "llm_estimated_cost_usd": 3,
                    "combined_estimated_cost_usd": 5,
                }
            ],
        }
        self.collector.poll("costs", "league_demo", lambda: costs(self.api, "league_demo"))
        self.now += 901
        self.responses["/admin/costs/leagues"]["leagues"][0]["combined_estimated_cost_usd"] = 8
        self.collector.poll("costs", "league_demo", lambda: costs(self.api, "league_demo"))
        source = self.store.source("costs", "league_demo")
        self.assertIsNotNone(source["error"])
        self.assertEqual(source["data"]["rows"][0]["combined_estimated_cost_usd"], 5)

    def test_missing_model_amount_is_not_a_healthy_snapshot(self):
        self.responses["/admin/llm-coworld-usage"] = {
            "period": "week",
            "rows": [
                {
                    "coworld": "webdiplomacy",
                    "coworld_id": "cow_demo",
                    "model_id": "Invented model",
                    "role": "player",
                    "source": "xp_request",
                    "policy_name": None,
                    "player_name": None,
                    "invocations": 1,
                    "error_count": 0,
                    "estimated_cost_usd": None,
                }
            ],
        }
        with self.assertRaisesRegex(ValueError, "Incomplete model"):
            models(self.api)


class SqlTests(DeskTest):
    def api_for(self, pages):
        self.sql_calls = []
        remaining = iter(pages)

        def request(method, path, params=None, json=None, timeout=None):
            if method == "GET":
                return httpx.Response(
                    200,
                    json={
                        "columns": [
                            {"name": key}
                            for key in (
                                "episode_request_id",
                                "slot",
                                "bucket_start",
                                "source_system",
                                "role",
                                "invocations",
                                "estimated_cost_usd",
                                "spend_limit_rejections",
                                "experience_request_id",
                                "request_spec",
                            )
                        ]
                    },
                )
            self.sql_calls.append(json["query"])
            page = next(remaining)
            return page if isinstance(page, httpx.Response) else httpx.Response(200, json=page)

        return Api(request)

    def seat_page(self, rows):
        return {
            "columns": ["episode", "slot", "calls", "estimated", "rejections"],
            "rows": rows,
            "row_count": len(rows),
        }

    def test_post_accepts_only_fixed_scoped_templates_before_io(self):
        for kind, ids, after in (
            ("DELETE", [GAME], None),
            ("seats", ["ereq_x';DROP TABLE x"], None),
            ("seats", [], None),
            ("seats", [GAME], (GAME[5:], "0'")),
        ):
            with self.assertRaises(ApiError):
                self.api.select(kind, ids, after)
        self.assertEqual(self.calls, [])
        statement = query("seats", [GAME])
        self.assertTrue(statement.startswith("SELECT "))
        self.assertIn("role = 'player'", statement)
        self.assertIn("GROUP BY episode_request_id, slot", statement)
        self.assertNotIn("request_spec", statement)
        statement = query("overrides", [REQUEST])
        self.assertNotIn("notes", statement)
        self.assertNotIn("roster", statement)

    def test_exact_full_sql_page_requires_next_page_and_keyset(self):
        api = self.api_for(
            [self.seat_page([[GAME[5:], "0", 2, 0.1, 0], [GAME[5:], "1", 1, 0.2, 1]]), self.seat_page([])]
        )
        with patch("league_desk.sql.SQL_PAGE_SIZE", 2):
            data = seats(api, [GAME])
        self.assertEqual(len(self.sql_calls), 2)
        self.assertIn("(episode_request_id, slot) >", self.sql_calls[-1])
        self.assertEqual(sum(r["estimated"] for r in data["rows"]), 0.1 + 0.2)
        self.assertEqual(data["rows"][1]["rejections"], 1)

    def test_missing_seat_amount_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Incomplete seat"):
            seats(self.api_for([self.seat_page([[GAME[5:], "0", 1, None, 0]])]), [GAME])
        statement = query("seats", [GAME])
        self.assertIn("SUM(invocations)::bigint", statement)
        self.assertIn("SUM(spend_limit_rejections)::bigint", statement)

    def test_unscoped_repeated_or_malformed_sql_rows_rejected(self):
        for rows in ([[OTHER[5:], "0", 1, 0.1, 0]], [[GAME[5:], "0", 1, 0.1, 0]] * 2, [[GAME[5:]]]):
            with self.assertRaises(ApiError):
                select_rows(self.api_for([self.seat_page(rows)]), "seats", [GAME])

    def test_timeout_splits_scope_without_guessing_totals(self):
        api = self.api_for([httpx.Response(408), self.seat_page([[GAME[5:], "0", 1, 0.1, 0]]), self.seat_page([])])
        rows = select_rows(api, "seats", [GAME, OTHER])
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(self.sql_calls), 3)
        with self.assertRaisesRegex(ApiError, "408"):
            select_rows(self.api_for([httpx.Response(408)]), "seats", [GAME])

    def test_overrides_read_only_allowlisted_scalars(self):
        values = {
            "end_year": 1905,
            "phase_minutes": {"secret": "never-store"},
            "retreat_build_minutes": None,
            "press": "full",
            "seed": "secret://private",
            "render_maps": False,
        }
        api = self.api_for(
            [{"columns": ["request", *OVERRIDES], "rows": [[REQUEST, *values.values()]], "row_count": 1}]
        )
        result = overrides(api, [REQUEST])
        self.assertEqual(result["rows"][0]["values"], {"end_year": 1905, "press": "full", "render_maps": False})
        self.assertNotIn("never-store", str(result))


class ExperienceTests(DeskTest):
    def row(self, **changes):
        return {
            "id": REQUEST,
            "coworld_id": "cow_demo",
            "coworld_version": "9.9.1",
            "variant_id": "classic-press",
            "requester_user_id": "user_invented",
            "requester": "invented@example.invalid",
            "status": "completed",
            "episode_count": 2,
            "created_at": iso(self.now - 600),
            "started_at": iso(self.now - 550),
            "completed_at": iso(self.now - 60),
            **changes,
        }

    def test_request_backfill_windows_resume_and_keep_private_notes_out(self):
        version = {"id": "cow_demo", "created_at": self.now - 40 * 86400}
        self.responses["/v2/experience-requests"] = {"entries": [self.row(notes="private-notes")], "next_cursor": None}
        first = request_history(self.api, version, None, self.now)
        self.assertFalse(first["backfilled"])
        self.assertNotIn("private-notes", str(first))
        self.responses["/v2/experience-requests"]["entries"] = []
        second = request_history(self.api, version, {"data": first}, self.now + 301)
        self.assertTrue(second["backfilled"])
        self.assertEqual(second["window_end"], first["window_start"])
        self.assertEqual(len(second["rows"]), 1)
        self.assertEqual(second["recent_through"], self.now)
        third = request_history(self.api, version, {"data": second}, self.now + 602)
        self.assertEqual(third["window_end"], self.now + 602)
        self.assertEqual(third["window_start"], self.now + 602 - 7 * 86400)

    def test_timing_panel_discloses_partial_episode_listing(self):
        row = {**request_row(self.row()), "seen_at": self.now}
        snapshot = {}
        for name, scope, data in (
            ("versions", "all", {"rows": [{"id": "cow_demo"}]}),
            ("requests", "cow_demo", {"rows": [row], "backfilled": True}),
            ("request_detail", REQUEST, {**row, "episode_ids": [GAME]}),
        ):
            snapshot[name, scope] = {
                "name": name,
                "data": data,
                "fetched_at": self.now,
                "next_due": self.now + 300,
            }
        result = spending_panels(snapshot, {"id": "league_demo", "key": "press"}, self.now, {"episode_sources": {}})
        timing = result["spend_panels"]["How long they take"]
        self.assertIn("1 request episode listings differ", timing["note"])
        self.assertIn("0/1 listed game details", timing["note"])
        self.assertEqual(timing["missing"], 1)

    def test_override_coverage_tracks_selected_requests_without_aging_old_checks(self):
        row = {**request_row(self.row()), "seen_at": self.now}
        snapshot = {}
        for name, scope, data in (
            ("versions", "all", {"rows": [{"id": "cow_demo"}]}),
            ("requests", "cow_demo", {"rows": [row], "backfilled": True}),
            ("overrides", "all", {"rows": [], "checked_at": {}}),
        ):
            snapshot[name, scope] = {"name": name, "data": data, "fetched_at": self.now,
                                     "next_due": self.now + 300}
        def result():
            return spending_panels(snapshot, {"id": "league_demo", "key": "press"}, self.now,
                                   {"episode_sources": {}})["spend_panels"]["Common config overrides"]
        self.assertEqual(result()["missing"], 1)
        snapshot["overrides", "all"]["data"]["checked_at"][REQUEST] = self.now - 279 * 60
        self.assertEqual(result()["missing"], 0)
        self.assertFalse(result()["stale"])
        self.assertIn("1/1 selected requests inspected", result()["note"])
        row["created_at"] = self.now - 60 * 86400
        snapshot["overrides", "all"]["data"]["checked_at"] = {}
        self.assertEqual(result()["missing"], 0)

    def test_failed_partial_window_restarts_same_bounds(self):
        version = {"id": "cow_demo", "created_at": self.now - 60 * 86400}
        old = {
            "data": {
                "cursor": "bad",
                "window_start": self.now - 50 * 86400,
                "window_end": self.now - 30 * 86400,
                "complete": False,
            },
            "error": "bad cursor",
        }
        self.responses["/v2/experience-requests"] = {"entries": [], "next_cursor": None}
        result = request_history(self.api, version, old, self.now)
        self.assertEqual(result["window_start"], old["data"]["window_start"])
        self.assertNotIn("cursor", self.calls[-1][2])

    def test_requests_not_episodes_and_timing_uses_running_at(self):
        version = {"id": "cow_demo", "created_at": self.now - 86400}
        self.responses["/v2/experience-requests"] = {"entries": [self.row()], "next_cursor": None}
        rows = request_history(self.api, version, None, self.now)["rows"]
        self.assertIn("1 observed requests", request_series(rows, True)["sentence"])
        games = [{**episode(raw_game(self.now)), "request_id": REQUEST, "variant": "Classic (press)"}]
        result = request_durations(rows, games)
        self.assertEqual(result["rows"][0][1:4], ["7.00", 1, "1.00"])
        self.assertEqual(result["rows"][0][4], "9.00")
        result = override_frequency(rows, {"rows": [{"id": REQUEST, "values": {"end_year": 1905}}]})
        self.assertIn("1/1 inspected", result["sentence"])
        self.assertNotIn("shortened", result["sentence"])


class SpendingMetricTests(DeskTest):
    def test_competition_stale_boundary_and_retry_does_not_redefine_it(self):
        deps = [
            {"name": "ratings", "fetched_at": self.now, "next_due": self.now + 300, "data": {}},
            {"name": "rounds", "fetched_at": self.now, "next_due": self.now + 60, "data": {}},
        ]
        for age, stale in ((523, False), (600, False), (601, True)):
            result = {}
            annotate(result, deps, self.now + age)
            self.assertEqual(result["stale"], stale)
        deps[0]["error"] = "failed"
        annotate(result, deps, self.now + 1)
        self.assertTrue(result["stale"])
        self.assertEqual(age_label(523), "9 min old")
        self.assertEqual(age_label(120), "120 s old")

    def test_fresh_chunk_does_not_hide_old_sql_coverage(self):
        source = {
            "name": "seats",
            "fetched_at": self.now,
            "data": {
                "checked_at": {GAME: self.now, OTHER: self.now - 1801},
            },
        }
        result = {}
        annotate(result, [source], self.now, cadence=900)
        self.assertEqual(result["age"], 1801)
        self.assertTrue(result["stale"])
        source["data"]["checked_at"][OTHER] = self.now
        annotate(result, [source], self.now, cadence=900)
        self.assertFalse(result["stale"])

    def test_usage_missing_seats_cap_reference_and_actual_rejections(self):
        game = episode(raw_game(self.now))
        data = {
            "ids": [GAME],
            "eligible": 2,
            "rows": [{"episode": GAME, "slot": 0, "calls": 2, "estimated": 0.95, "rejections": 0}],
        }
        result, amounts, alerts = seat_spend(data, [game], 1)
        self.assertIn("current cap reference", result["sentence"])
        self.assertEqual(alerts, [])
        self.assertNotIn((GAME, 1), amounts)
        data["rows"][0]["rejections"] = 2
        result, _, alerts = seat_spend(data, [game], 1)
        self.assertIn("2 recorded", result["sentence"])
        self.assertEqual(len(alerts), 1)

    def test_model_scope_error_threshold_and_no_model_free_claim(self):
        row = {
            "model": "Invented model",
            "role": "player",
            "source": "xp_request",
            "policy": "Invented policy",
            "player": "Invented player",
            "invocations": 20,
            "error_count": 2,
            "estimated_cost_usd": 0.5,
        }
        result, alerts = model_usage({"rows": [row]})
        self.assertEqual(alerts, [])
        row["error_count"] = 3
        result, alerts = model_usage({"rows": [row]})
        self.assertIn("Family-wide", alerts[0])
        self.assertIn("both leagues", result["note"])
        self.assertEqual(model_usage({})[0]["sentence"], "No model usage observed.")

    def test_unit_costs_do_not_use_uncovered_rounds_or_missing_compute_as_zero(self):
        game = episode(raw_game(self.now))
        other = {**copy.deepcopy(game), "id": OTHER}
        details = {GAME: {"data": {"compute": 2}}, OTHER: {"data": {"compute": None}}}
        rounds = [{"id": "round_demo", "status": "completed"}]
        sources = {"round_demo": {"data": {"rows": [game, other]}}}
        result = unit_costs([game, other], details, rounds, sources)
        self.assertIn("unknown/round", result["sentence"])
        self.assertIn("$2.00/game", result["sentence"])
        self.assertEqual(result["rows"][0][1], "1/2")


class FreshnessScheduleTests(DeskTest):
    def test_finished_detail_uses_daily_schedule_but_errors_still_show(self):
        source = {"name": "detail", "data": {}, "fetched_at": self.now, "next_due": self.now + 86400}
        panel = {}
        annotate(panel, [source], self.now + 18000)
        self.assertFalse(panel["stale"])
        annotate(panel, [source], self.now + 172801)
        self.assertTrue(panel["stale"])
        source["error"] = "failed"
        annotate(panel, [source], self.now + 1)
        self.assertTrue(panel["stale"])

    def test_override_age_is_newest_pass_not_immutable_chunk(self):
        source = {"name": "overrides", "data": {"checked_at": {REQUEST: self.now - 279 * 60}},
                  "fetched_at": self.now}
        panel = {}
        annotate(panel, [source], self.now)
        self.assertFalse(panel["stale"])
        self.assertEqual(panel["age"], 0)
        annotate(panel, [source], self.now + 1801)
        self.assertTrue(panel["stale"])
        source["error"] = "failed"
        annotate(panel, [source], self.now)
        self.assertTrue(panel["stale"])

    def test_rotated_request_lists_and_strict_canonical(self):
        from league_desk.spending import request_interval

        panel = {}
        for version, expected in (("cow_old", False), ("cow_current", True)):
            interval = request_interval(version, "cow_current", 30)
            source = {"name": "requests", "data": {"recent_through": self.now},
                      "fetched_at": self.now, "revisit_seconds": interval}
            annotate(panel, [source], self.now + 13 * 60, cadence=900)
            self.assertEqual(panel["stale"], expected)
            annotate(panel, [source], self.now + 2 * interval + 1)
            self.assertTrue(panel["stale"])
            source["error"] = "failed"
            annotate(panel, [source], self.now + 1)
            self.assertTrue(panel["stale"])

    def test_canonical_request_walk_is_not_starved_by_old_versions(self):
        from league_desk.spending import collect_spending

        rows = [{"id": f"cow_old_{n}", "created_at": self.now - 1000} for n in range(30)]
        rows.append({"id": "cow_demo", "created_at": self.now})
        self.store.success("versions", "all", {"rows": rows}, self.now, cadence=86400)
        self.responses["/v2/experience-requests"] = {"entries": [], "next_cursor": None}
        collect_spending(self.collector, {"coworld_id": "cow_demo", "leagues": []})
        calls = [c for c in self.calls if c[1] == "/v2/experience-requests"]
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][2]["coworld_id"], "cow_demo")
        self.assertEqual(self.store.source("requests", "cow_demo")["next_due"], self.now + 300)
        self.assertEqual(self.store.source("requests", "cow_old_0")["next_due"], self.now + 1800)

    def test_known_finished_game_detail_is_scheduled_daily(self):
        from league_desk.spending import collect_spending

        game = {**episode(raw_game(self.now)), "completed_at": self.now - 1}
        self.store.success("episodes", "round_demo", {"rows": [game]}, self.now)
        with patch("league_desk.spending.details", return_value=game):
            collect_spending(self.collector, {"coworld_id": "cow_demo", "leagues": []})
        self.assertEqual(self.store.source("detail", game["id"])["next_due"], self.now + 86400)
