"""press_behaviour: the countable shape of a committed policy, phase rows from a seat log, the summary."""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401  (puts the tools folder on sys.path)
import press_behaviour as pb
from helpers import write_episode


def seat_log():
    """Two movement phases: one with every unit fixed (one as a hold), one played on the floor."""
    return [
        {"event": "press_out", "turn": 0, "to": "RUSSIA", "text": "a"},
        {"event": "press_out", "turn": 0, "to": "RUSSIA", "text": "b"},
        {"event": "press_out", "turn": 0, "to": "RUSSIA", "text": "c"},
        {"event": "press_commit", "turn": 0, "press_policy": {"require_orders": ["A CON - BUL"]},
         "orders": ["A CON - BUL", "F ANK - BLA"]},
        {"event": "press_commit", "turn": 0,
         "press_policy": {"require_orders": ["A CON - BUL", "F ANK H"], "stances": {"RUSSIA": "Hostile"},
                          "forbid_moves_into": ["BLA"]},
         "orders": ["A CON - BUL", "F ANK H"]},
        {"event": "wake", "turn": 0, "status": "ok"},
        {"event": "wake", "turn": 0, "status": "ok"},
        {"event": "decision", "turn": 0, "phase": "Diplomacy", "llm_cost_usd": 0.01,
         "trace": {"press_freed_holds": 2}},
        {"event": "decision", "turn": 1, "phase": "Builds"},
        {"event": "wake", "turn": 2, "status": "time_limit"},
        {"event": "decision", "turn": 2, "phase": "Diplomacy", "llm_cost_usd": 0.03, "trace": {}},
    ]


class CommitShape(unittest.TestCase):
    def test_counts_fixed_orders_holds_and_stances(self):
        shape = pb.commit_shape({"require_orders": ["A BUL H", "F CON - AEG"], "stances": {"ITALY": "hostile"},
                                 "center_values": {"ITALY": 0.5}}, ["A BUL H", "F CON - AEG", "A ARM H"])
        self.assertEqual((shape["units"], shape["fixed"], shape["fixed_holds"], shape["holds"]), (3, 2, 1, 2))
        self.assertFalse(shape["all_fixed"])
        self.assertTrue(shape["hostile"] and shape["center_values"])
        self.assertFalse(shape["ally"] or shape["forbid"] or shape["expected"])

    def test_an_empty_policy_fixes_nothing_and_a_support_hold_is_not_a_hold(self):
        shape = pb.commit_shape(None, ["A PAR S F BRE", "F BRE H"])
        self.assertEqual((shape["fixed"], shape["holds"], shape["all_fixed"]), (0, 1, False))


class PhaseRows(unittest.TestCase):
    def test_the_last_commit_of_a_phase_counts_and_a_floor_phase_has_no_order_counts(self):
        first, second = pb.phase_rows(seat_log())
        self.assertEqual((first["turn"], first["committed"], first["fixed"], first["fixed_holds"]), (0, True, 2, 1))
        self.assertTrue(first["all_fixed"] and first["hostile"] and first["forbid"])
        self.assertEqual((first["messages"], first["repeat_to_one"], first["wakes"], first["freed_holds"]),
                         (3, True, 2, 2))
        self.assertEqual((second["turn"], second["committed"], second["wakes"]), (2, False, 1))
        self.assertNotIn("units", second)

    def test_summary_shares(self):
        summary = pb.summarize(pb.phase_rows(seat_log()))
        self.assertEqual(summary["phases"], 2)
        self.assertEqual(summary["committed"], 0.5)
        self.assertEqual((summary["fixed_share"], summary["fixed_hold_share"], summary["hold_share"]), (1.0, 0.5, 0.5))
        self.assertEqual((summary["all_fixed"], summary["hostile"], summary["ally"]), (1.0, 1.0, 0.0))
        self.assertEqual((summary["messages"], summary["repeat_to_one"], summary["wakes"]), (1.5, 0.5, 1.5))
        self.assertAlmostEqual(summary["cost"], 0.02)
        self.assertEqual(pb.summarize([])["committed"], None)  # nothing to divide by: no share, no crash


class CommandLine(unittest.TestCase):
    def test_table_by_version_reads_our_press_seats_and_skips_a_seat_whose_agent_never_ran(self):
        with tempfile.TemporaryDirectory() as tmp:
            floor_only = [{"event": "decision", "turn": 0, "phase": "Diplomacy", "trace": {}}]
            write_episode(Path(tmp) / "ep1", [0.5, 0.5], [6, 7], [4, 4], seating=["ours:v2", "search:v1"],
                          logs={0: seat_log(), 1: floor_only})
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                pb.main([tmp])
        text = out.getvalue()
        self.assertIn("seats read: ours:v2 1", text)
        self.assertNotIn("search:v1", text)
        self.assertIn("| every unit fixed | 100% |", text)
        self.assertIn("| LLM cost per phase | $0.0200 |", text)


if __name__ == "__main__":
    unittest.main()
