"""Press player: floor-first ordering, the no-endpoint fallback, commits and locking."""

import os
import random
import tempfile
import unittest
from unittest import mock

import _support
from castlereagh import bot, config, golden
from castlereagh.press.player import PressPlayer, horizon
from castlereagh.search import SearchBot

CASE = 9  # a 4-unit autumn 1902 position: quick to search


def make_api(clock, phase_seconds=120):
    data = _support.golden_data()
    case = data["cases"][CASE]
    board = golden._board(data["variant"], case["units"], case["centers"])
    api = _support.FakeApi(case["country"], board, data["variant"], case["turn"], clock)
    api.slots = [{"unitID": s["unitID"]} for s in case["slots"]]
    api.deadline = clock() + phase_seconds
    return api, data, case, board


def gunboat_orders(api, data, case, board, seed):
    rng = random.Random(bot.phase_rng_key(seed, case["country"], case["turn"], "Diplomacy"))
    searcher = SearchBot(data["variant"], board, case["country"], "Diplomacy", case["turn"], rng)
    searcher.memory = {"logodds": {}, "pending": None}
    return searcher.choose(api.slots)


class PressPlayerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.multiple(config, PRESS_STATE_DIR=self.tmp.name, SEARCH_TIME_BUDGET_S=1e9)
        self.patch.start()
        self.events = []
        self.clock = _support.FakeClock()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def log(self, **fields):
        self.events.append(fields)

    def player(self, api, **kwargs):
        return PressPlayer("castlereagh-press", api, 7, self.log, clock=self.clock, sleep=self.clock.sleep, **kwargs)

    def play(self, player, api):
        context = api.context()
        player.play(context, bot.play_phase)

    def test_floor_is_saved_before_the_first_wake_and_equals_gunboat_play(self):
        api, data, case, board = make_api(self.clock)
        seen_at_wake = []

        def run_wake(agent, prompt, seconds, limit):
            seen_at_wake.append(list(api.calls))
            return "done", "ok"

        player = self.player(api, agent=object(), run_wake=run_wake)
        self.play(player, api)
        first_saves = seen_at_wake[0]
        self.assertEqual(first_saves[0][:2], ("orders", "No"))
        self.assertEqual(first_saves[0][2], gunboat_orders(api, data, case, board, 7))
        last = api.calls[-1]
        self.assertEqual(last[:3], ("orders", "Yes", first_saves[0][2]))
        self.assertLessEqual(last[3], api.deadline - config.PRESS_FINAL_MARGIN_S + config.PRESS_POLL_S)
        decision = next(e for e in self.events if e["event"] == "decision")
        self.assertEqual(decision["rejected"], 0)
        self.assertTrue(any(e["event"] == "workspace" for e in self.events))

    def test_commit_replaces_the_floor_and_is_refused_after_the_lock(self):
        api, *_ = make_api(self.clock)

        def run_wake(agent, prompt, seconds, limit):
            player.commit({"risk": 1.0, "stances": {"FRANCE": "ally"}})
            return "committed", "ok"

        player = self.player(api, agent=object(), run_wake=run_wake)
        self.play(player, api)
        committed = player.orders
        self.assertEqual(api.calls[-1][:3], ("orders", "Yes", committed))
        self.assertTrue(any(e["event"] == "press_commit" for e in self.events))
        with self.assertRaises(ValueError):
            player.commit({"risk": 0.0})

    def test_a_failing_wake_keeps_the_floor(self):
        api, *_ = make_api(self.clock)

        def run_wake(agent, prompt, seconds, limit):
            raise RuntimeError("sidecar down")

        player = self.player(api, agent=object(), run_wake=run_wake)
        self.play(player, api)
        floor = api.calls[0][2]
        self.assertEqual(api.calls[-1][:3], ("orders", "Yes", floor))
        self.assertTrue(any(e["event"] == "wake_error" for e in self.events))
        self.assertEqual(next(e for e in self.events if e["event"] == "wake")["status"], "error")

    def test_new_press_wakes_the_agent_and_is_marked_new(self):
        api, *_ = make_api(self.clock)
        prompts = []

        def run_wake(agent, prompt, seconds, limit):
            prompts.append(prompt)
            if len(prompts) == 1:
                api.inbox.append({"id": 1, "turn": api.turn, "fromCountryID": 2, "toCountryID": api.country_id,
                                  "message": "DMZ Burgundy?"})
            return "ok", "ok"

        player = self.player(api, agent=object(), run_wake=run_wake)
        self.play(player, api)
        self.assertEqual(len(prompts), 2)
        self.assertIn('NEW <press phase="F1902" from="FRANCE" to="you">DMZ Burgundy?</press>', prompts[1])
        self.assertTrue(any(e["event"] == "press_in" for e in self.events))

    def test_without_endpoint_plays_the_floor_with_ready_at_once(self):
        api, data, case, board = make_api(self.clock)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("COWORLD_LLM_ENDPOINT", None)
            player = self.player(api)
        self.assertIsNone(player.agent)
        disabled = [e for e in self.events if e["event"] == "press_disabled"]
        self.assertEqual(len(disabled), 1)
        self.play(player, api)
        self.play(player, api)  # a second phase must not log it again
        self.assertEqual(len([e for e in self.events if e["event"] == "press_disabled"]), 1)
        self.assertEqual(api.calls[0][:2], ("orders", "Yes"))
        self.assertEqual(api.calls[0][2], gunboat_orders(api, data, case, board, 7))
        self.assertFalse(any(e["event"] == "wake_start" for e in self.events))

    def test_horizon_reads_only_the_environment(self):
        with mock.patch.dict(os.environ, {"WEBDIP_END_YEAR": "1904", "WEBDIP_SCORING": "sum_of_squares"}):
            text = horizon(4)  # spring 1903
        self.assertIn("4 movement phase(s) remain", text)
        self.assertIn("sum_of_squares", text)
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIn("not given", horizon(4))


if __name__ == "__main__":
    unittest.main()
