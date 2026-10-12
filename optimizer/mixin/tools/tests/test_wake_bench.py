"""wake_bench: sampling cases, rebuilding a position from a replay and a seat log, and playing a
case through the reference policy with a scripted wake (no model, no network)."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401  (puts the tools folder on sys.path)
import wake_bench
from helpers import write_episode

GOLDEN = wake_bench.POLICY_SOURCE / "tests" / "golden.json"
CASE = 9  # a 4-unit autumn 1902 position (turn 3): quick to search


def write_game(root: Path) -> tuple[Path, dict]:
    """One synthetic episode: the golden position as the replay's turn-3 phase, and a seat log around it."""
    data = json.loads(GOLDEN.read_text())
    case = data["cases"][CASE]
    country, turn = int(case["country"]), int(case["turn"])
    units = [{"countryID": u["countryID"], "type": u["type"], "terrID": u["terrID"], "retreating": False}
             for u in case["units"]]
    phases = [{"turn": turn - 1, "phase": "Diplomacy", "units": units, "centers": case["centers"], "orders": []},
              {"turn": turn, "phase": "Diplomacy", "units": units, "centers": case["centers"], "orders": []},
              {"turn": turn + 1, "phase": "Diplomacy", "units": units, "centers": case["centers"], "orders": []}]
    other = next(c for c in range(1, 8) if c != country)
    log = [
        {"event": "press_in", "t": 10.0, "id": 77, "turn": turn - 1, "frm": wake_bench.we.POWERS[other].upper(),
         "to": "us", "text": "old offer"},
        {"event": "press_out", "t": 11.0, "turn": turn - 1, "to": wake_bench.we.POWERS[other].upper(),
         "text": "old reply"},
        {"event": "workspace", "t": 20.0, "turn": turn - 1, "notes": {"plan": "hold the line"}, "beliefs": {"3": 1.5}},
        {"event": "wake_start", "t": 30.0, "wake": f"{turn}-5-phase_start", "turn": turn, "kind": "phase_start"},
        {"event": "llm_request", "t": 30.1, "wake": f"{turn}-5-phase_start",
         "messages": [{"role": "system", "content": "(system prompt: see press_start)"},
                      {"role": "user",
                       "content": "# You play X.\n\n## Board\n\nrecorded board\n## Map connectivity\nx"}]},
        {"event": "press_in", "t": 40.0, "id": 78, "turn": turn, "frm": wake_bench.we.POWERS[other].upper(),
         "to": "ALL", "text": "arrived after the wake began"},
        {"event": "wake_start", "t": 50.0, "wake": f"{turn}-6-press", "turn": turn, "kind": "press"},
    ]
    ep = root / "ep1"
    countries = [country] + [c for c in range(1, 8) if c != country]
    write_episode(ep, [1 / 7] * 7, countries, [3] * 7, seating=["ours:v1"] + ["field:v1"] * 6, logs={0: log})
    (ep / "replay.json").write_text(json.dumps([{"variant": data["variant"], "history": {"phases": phases}}]))
    return ep, case


class Sampling(unittest.TestCase):
    def test_turn_of(self):
        turns = (wake_bench.turn_of("S1901"), wake_bench.turn_of("A1902"), wake_bench.turn_of("f1902"))
        self.assertEqual(turns, (0, 3, 3))
        with self.assertRaises(ValueError):
            wake_bench.turn_of("W1901")

    def test_only_phase_start_wakes_of_the_named_policy_become_cases_and_a_named_case_comes_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            ep, case = write_game(Path(tmp))
            power = wake_bench.we.POWERS[int(case["country"])]
            cases = wake_bench.sample_cases([Path(tmp)], ["ours"], 5, 0, [f"ep1:{power}:A1902"])
            self.assertEqual([c["id"] for c in cases], [f"ep1:{power}:3"])  # the press wake is not a case
            self.assertEqual((cases[0]["slot"], cases[0]["policy"]), (0, "ours:v1"))
            self.assertEqual(wake_bench.sample_cases([Path(tmp)], ["field"], 5, 0, []), [])
            with self.assertRaises(ValueError):
                wake_bench.sample_cases([Path(tmp)], None, 5, 0, [f"ep1:{power}:S1905"])


class Rebuild(unittest.TestCase):
    def test_the_position_is_what_the_wake_could_see(self):
        with tempfile.TemporaryDirectory() as tmp:
            ep, case = write_game(Path(tmp))
            position = wake_bench.rebuild(wake_bench.seat_cases(ep, None)[0])
        me, turn = int(case["country"]), int(case["turn"])
        self.assertEqual((position["country"], position["turn"]), (me, turn))
        self.assertEqual([u["id"] for u in position["units"]], list(range(1, len(case["units"]) + 1)))
        self.assertEqual([p["turn"] for p in position["history"]["phases"]], [turn - 1])  # nothing from the future
        self.assertEqual([m["message"] for m in position["messages"]], ["old offer", "old reply"])
        self.assertEqual([(m["fromCountryID"] == me, m["toCountryID"] == me) for m in position["messages"]],
                         [(False, True), (True, False)])
        self.assertEqual((position["notes"], position["beliefs"]), ({"plan": "hold the line"}, {"3": 1.5}))
        self.assertEqual(position["recorded_board"], "## Board\n\nrecorded board")

    def test_board_section_stops_at_the_next_heading(self):
        self.assertEqual(wake_bench.board_section("x\n## Board\n\nA\nB\n## Map connectivity\nC"), "## Board\n\nA\nB")
        self.assertEqual(wake_bench.board_section("no board here"), "")


class RunCase(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(wake_bench.POLICY_SOURCE))
        from castlereagh import config
        self.config, self.saved = config, config.SEARCH_TIME_BUDGET_S
        config.SEARCH_TIME_BUDGET_S = 1e9  # determinism: never stop the search on wall clock

    def tearDown(self):
        self.config.SEARCH_TIME_BUDGET_S = self.saved

    def test_a_scripted_wake_plays_the_phase_and_its_commit_is_read_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            ep, case = write_game(Path(tmp))
            bench_case = wake_bench.seat_cases(ep, None)[0]

            def fixes_every_unit_as_a_hold(player):
                def run_wake(agent, prompt, seconds, limit):
                    self.assertIn("hold the line", prompt)  # the recorded notes reach the briefing
                    self.assertIn("old offer", player.toolbox_conversation())
                    mine = [u for u in player.service.b.units if int(u["countryID"]) == player.country]
                    player.commit({"require_orders": [player.service.notation.unit_label(u) + " H" for u in mine]})
                    player.send("ALL", "hello")
                    return "done", "ok"
                player.toolbox_conversation = lambda: "\n".join(m["text"] for m in player.press_log.messages)
                return run_wake

            result = wake_bench.run_case(bench_case, 0, fixes_every_unit_as_a_hold)
        row = result["row"]
        units = len([u for u in case["units"] if int(u["countryID"]) == int(case["country"])])
        self.assertEqual((row["committed"], row["units"], row["fixed"], row["fixed_holds"], row["holds"]),
                         (True, units, units, units, units))
        self.assertTrue(row["all_fixed"] and row["wake_ok"])
        self.assertEqual((row["messages"], row["sent"], row["wakes"]), (1, ["hello"], 1))
        self.assertFalse(row["board_matches"])  # the fixture's recorded board is a placeholder
        self.assertEqual(len(row["final_orders"]), units)
        self.assertIsNotNone(row["centres_delta"])
        # The zero lines: the plain search run once more, beside the floor.
        self.assertIn(row["research_changed"], (True, False))
        self.assertIsNotNone(row["research_delta"])
        self.assertFalse(row["wake_limit"])
        self.assertTrue(any(e["event"] == "decision" for e in result["events"]))

        summary = wake_bench.summarize([row, {"case": "broken", "error": "boom"}])
        self.assertEqual((summary["cases"], summary["errors"], summary["phases"]), (2, 1, 1))
        self.assertEqual((summary["all_fixed"], summary["wake_ok"], summary["board_matches"]), (1.0, 1.0, 0.0))
        self.assertEqual((row["wake_status"], row["llm_failed"]), ("ok", 0))
        self.assertIn("1 of 2 cases could not be played", wake_bench.validity(summary, [row]))


class Validity(unittest.TestCase):
    def test_a_run_whose_model_failed_is_flagged_with_the_first_error_and_a_clean_run_is_not(self):
        played = {"case": "a", "committed": False, "messages": 0, "repeat_to_one": False, "wakes": 1, "cost": 0.0,
                  "freed_holds": 0, "board_matches": True, "changed": False, "centres_delta": 0.0}
        dead = [{**played, "wake_ok": False, "llm_failed": 1, "llm_error": "HTTP 403: Key limit exceeded"}] * 3
        problem = wake_bench.validity(wake_bench.summarize(dead), dead)
        self.assertIn("only 0% of wakes ended ok", problem)
        self.assertIn("Key limit exceeded", problem)
        fine = [{**played, "wake_ok": True, "llm_failed": 0}] * 3
        self.assertIsNone(wake_bench.validity(wake_bench.summarize(fine), fine))

    def test_wakes_cut_off_at_a_limit_are_noted_and_not_read_as_failures(self):
        played = {"case": "a", "committed": False, "messages": 0, "repeat_to_one": False, "wakes": 1, "cost": 0.0,
                  "freed_holds": 0, "board_matches": True, "changed": False, "centres_delta": 0.0, "llm_failed": 0}
        ok = {**played, "wake_ok": True, "wake_limit": False}
        cut = {**played, "wake_ok": False, "wake_limit": True}
        rows = [ok] * 7 + [cut] * 3   # 70% ok, 30% cut off at a limit, none failed
        summary = wake_bench.summarize(rows)
        self.assertEqual((summary["wake_ok"], summary["wake_limit"]), (0.7, 0.3))
        self.assertIsNone(wake_bench.validity(summary, rows))
        self.assertIn("30% of wakes ran to their time or request limit", wake_bench.limit_note("slow", summary))
        self.assertIsNone(wake_bench.limit_note("quick", wake_bench.summarize([ok] * 19 + [cut])))
        failed = {**played, "wake_ok": False, "wake_limit": False}
        rows = [ok] * 7 + [cut] + [failed] * 2   # 20% failed: not readable
        self.assertIn("only 80% of wakes ended ok or at a limit", wake_bench.validity(wake_bench.summarize(rows), rows))
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "rows.json").write_text(json.dumps({"label": "slow", "rows": [ok] * 7 + [cut] * 3}))
            _, text = wake_bench.report([Path(tmp)])
        self.assertTrue(text.startswith("Note on `slow`: 30% of wakes"))
        self.assertIn("| a re-search alone differs |", text)

    def test_the_report_puts_the_warning_above_the_table(self):
        played = {"case": "a", "committed": False, "messages": 0, "repeat_to_one": False, "wakes": 1, "cost": 0.0,
                  "freed_holds": 0, "board_matches": True, "changed": False, "centres_delta": 0.0, "wake_ok": False}
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "rows.json").write_text(json.dumps({"label": "dead", "rows": [played]}))
            summaries, text = wake_bench.report([Path(tmp)])
        self.assertTrue(text.startswith("**DO NOT READ the `dead` column"))
        self.assertTrue(summaries["dead"]["not_valid"])


if __name__ == "__main__":
    unittest.main()
