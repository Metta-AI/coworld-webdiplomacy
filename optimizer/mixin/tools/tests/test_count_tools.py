"""holds.py, board_counts.py, seat_rows.py and seat_log.py on small synthetic games.

The games are the three-seat ones of test_opponent_profile (Germany, Russia, France in slots 0, 1, 2):
with `EAST`, Germany moves A BER - PRU and F KIE - DEN and holds Munich in Spring 1901, takes Warsaw
and Denmark in Autumn 1901, and everyone holds through 1902."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401  (puts the tools folder on sys.path)
import board_counts
import holds
import seat_log
import seat_rows
from opponent_profile import load_games
from test_opponent_profile import BLITZ, EAST, history, write_game

SEATS = ["rival:v2", "ours:v1", "filler:v1"]


def run(tool, argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = tool.main(argv)
    return code, out.getvalue()


def write_log(ep: Path, slot: int, rows) -> None:
    (ep / "policy-logs").mkdir(exist_ok=True)
    text = rows if isinstance(rows, str) else "".join(json.dumps(r) + "\n" for r in rows)
    (ep / "policy-logs" / f"pv.{slot}.log").write_text(text)


class Holds(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.ep = write_game(self.root, "ereq_a", history(EAST), SEATS, [0.6, 0.1, 0.3], [5, 1, 1])

    def measure(self, policy, **kwargs):
        games, _ = load_games([self.root])
        return holds.measure(games, policy, **kwargs)

    def test_hold_share_beside_the_field_and_by_year(self):
        result = self.measure("rival", stopped_phases=2)
        germany = next(r for r in result["by_power"] if r["who"] == "rival:v2")
        # Germany: 1 hold of 3 in each 1901 phase, then 4 of 4 in both 1902 phases.
        self.assertEqual((germany["orders"], germany["holds"], germany["all_hold_phases"]), (14, 10, 2))
        field = next(r for r in result["overall"] if r["who"] == "field")
        self.assertEqual((field["seats"], field["orders"], field["holds"]), (2, 10, 8))
        by_year = {(r["who"], r["year"]): r["hold_share"] for r in result["by_year"]}
        self.assertAlmostEqual(by_year[("policy", 1901)], 2 / 6, places=3)
        self.assertEqual(by_year[("policy", 1902)], 1.0)

    def test_a_seat_that_only_holds_at_the_end_is_listed_with_when_it_began(self):
        stopped = self.measure("rival", stopped_phases=2)["stopped_seats"]
        self.assertEqual([(s["power"], s["began"], s["phases"], s["log"]) for s in stopped],
                         [("Germany", "Spring 1902", 2, "no log on disk")])
        self.assertEqual(self.measure("rival")["stopped_seats"], [])  # the default asks for four phases

    def test_holds_are_split_by_what_the_press_layer_committed(self):
        write_log(self.ep, 1, [
            {"event": "decision", "turn": 0, "phase": "Diplomacy", "trace": {"press_commits": 2},
             "press_policy": {"require_orders": ["A WAR H", "A MOS H"]}},
            {"event": "decision", "turn": 1, "phase": "Diplomacy", "press_policy": None},
            {"event": "decision", "turn": 2, "phase": "Diplomacy", "trace": {"press_rule_refused": 3},
             "press_policy": {"forbid_moves_into": ["WAR"]}},
        ])
        press = self.measure("ours")["press_policy"]["ours:v1"]
        self.assertEqual((press["orders"], press["holds"], press["holds_required"]), (6, 6, 2))
        self.assertEqual(press["guards"], {"press_commits": 2, "press_rule_refused": 3})
        groups = {g["group"]: g["phases"] for g in press["by_constraint"]}
        self.assertEqual(groups, {"pins half or more, forbids nothing": 1,
                                  "no policy committed (the search floor played)": 1,
                                  "pins under half, forbids a province": 1,
                                  "no decision line for the phase": 1})
        self.assertEqual([g["group"] for g in press["last_phase"]], ["no decision line for the phase"])

    def test_a_dead_pod_is_left_out_and_counted(self):
        write_log(self.ep, 1, "No logs collected for pod job-1-game-player-1 container player: the pod was deleted.\n")
        result = self.measure("rival")
        self.assertEqual(result["pod_deleted_seats"], {"field": 1})
        self.assertEqual(next(r for r in result["overall"] if r["who"] == "field")["seats"], 1)

    def test_alone_leaves_out_games_with_two_seats_of_the_policy(self):
        write_game(self.root, "ereq_twin", history(EAST), ["rival:v2", "rival:v3", "filler:v1"], [0.6, 0.1, 0.3],
                   [5, 1, 1])
        self.assertEqual((self.measure("rival")["games"], self.measure("rival", alone=True)["games"]), (2, 1))

    def test_alone_also_leaves_out_games_with_another_policy_named_as_ours(self):
        self.assertEqual(self.measure("ours", alone=True)["games"], 1)
        named = self.measure("ours", alone=True, also_ours=("filler",))
        self.assertEqual((named["games"], named["also_ours"]), (0, ["filler"]))
        self.assertEqual(self.measure("ours", also_ours=("filler",))["games"], 1)  # only --alone uses it
        code, text = run(holds, [str(self.root), "--policy", "rival", "--alone", "--ours", "nobody"])
        self.assertIn("1 games with one seat of the policy or nobody", text)

    def test_cli_prints_the_tables_and_exits_2_for_an_unknown_policy(self):
        code, text = run(holds, [str(self.root), "--policy", "rival", "--stopped-phases", "2"])
        self.assertEqual(code, 0)
        self.assertIn("| Germany | rival:v2 | 1 | 14 | 10 | 71% | 2 of 4 | 1 of 1 |", text)
        self.assertEqual(run(holds, [str(self.root), "--policy", "nobody"])[0], 2)


class BoardCounts(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        write_game(self.root, "ereq_a", history(EAST), SEATS, [0.6, 0.1, 0.3], [5, 1, 1])
        write_game(self.root, "ereq_b", history(BLITZ, attack_russia=False), SEATS, [0.2, 0.5, 0.3], [4, 2, 1])
        # The field's Germany: another policy at the same power.
        write_game(self.root, "ereq_c", history(EAST), ["filler:v1", "rival:v2", "ours:v1"], [0.3, 0.4, 0.3],
                   [5, 1, 1])
        self.games, _ = load_games([self.root])

    def test_when_reads_phases_ranges_and_years(self):
        self.assertEqual(board_counts.parse_when("S1901"), (0, 0))
        self.assertEqual(board_counts.parse_when("a1902"), (3, 3))
        self.assertEqual(board_counts.parse_when("S1901-A1902"), (0, 3))
        self.assertEqual(board_counts.parse_when("1902"), (2, 3))
        self.assertEqual(board_counts.parse_when("1901-1903"), (0, 5))
        self.assertIsNone(board_counts.parse_when(None))
        with self.assertRaises(ValueError):
            board_counts.parse_when("spring 1901")

    def test_an_order_is_counted_for_the_policy_and_for_the_field(self):
        result = board_counts.count(self.games, "rival", "Germany", ["A BER - PRU", "* - DEN"], [], [], (0, 0))
        ours, field = result["policy_counts"], result["field_counts"]
        self.assertEqual((ours["seats"], field["seats"]), (2, 1))
        self.assertEqual(ours["orders"]["A BER - PRU"]["given_once"], 1)  # EAST only; BLITZ moves A BER - KIE
        self.assertEqual(ours["orders"]["* - DEN"]["given_once"], 2)  # the wildcard: any move into Denmark
        self.assertEqual(field["orders"]["A BER - PRU"]["given_once"], 1)

    def test_every_phase_and_success_are_counted_apart(self):
        result = board_counts.count(self.games, "rival", "Germany", ["A MUN H"], [], [], (0, 3))
        counts = result["policy_counts"]["orders"]["A MUN H"]
        # Both games hold Munich in some phase, neither in all four (EAST supports from it in Autumn 1901,
        # BLITZ moves it in Spring 1901), and a hold is never counted as an order that succeeded.
        self.assertEqual((counts["given_once"], counts["given_every_phase"], counts["succeeded_once"]), (2, 0, 0))
        moved = board_counts.count(self.games, "rival", "Germany", ["F KIE - DEN"], [], [], (0, 0))
        self.assertEqual(moved["policy_counts"]["orders"]["F KIE - DEN"]["succeeded_once"], 2)

    def test_centre_ownership_by_year_stops_before_the_last_autumn(self):
        result = board_counts.count(self.games, "rival", "Germany", [], ["WAR"], [], None)
        self.assertEqual(result["policy_counts"]["owns"]["WAR"], {"1901": {"yes": 1, "of": 2}})

    def test_units_in_a_province_and_the_split_by_a_neighbour(self):
        # The fixture's Autumn 1901 board has a German army in Prussia in both games and none in the Ruhr.
        result = board_counts.count(self.games, "rival", "Germany", [], [], ["PRU", "RUH"], (0, 0), split_by="Russia")
        self.assertEqual(result["policy_counts"]["unit_at"]["PRU"], {"Spring 1901": {"yes": 2, "of": 2}})
        self.assertEqual(result["policy_counts"]["unit_at"]["RUH"], {"Spring 1901": {"yes": 0, "of": 2}})
        self.assertEqual(list(result["split"]), ["ours"])
        self.assertEqual(result["split"]["ours"]["seats"], 2)

    def test_cli_needs_a_check_and_prints_rows_with_turn_links(self):
        with self.assertRaises(SystemExit):
            run(board_counts, [str(self.root), "--policy", "rival", "--as", "Germany"])
        base = [str(self.root), "--policy", "rival"]
        check = ["--as", "Germany", "--order", "A BER - PRU", "--when", "S1901", "--rows"]
        code, text = run(board_counts, base + check)
        self.assertEqual(code, 0)
        self.assertIn("policy, `A BER - PRU`: given in at least one phase by 1 of 2 seats", text)
        self.assertIn("[/replays/ereq_a?turn=0]", text)
        self.assertEqual(run(board_counts, base + ["--as", "Turkey", "--owns", "WAR"])[0], 2)


class SeatRows(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        write_game(self.root, "ereq_a", history(EAST), SEATS, [0.6, 0.1, 0.3], [5, 1, 1])
        write_game(self.root, "ereq_b", history(BLITZ, attack_russia=False), SEATS, [0.2, 0.5, 0.3], [4, 2, 1])
        self.games, _ = load_games([self.root])

    def test_one_row_per_seat_with_its_first_target(self):
        rows = seat_rows.seat_rows(self.games, "rival")
        by_episode = {r["episode"]: r for r in rows}
        self.assertEqual(by_episode["ereq_a"]["first_targets"], {"Russia": "Autumn 1901"})
        self.assertEqual(by_episode["ereq_b"]["first_targets"], {})
        self.assertEqual(by_episode["ereq_a"]["link"], "/replays/ereq_a?seat=0")

    def test_versus_adds_the_other_policys_side_of_the_game(self):
        rows = seat_rows.seat_rows(self.games, "ours", power="Russia", versus="rival")
        row = next(r for r in rows if r["episode"] == "ereq_a")
        self.assertEqual(len(row["versus"]), 1)
        theirs = row["versus"][0]
        self.assertEqual((theirs["power"], theirs["policy_finished"], theirs["other_first_hostile_act_on_policy"]),
                         ("Germany", "behind", "Autumn 1901"))
        self.assertEqual((theirs["other_took_from_policy"], theirs["policy_took_from_other"]), (1, 0))
        self.assertEqual(seat_rows.seat_rows(self.games, "ours", versus="nobody"), [])

    def test_versus_lines_name_both_policies_whichever_way_round_it_is_run(self):
        # --policy may be ours or an opponent, so the text never says "we" or "it"
        code, text = run(seat_rows, [str(self.root), "--policy", "ours", "--versus", "rival", "--sort", "episode"])
        self.assertIn("    rival:v2 Germany: score 0.600, 5 centres; ours finished behind; first hostile act: "
                      "rival on ours Autumn 1901, ours on rival never; rival took 1 from ours, ours took 0 from rival",
                      text)
        code, text = run(seat_rows, [str(self.root), "--policy", "rival", "--versus", "ours", "--sort", "episode"])
        self.assertIn("    ours:v1 Russia: score 0.100, 1 centres; rival finished ahead; first hostile act: "
                      "ours on rival never, rival on ours Autumn 1901; ours took 0 from rival, rival took 1 from ours",
                      text)
        for word in (" we ", " it ", " us", " its "):
            self.assertNotIn(word, text)

    def test_cli_sorts_worst_first_and_limits(self):
        code, text = run(seat_rows, [str(self.root), "--policy", "rival", "--limit", "1"])
        self.assertEqual(code, 0)
        self.assertEqual(len(text.strip().splitlines()), 1)
        self.assertTrue(text.startswith("ereq_b rival:v2 Germany: score 0.200"))
        self.assertEqual(run(seat_rows, [str(self.root), "--policy", "rival", "--as", "Turkey"])[0], 2)


class SeatLog(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.ep = write_game(self.root, "ereq_a", history(EAST), SEATS, [0.6, 0.1, 0.3], [5, 1, 1])
        write_log(self.ep, 1, [
            {"event": "press_in", "turn": 0, "frm": "GERMANY", "to": "us", "text": "Peace in the east?"},
            {"event": "press_out", "turn": 0, "to": "GERMANY", "text": "Agreed."},
            {"event": "tool_call", "wake": "0-1-open", "tool": "read_notes", "arguments": "{}", "result": "none"},
            {"event": "press_commit", "turn": 0, "press_policy": {"stances": {"GERMANY": "ally"}, "notes": "private"},
             "orders": ["A WAR H", "A MOS H"]},
            {"event": "decision", "turn": 0, "phase": "Diplomacy", "units": 2, "centers": 2, "rejected": 0,
             "trace": {"press_commits": 1}, "press_policy": {"stances": {"GERMANY": "ally"}}},
            {"event": "decision", "turn": 0, "phase": "Retreats", "units": 2, "centers": 2, "rejected": 0},
            {"event": "llm_call", "wake": "1-1-open", "status": "404", "error": "No endpoints found"},
            {"event": "decision", "turn": 1, "phase": "Diplomacy", "units": 2, "centers": 2, "rejected": 1,
             "press_policy": None},
        ])

    def test_one_turn_prints_press_commits_and_the_decision(self):
        code, text = run(seat_log, [str(self.root), "--game", "ereq", "--power", "Russia", "--when", "S1901"])
        self.assertEqual(code, 0)
        self.assertIn("## Spring 1901 (turn 0)", text)
        self.assertIn("press in   from GERMANY: Peace in the east?", text)
        self.assertIn("press out  to GERMANY: Agreed.", text)
        self.assertIn('commit     {"stances": {"GERMANY": "ally"}} -> orders ["A WAR H", "A MOS H"]', text)
        self.assertIn("decision   2 units, 2 centres, rejected 0; press_commits 1; policy in force:", text)
        self.assertNotIn("private", text)  # only the policy fields that steer orders are printed
        self.assertNotIn("Autumn 1901", text)
        self.assertNotIn("read_notes", text)  # tool calls are opt-in
        self.assertEqual(text.count("decision   "), 1)  # the retreat line of the same turn is not a movement decision

    def test_errors_and_the_floor_show_in_the_next_turn(self):
        code, text = run(seat_log, [str(self.root), "--game", "ereq_a", "--power", "Russia", "--when", "A1901",
                                    "--events", "decision,error,tool"])
        self.assertIn("ERROR      llm_call status 404: No endpoints found", text)
        self.assertIn("rejected 1; policy in force: none (the search floor played)", text)
        code, text = run(seat_log, [str(self.root), "--game", "ereq_a", "--power", "Russia", "--events", "tool"])
        self.assertIn("tool       read_notes({}) -> none", text)

    def test_a_seat_without_a_log_or_an_unknown_game_exits_2(self):
        self.assertEqual(run(seat_log, [str(self.root), "--game", "ereq_a", "--power", "Germany"])[0], 2)
        self.assertEqual(run(seat_log, [str(self.root), "--game", "ereq_zzz", "--power", "Russia"])[0], 2)


if __name__ == "__main__":
    unittest.main()
