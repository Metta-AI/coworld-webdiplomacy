from html import unescape
from unittest.mock import patch

from fastapi.testclient import TestClient
from helpers import DeskTest

from league_desk.dates import timestamp, when
from league_desk.metrics import desk
from league_desk.panels import SECTIONS
from league_desk.server import create_app
from league_desk.store import Store


class RoutesTests(DeskTest):
    def client(self, store=None):
        return TestClient(create_app(store or self.store), base_url="http://127.0.0.1:8660")

    def test_missing_database_page_requires_no_login_or_files(self):
        empty = Store(self.store.directory / "absent")
        with patch("coworld.api_client.CoworldApiClient.from_login", side_effect=AssertionError("login forbidden")):
            response = self.client(empty).get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("No data collected yet", response.text)
        self.assertFalse(empty.directory.exists())
        for _, panels in SECTIONS:
            for title, _, _, _ in panels:
                self.assertIn(title, unescape(response.text))
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_populated_cache_is_escaped_and_network_free(self):
        self.responses["/v2/leagues"][0]["name"] = "<script>bad()</script>"
        self.collector.once()
        self.calls.clear()
        response = self.client().get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("&lt;script&gt;", response.text)
        self.assertNotIn("<script>", response.text)
        self.assertIn("$4.00 of $40.00", response.text)
        self.assertIn("9.9.1", response.text)
        self.assertEqual(self.calls, [])

    def test_host_rebinding_blocked_even_on_static(self):
        client = self.client()
        for url in ("/", "/static/desk.css"):
            self.assertEqual(client.get(url, headers={"host": "evil.invalid"}).status_code, 400)
        self.assertEqual(client.post("/").status_code, 405)
        self.assertEqual(client.get("/.runtime/desk.sqlite3").status_code, 404)

    def test_league_filter_and_validation(self):
        client = self.client()
        self.assertIn('value="gunboat" selected', client.get("/?league=gunboat").text)
        self.assertEqual(client.get("/?league=elsewhere").status_code, 422)

    def test_stale_retains_numbers_and_displays_failure(self):
        self.collector.once()
        self.store.failure("budgets", "all", "API returned HTTP 503", self.now + 61, 60)
        data = desk(self.store.snapshot(), "press", self.now + 61)
        budget = data["now_rows"][2]
        self.assertTrue(budget["stale"])
        self.assertIn("$4.00", budget["text"])
        self.assertIn("503", budget["error"])

    def test_budget_sentence_precedence_and_zero(self):
        self.collector.once()
        snapshot = self.store.snapshot()
        budget = snapshot[("budgets", "all")]["data"]["leagues"][0]
        budget.update(spent_today_usd=45, projected_today_usd=50)
        data = desk(snapshot, "press", self.now)
        self.assertTrue(any("Budget exceeded" in a for a in data["alerts"]))
        self.assertFalse(any("Projected spend" in a for a in data["alerts"]))
        budget.update(spent_today_usd=0, projected_today_usd=50)
        data = desk(snapshot, "press", self.now)
        self.assertTrue(any("Projected spend" in a for a in data["alerts"]))
        self.assertIn("$0.00", data["now_rows"][2]["text"])
        self.assertTrue(data["meter"]["alert"])
        budget.update(spent_today_usd=40, projected_today_usd=40)
        self.assertFalse(desk(snapshot, "press", self.now)["meter"]["alert"])
        budget.update(spent_today_usd=41, projected_today_usd=None)
        self.assertTrue(desk(snapshot, "press", self.now)["meter"]["alert"])

    def test_timestamps_display_pacific_and_dst(self):
        self.assertIn("PST", when(timestamp("2027-01-15T08:00:00Z")))
        self.assertIn("PDT", when(timestamp("2027-07-15T08:00:00Z")))

    def test_naive_api_timestamp_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "timezone"):
            timestamp("2027-01-15T08:00:00")

    def test_static_css_has_no_remote_assets(self):
        response = self.client().get("/static/desk.css")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("https://", response.text)
