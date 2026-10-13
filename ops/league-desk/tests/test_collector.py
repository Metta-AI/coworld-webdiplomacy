from unittest.mock import patch

import httpx
from helpers import DeskTest

from league_desk.api import Api, ApiError, logged_in_api
from league_desk.collector import collector_lock


class ApiTests(DeskTest):
    def test_only_allowlisted_gets(self):
        for path in ("/sql/query", "/v2/leagues/league_demo/locks", "https://evil.invalid/v2/games",
                     "/v2/coworlds/cow_demo/../secrets", "/v2/games?token=bad"):
            with self.assertRaises(ApiError):
                self.api.get(path)
        self.assertEqual(self.calls, [])
        self.api.get("/v2/games")
        self.assertEqual(self.calls[0][0], "GET")

    def test_object_pagination_and_exact_full_final_page(self):
        responses = iter([
            httpx.Response(200, json={"entries": [{"id": "a"}], "next_cursor": "next"}),
            httpx.Response(200, json={"entries": [{"id": "b"}], "next_cursor": None}),
        ])
        calls = []

        def request(method, path, params):
            calls.append(dict(params))
            return next(responses)

        self.assertEqual(Api(request).pages("/v2/rounds", {"limit": 1}), [{"id": "a"}, {"id": "b"}])
        self.assertEqual(calls[1]["cursor"], "next")

    def test_list_header_cursor(self):
        self.responses["/v2/rounds"] = httpx.Response(200, json=[{"id": "a"}], headers={"X-Next-Cursor": "b"})
        page = self.api.page("/v2/rounds", {"limit": 1})
        self.assertEqual(page.next_cursor, "b")
        self.assertFalse(page.complete)

    def test_full_bare_page_is_incomplete(self):
        self.responses["/v2/rounds"] = [{"id": "a"}]
        with self.assertRaisesRegex(ApiError, "Incomplete"):
            self.api.pages("/v2/rounds", {"limit": 1})

    def test_repeated_rows_do_not_loop(self):
        self.responses["/v2/rounds"]["next_cursor"] = "more"
        with self.assertRaisesRegex(ApiError, "repeated"):
            self.api.pages("/v2/rounds")
        self.assertEqual(len(self.calls), 2)

    def test_errors_do_not_expose_bodies_or_urls(self):
        for status in (301, 401, 403, 500):
            self.responses["/v2/games"] = httpx.Response(status, text="private-token-and-email")
            with self.assertRaises(ApiError) as caught:
                self.api.json("/v2/games")
            self.assertNotIn("private", str(caught.exception))
        self.responses["/v2/games"] = httpx.ConnectError("secret URL")
        with self.assertRaisesRegex(ApiError, "Network request failed"):
            self.api.json("/v2/games")

    def test_bad_json(self):
        self.responses["/v2/games"] = httpx.Response(200, content=b"private invalid json")
        with self.assertRaisesRegex(ApiError, "invalid JSON"):
            self.api.json("/v2/games")

    def test_login_failure_is_safe(self):
        with patch("coworld.api_client.CoworldApiClient.from_login", side_effect=RuntimeError("secret")):
            with self.assertRaisesRegex(ApiError, "Login unavailable"):
                with logged_in_api():
                    self.fail("unreachable")


class CollectorTests(DeskTest):
    def test_selected_fields_only_and_no_remote_writes(self):
        self.collector.once()
        rows = self.store.snapshot()
        self.assertEqual(len(rows), 16)
        self.assertTrue(all(r["error"] is None for r in rows.values()))
        self.assertNotIn("must-not-store", str(rows))
        self.assertNotIn("not-for-cache", str(rows))
        self.assertTrue(all(method == "GET" for method, _, _ in self.calls))
        self.assertEqual(rows[("canonical", "all")]["data"]["version"], "9.9.1")

    def test_repeat_before_due_is_noop(self):
        self.collector.once()
        self.calls.clear()
        self.collector.once()
        self.assertEqual(self.calls, [])

    def test_failed_source_preserves_good_data_and_other_sources_advance(self):
        self.collector.once()
        old = self.store.source("budgets", "all")
        self.now += 61
        self.responses["/v2/budgets"] = httpx.Response(503, text="private error")
        self.collector.once()
        new = self.store.source("budgets", "all")
        self.assertEqual(new["data"], old["data"])
        self.assertEqual(new["fetched_at"], old["fetched_at"])
        self.assertEqual(new["error"], "API returned HTTP 503")
        self.assertEqual(self.store.source("round", "league_demo")["fetched_at"], self.now)

    def test_rate_limit_persists_and_stops_remaining_sources(self):
        self.responses["/v2/games"] = httpx.Response(
            429, headers={"x-ratelimit-retry-after": "300", "retry-after": "1"})
        self.collector.once()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.store.retry_not_before(), self.now + 300)
        self.now += 299
        self.collector.once()
        self.assertEqual(len(self.calls), 1)
        self.store.initialize()
        self.assertGreater(self.store.retry_not_before(), self.now)

    def test_malformed_budget_cannot_replace_snapshot(self):
        self.collector.once()
        old = self.store.source("budgets", "all")
        self.now += 61
        self.responses["/v2/budgets"]["leagues"][0]["spent_today_usd"] = "secret malformed number"
        self.collector.once()
        new = self.store.source("budgets", "all")
        self.assertEqual(new["data"], old["data"])
        self.assertNotIn("secret", new["error"])

    def test_observations_only_on_change_and_recovery_clears_failure(self):
        self.collector.once()
        self.now += 61
        self.collector.once()
        with self.store.connection(True) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM observations").fetchone()[0], 3)
        self.responses["/v2/coworlds/cow_demo"]["version"] = "9.9.2"
        self.now += 61
        self.collector.once()
        with self.store.connection(True) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM observations").fetchone()[0], 4)
        self.store.failure("canonical", "all", "error", self.now, 1)
        self.now += 61
        self.collector.once()
        self.assertIsNone(self.store.source("canonical", "all")["error"])

    def test_duplicate_active_variant_fails_discovery(self):
        self.responses["/v2/leagues"].append({"id": "league_other", "name": "Other",
                                             "commissioner_config": {"default_variant_id": "classic-press"}})
        self.collector.once()
        self.assertIsNone(self.store.source("discovery", "all")["data"])
        self.assertEqual(len(self.calls), 2)

    def test_lock_excludes_second_collector_and_releases(self):
        with collector_lock(self.store.directory):
            with self.assertRaisesRegex(ApiError, "already owns"):
                with collector_lock(self.store.directory):
                    self.fail("second lock acquired")
        with collector_lock(self.store.directory):
            pass
