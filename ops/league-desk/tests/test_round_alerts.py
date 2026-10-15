from helpers import DeskTest

from league_desk.metrics import desk


def messages(data):
    return [a["message"] if isinstance(a, dict) else a for a in data["alerts"]]


class CreditAndRoundAlertTests(DeskTest):
    def test_credit_pool_tile_caches_selected_fields_only(self):
        self.collector.once()
        cached = self.store.source("credits", "league_demo")["data"]
        self.assertEqual(set(cached), {"pool_credits", "granted_today_credits", "play_charged_today_credits",
                                       "paid_today_credits"})
        row = next(r for r in desk(self.store.snapshot(), "press", self.now)["now_rows"] if r["title"] == "Credit pool")
        self.assertEqual(row["text"], "250 credits ($25.00)")
        self.assertIn("+400 credits granted, −150 credits play, −0 credits rewards", row["note"])
        self.assertFalse(any("Credit pool" in m for m in messages(desk(self.store.snapshot(), "press", self.now))))

    def test_empty_pool_alerts(self):
        self.responses["/v2/leagues/league_demo/owner-status"]["credits"]["pool_credits"] = -12.5
        self.collector.once()
        self.assertTrue(any(m.startswith("Credit pool is empty: -12 credits")
                            for m in messages(desk(self.store.snapshot(), "press", self.now))))

    def test_refused_budget_check_alerts_with_the_platform_reason(self):
        self.responses["/v2/leagues/health"][0]["budgets"] = [
            {"checked_at": "2027-01-15T07:00:00Z", "refusal_cause": None},
            {"checked_at": "2027-01-15T07:59:00Z", "refusal_cause": "league_pool"}]
        self.collector.once()
        found = [m for m in messages(desk(self.store.snapshot(), "press", self.now)) if "blocked" in m]
        self.assertEqual(len(found), 1)
        self.assertIn("the league credit pool is too low", found[0])

    def test_stall_alert_after_two_hours_without_a_new_round(self):
        self.collector.once()
        snapshot = self.store.snapshot()
        self.assertFalse(any("No new round" in m for m in messages(desk(snapshot, "press", self.now + 7200))))
        late = desk(snapshot, "press", self.now + 7260)
        stall = [a for a in late["alerts"] if isinstance(a, dict) and "No new round" in a["message"]]
        self.assertEqual(len(stall), 1)
        self.assertIn("No new round for 2 h 1 min: round 3 (running)", stall[0]["message"])
        # The identity is the stalled round, so a dismissal survives the growing duration.
        later = desk(snapshot, "press", self.now + 9000)
        self.assertIn(stall[0]["fingerprint"], [a["fingerprint"] for a in later["alerts"] if isinstance(a, dict)])

    def test_stall_threshold_is_two_intervals_for_slow_leagues(self):
        self.responses["/v2/leagues/league_demo/settings"]["settings"]["round_interval_minutes"] = 1440
        self.collector.once()
        snapshot = self.store.snapshot()
        self.assertFalse(any("No new round" in m for m in messages(desk(snapshot, "press", self.now + 86400))))
        self.assertTrue(any("No new round" in m for m in messages(desk(snapshot, "press", self.now + 2 * 86400 + 60))))
