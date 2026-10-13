from fastapi.testclient import TestClient
from helpers import DeskTest

from league_desk.alerts import alert, model_alerts, prepare_alerts
from league_desk.server import create_app
from league_desk.store import Store


class AlertTests(DeskTest):
    def test_model_fingerprint_changes_only_with_situation(self):
        rows = [{"model": "invented/model", "policy_version_id": "invented-pv-1", "calls": 100,
                 "failed": 20, "failure_day": "2027-01-15"}]
        first = model_alerts(rows, [], "invented-league")[0]
        rows[0]["failed"] = 21
        self.assertEqual(first["fingerprint"], model_alerts(rows, [], "invented-league")[0]["fingerprint"])
        for field, value in (("model", "invented/other"), ("failure_day", "2027-01-16"),
                             ("policy_version_id", "invented-pv-2")):
            changed = [{**rows[0], field: value}]
            new = model_alerts(changed, [], "invented-league")[0]
            active, hidden = prepare_alerts([new], "invented-league", [], [], {first["fingerprint"]})
            self.assertEqual(active, [new])
            self.assertFalse(hidden)
        self.assertNotEqual(first["fingerprint"], model_alerts(rows, [], "other-league")[0]["fingerprint"])
        new = model_alerts(rows + [{**rows[0], "policy_version_id": "invented-pv-2"}], [], "invented-league")[0]
        self.assertNotEqual(first["fingerprint"], new["fingerprint"])
        self.assertIn("2 affected policy versions", new["message"])

    def test_source_and_version_sets_revive_alerts(self):
        messages = ["Multiple versions; mixed-version inputs.", "Some sources failed or are stale."]
        first, _ = prepare_alerts(messages, "invented-league", ["a", "b"], ["costs"], set())
        dismissed = {a["fingerprint"] for a in first}
        active, hidden = prepare_alerts(messages, "invented-league", ["b", "a"], ["costs"], dismissed)
        self.assertFalse(active)
        self.assertEqual(len(hidden), 2)
        active, hidden = prepare_alerts(messages, "invented-league", ["a", "b", "c"], ["costs", "attempts"], dismissed)
        self.assertEqual(len(active), 2)
        self.assertFalse(hidden)

    def test_same_origin_dismiss_undo_and_restart(self):
        fingerprint = alert("Invented alert", "league", "kind", [1])["fingerprint"]
        client = TestClient(create_app(self.store), base_url="http://127.0.0.1:8660")
        path = f"/alerts/{fingerprint}?dismissed=true"
        for headers in ({}, {"origin": "http://evil.invalid"}):
            self.assertEqual(client.post(path, headers=headers).status_code, 403)
        headers = {"origin": "http://127.0.0.1:8660"}
        self.assertEqual(client.post(path, headers=headers).status_code, 200)
        restarted = Store(self.store.directory)
        restarted.initialize()
        self.assertEqual(restarted.dismissals(), {fingerprint})
        self.assertEqual(client.post(f"/alerts/{fingerprint}?dismissed=false", headers=headers).status_code, 200)
        self.assertEqual(restarted.dismissals(), set())
        self.assertEqual(client.post("/alerts/bad?dismissed=true", headers=headers).status_code, 422)
        self.assertEqual(client.get(path).status_code, 405)

    def test_existing_cache_migration_and_hidden_rendering(self):
        self.collector.once()
        with self.store.connection() as db:
            db.execute("DROP TABLE alert_dismissals")
        self.assertFalse(self.store.dismissals())
        self.store.initialize()
        client = TestClient(create_app(self.store), base_url="http://127.0.0.1:8660")
        import re
        page = client.get("/").text
        fingerprints = re.findall(r'data-alert="([a-f0-9]+)"', page)
        self.assertTrue(fingerprints)
        for fingerprint in fingerprints:
            self.store.set_dismissed(fingerprint, True, self.now)
        page = client.get("/").text
        self.assertIn("dismissed · show", page)
        self.assertIn('data-dismiss="false">Undo', page)
