"""Pure-logic tests for the campaign tools: sizing, seat_bias, ship, run_ab, field,
year_deltas, flag_episodes, mine_variance, gzip_replays. No network, no Docker."""

import contextlib
import gzip
import io
import json
import math
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401  (puts the tools folder on sys.path)
import field
import flag_episodes
import gzip_replays
import mine_variance
import run_ab
import seat_bias
import ship
import sizing
import year_deltas
from webdip_episodes import load_dirs


def seat(episode, slot, policy, score, power="France", years=None, **extra):
    """A `wd.py seats` row with only the fields these tools read."""
    row = {"episode_id": episode, "slot": slot, "policy": policy, "power": power, "score": score,
           "final_centers": 5, "survived": True, "solo": False, "taint": [],
           "centers_by_year": years or {"1901": 4, "1902": 5}, "orders": 10, "orders_failed": 4, "dislodged": 1,
           "log": {"decisions": 4, "rejected": 0, "exceptions": 0, "trace": {"Move": 6, "Hold": 2, "Support move": 2}}}
    row.update(extra)
    return row


class Sizing(unittest.TestCase):
    def test_games_needed_matches_the_formula(self):
        # n = (z * sd / effect)^2, paired
        self.assertEqual(sizing.games_needed(0.04, 0.34, separate=False, z=2.0), math.ceil((2 * 0.34 / 0.04) ** 2))
        self.assertEqual(sizing.games_needed(0.04, 0.34, False, 2.0), 289)

    def test_separate_arms_pay_root_two(self):
        paired = sizing.games_needed(0.05, 0.2, False, 2.0)
        separate = sizing.games_needed(0.05, 0.2, True, 2.0)
        self.assertEqual(paired, 64)
        self.assertEqual(separate, 128)

    def test_smallest_effect_inverts_games_needed(self):
        effect = sizing.smallest_effect(289, 0.34, False, 2.0)
        self.assertAlmostEqual(effect, 0.04, places=3)
        self.assertLess(sizing.smallest_effect(400, 0.34, False, 2.0), effect)  # more games, smaller effect


    def test_press_is_the_default_league_and_gunboat_keeps_its_measured_values(self):
        self.assertEqual(sizing.LEAGUE_SD["gunboat"], (0.34, 0.22))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            sizing.main(["--games", "100"])
        self.assertIn(f"SD {sizing.LEAGUE_SD['press'][0]}", out.getvalue())


class SeatBias(unittest.TestCase):
    def test_difference_is_first_minus_second_split_by_holder(self):
        seats = [seat("g1", 0, "A", 0.30), seat("g1", 1, "B", 0.10),
                 seat("g2", 0, "B", 0.25), seat("g2", 1, "A", 0.05),
                 seat("g3", 0, "A", 0.20)]  # g3 has no seat 1: skipped
        overall, by_holder = seat_bias.seat_differences(seats, 0, 1)
        self.assertEqual([round(d, 2) for d in overall], [0.20, 0.20])
        self.assertEqual({k: [round(d, 2) for d in v] for k, v in by_holder.items()}, {"A": [0.2], "B": [0.2]})

    def test_tainted_seats_are_left_out(self):
        seats = [seat("g1", 0, "A", 0.30, taint=["exception"]), seat("g1", 1, "B", 0.10)]
        self.assertEqual(seat_bias.seat_differences(seats, 0, 1), ([], {}))

    def test_summary_handles_tiny_and_constant_samples(self):
        self.assertEqual(seat_bias.summary([0.1]), "n=1")
        self.assertIn("mean +0.100", seat_bias.summary([0.1, 0.1]))  # zero spread: no z


class Ship(unittest.TestCase):
    LOG = ("# Version log\n\nintro\n\n| Version | Policy version id | Uploaded (UTC) | Change |\n|---|---|---|---|\n"
           "| v0 | (not uploaded) | — | start |\n\n## v0 details\n\ntext\n")

    def test_row_goes_after_the_last_table_row(self):
        out = ship.insert_row(self.LOG, "| p:v1 | `id` | now | change |\n")
        lines = out.splitlines()
        after_v0 = lines[lines.index("| v0 | (not uploaded) | — | start |") + 1]
        self.assertEqual(after_v0, "| p:v1 | `id` | now | change |")
        self.assertIn("\n\n## v0 details\n", out)
        twice = ship.insert_row(out, "| p:v2 | `id2` | now | change |\n")
        self.assertLess(twice.index("p:v1"), twice.index("p:v2"))

    def test_table_at_end_of_file_and_missing_table(self):
        text = "| Version | id |\n|---|---|\n| v0 | x |"  # no trailing newline
        self.assertTrue(ship.insert_row(text, "| v1 | y |\n").endswith("| v0 | x |\n| v1 | y |\n"))
        with self.assertRaises(ValueError):
            ship.insert_row("# no table here\n", "| v1 | y |\n")

    def test_row_text(self):
        row = ship.version_log_row("p", 3, "abc", "2026-01-01 00:00", "A | B", "search", "KEY=1", None,
                                   "webdip-p:slug", "exp-1", "ply_1")
        self.assertTrue(row.startswith("| p:v3 | `abc` | 2026-01-01 00:00 | A / B | "))  # no stray cell separator
        self.assertIn("`CASTLEREAGH_OVERRIDES=KEY=1`", row)
        self.assertIn("unvalidated (experiment `exp-1`)", row)
        self.assertEqual(row.count("|"), 8)
        press = ship.version_log_row("p", 1, "abc", "t", "c", "press", "", "vendor/model", "tag", "", None)
        self.assertIn("`--llm-model vendor/model`", press)
        self.assertIn("| unvalidated |", press)


    def test_default_press_model_is_the_reference_policys_own(self):
        config = (Path(ship.LAB) / "players" / "castlereagh" / "castlereagh" / "config.py").read_text()
        self.assertIn(f'PRESS_MODEL = "{ship.DEFAULT_LLM_MODEL}"', config)


class RunAbRecord(unittest.TestCase):
    TEMPLATE = ("---\nid: x\npolicy: <policy name>\nstatus: proposed        # proposed | running\n"
                "hypothesis: >\n  One sentence: X happens because Y (at <code location>), causing Z.\nevals: []"
                "               # batch ids\n---\n\n# Title\n")
    FILLED = ("---\nid: x\npolicy: mybot\nstatus: proposed        # proposed | running\nhypothesis: >\n  Real text.\n"
              "evals: []\n---\n\n# Title\n\nBody mentions --- a dash rule.\n")

    def test_placeholders(self):
        self.assertTrue(run_ab.has_placeholders(self.TEMPLATE))
        self.assertFalse(run_ab.has_placeholders(self.FILLED))
        self.assertFalse(run_ab.has_placeholders("no frontmatter at all"))

    def test_evals_round_trip_and_status(self):
        self.assertEqual(run_ab.evals_in(self.FILLED), [])
        text = run_ab.with_evals(self.FILLED, ["xreq_1", "xreq_2"], status="running")
        self.assertEqual(run_ab.evals_in(text), ["xreq_1", "xreq_2"])
        self.assertIn("status: running        # proposed | running", text)  # the comment survives
        more = run_ab.with_evals(text, run_ab.evals_in(text) + ["xreq_3"])
        self.assertEqual(run_ab.evals_in(more), ["xreq_1", "xreq_2", "xreq_3"])
        self.assertIn("status: running", more)  # untouched without a status argument
        self.assertIn("Body mentions --- a dash rule.", more)

    def test_record_without_an_evals_line_is_an_error(self):
        with self.assertRaises(ValueError):
            run_ab.with_evals("---\nid: x\n---\n", ["xreq_1"])


class Field(unittest.TestCase):
    def episode(self):
        seats = [("a:v1", "id-a", True, 0), ("a:v1", "id-a", True, 1), ("b:v2", "id-b", False, 2)]
        return {"participants": [{"label": label, "policy_version_id": pvid, "is_filler": filler, "position": pos,
                                  "player_name": "P"} for label, pvid, filler, pos in seats],
                "participant_scores": [{"position": 0, "score": 0.2}, {"position": 1, "score": 0.4},
                                       {"position": 2, "score": 0.1}],
                # `scores` is by policy version and would merge the two a:v1 seats; it must be ignored.
                "scores": [{"policy_version_id": "id-a", "score": 0.2}, {"policy_version_id": "id-b", "score": 0.1}]}

    def test_a_policy_seated_twice_keeps_both_scores(self):
        seen: dict = {}
        field.add_episode(seen, 5, self.episode())
        field.add_episode(seen, 6, {"participants": self.episode()["participants"][2:], "participant_scores": []})
        rows = field.summarize(seen)
        self.assertEqual([r["label"] for r in rows], ["a:v1", "b:v2"])  # fillers first
        self.assertEqual(rows[0]["seats"], 2)
        self.assertAlmostEqual(rows[0]["mean_score"], 0.3)
        self.assertEqual(rows[1]["rounds"], [5, 6])
        self.assertEqual(rows[1]["seats"], 1)  # the round with no scores adds a sighting, not a score

    def test_seatings_count_each_policys_seats_per_round_newest_first(self):
        seen: dict = {}
        field.add_episode(seen, 5, self.episode())
        field.add_episode(seen, 6, {"participants": self.episode()["participants"][2:], "participant_scores": []})
        self.assertEqual(field.seatings(field.summarize(seen)), {6: {"b:v2": 1}, 5: {"a:v1": 2, "b:v2": 1}})
        self.assertEqual(list(field.seatings(field.summarize(seen))), [6, 5])

    def test_policy_with_no_scores(self):
        seen: dict = {}
        field.add_episode(seen, 1, {"participants": self.episode()["participants"][:1]})
        self.assertIsNone(field.summarize(seen)[0]["mean_score"])


class YearDeltas(unittest.TestCase):
    def test_first_year_is_measured_from_the_starting_count(self):
        seats = [seat("g1", 0, "A", 0.2, power="France", years={"1901": 5, "1902": 4}),
                 seat("g2", 0, "A", 0.2, power="Russia", years={"1901": 5, "1902": 7}),
                 seat("g3", 0, "A", 0.2, taint=["exception"])]
        deltas = year_deltas.year_deltas(seats)
        self.assertEqual(deltas["A"]["1901"], [2, 1])   # France starts with 3, Russia with 4
        self.assertEqual(deltas["A"]["1902"], [-1, 2])


class FlagEpisodes(unittest.TestCase):
    def test_flags(self):
        seats = [
            seat("g1", 0, "A", 0.0, years={"1901": 3, "1902": 0, "1903": 0, "1904": 0, "1905": 0}),
            seat("g1", 1, "B", 1.0, solo=True),
            seat("g2", 0, "A", 0.6, years={"1901": 4, "1902": 8}),
            seat("g3", 0, "A", 0.1, taint=["no_decisions"], log={"decisions": 0}),
        ]
        ours, episodes, flags = flag_episodes.episode_flags(seats, "A", top=1)
        self.assertEqual((ours, episodes), (3, 3))
        self.assertEqual(len(flags["opponent solo"]), 1)
        self.assertIn("B soloed", flags["opponent solo"][0])
        self.assertEqual(len(flags["eliminated early"]), 1)
        self.assertEqual(len(flags["swing of 3+ centres in a year"]), 2)  # 3 -> 0 and 4 -> 8
        self.assertEqual(len(flags["crash or dropped orders"]), 1)        # the seat that never played
        self.assertTrue(flags["worst games"][0].startswith("g1"))
        self.assertTrue(flags["best games"][0].startswith("g2"))

    def test_seat_flags_are_structured_and_the_printed_lines_come_from_them(self):
        seats = [
            seat("g1", 0, "A", 0.0, years={"1901": 3, "1902": 0, "1903": 0, "1904": 0, "1905": 0}),
            seat("g1", 1, "B", 1.0, solo=True),
        ]
        ours, episodes, found = flag_episodes.seat_flags(seats, "A")
        self.assertEqual((len(ours), episodes), (1, 1))
        power = seats[0]["power"]
        self.assertIn({"flag": "opponent solo", "episode_id": "g1", "power": power,
                       "detail": f"B soloed as {seats[1]['power']}"}, found)
        self.assertIn({"flag": "swing of 3+ centres in a year", "episode_id": "g1", "power": power,
                       "detail": "3 -> 0 in 1902"}, found)
        lines = flag_episodes.episode_flags(seats, "A")[2]
        self.assertEqual(lines["swing of 3+ centres in a year"], [f"g1 as {power}: 3 -> 0 in 1902"])

    def test_short_game_has_no_early_elimination_and_does_not_crash(self):
        seats = [seat("g1", 0, "A", 0.0, years={"1901": 0, "1902": 0})]
        _, _, flags = flag_episodes.episode_flags(seats, "A")
        self.assertNotIn("eliminated early", flags)


class MineVariance(unittest.TestCase):
    def test_features_and_unusable_seats(self):
        feats = mine_variance.features(seat("g1", 0, "A", 0.2))
        self.assertAlmostEqual(feats["share of orders: Move"], 0.6)
        self.assertAlmostEqual(feats["failed-order rate"], 0.4)
        self.assertEqual(feats["centres after 1902"], 5.0)
        self.assertIsNone(mine_variance.features(seat("g1", 0, "A", 0.2, log={})))  # no trace: not usable

    def test_demean_removes_the_power_effect(self):
        rows = [("France", 0.5), ("France", 0.3), ("Austria", 0.1), ("Austria", 0.0)]
        self.assertEqual([round(v, 2) for v in mine_variance.demean_by_power(rows)], [0.1, -0.1, 0.05, -0.05])

    def test_correlation_of_degenerate_input_is_zero(self):
        self.assertEqual(mine_variance.correlation([1.0, 1.0, 1.0], [0.1, 0.2, 0.3]), 0.0)
        self.assertAlmostEqual(mine_variance.correlation([1.0, 2.0, 3.0], [0.1, 0.2, 0.3]), 1.0)


class GzipReplays(unittest.TestCase):
    def test_only_fetched_episodes_are_compressed_and_the_loader_still_reads_them(self):
        frames = [{"lifecycle": {"turn": 0, "phase": "Diplomacy"}, "padding": "x" * 5000}]
        with tempfile.TemporaryDirectory() as tmp:
            done, pending = Path(tmp) / "ereq_done", Path(tmp) / "ereq_pending"
            for ep in (done, pending):
                ep.mkdir()
                (ep / "replay.bin").write_text(json.dumps(frames))
            (done / ".done").write_text("now")
            files, saved = gzip_replays.compress_replays([Path(tmp)])
            self.assertEqual(files, 1)
            self.assertGreater(saved, 0)
            self.assertEqual(json.loads(gzip.decompress((done / "replay.bin").read_bytes())), frames)
            self.assertEqual(json.loads((pending / "replay.bin").read_text()), frames)  # still downloading: untouched
            self.assertEqual(gzip_replays.compress_replays([Path(tmp)]), (0, 0))        # already compressed
            load_dirs([Path(tmp)])  # the lab's loader accepts a directory holding a compressed replay


if __name__ == "__main__":
    unittest.main()
