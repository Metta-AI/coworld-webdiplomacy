"""Pure-logic tests for the campaign tools: sizing, seat_bias, ship, run_ab, field,
year_deltas, flag_episodes, mine_variance, gzip_replays. No network, no Docker."""

import argparse
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
        self.assertEqual(run_ab.placeholders(self.TEMPLATE),
                         ["<policy name>", "<code location>", "One sentence: X happens because Y …"])
        self.assertEqual(run_ab.placeholders(self.FILLED), [])
        self.assertEqual(run_ab.placeholders("no frontmatter at all"), [])

    def test_any_unfilled_front_matter_field_stops_the_launch(self):
        # A record with its policy and hypothesis filled, but the rule or the cost still the template's.
        rule = self.FILLED.replace("evals: []", "decision_rule: >\n  ship iff <metric> moves <threshold>\nevals: []")
        self.assertEqual(run_ab.placeholders(rule), ["<metric>", "<threshold>"])
        cost = self.FILLED.replace("evals: []", "evals: []\ncost: <what a run would spend, e.g. 28 press games>")
        self.assertEqual(run_ab.placeholders(cost), ["<what a run would spend, e.g. 28 press games>"])
        # Not placeholders: a comparison in a rule, and anything in the body.
        fine = self.FILLED.replace("evals: []", "decision_rule: ship iff the difference is > 0.04 and |z| < 2 fails\n"
                                   "evals: []") + "\nSee <the folder>.\n"
        self.assertEqual(run_ab.placeholders(fine), [])
        with tempfile.TemporaryDirectory() as tmp:
            record = Path(tmp) / "x.md"
            record.write_text(cost)
            with self.assertRaises(SystemExit) as stopped:
                run_ab.launch(None, record)
        self.assertIn("<what a run would spend", str(stopped.exception))

    def test_screen_stage_ids_are_kept_apart_and_the_variant_reaches_the_request(self):
        text = run_ab.with_evals(self.FILLED, ["xreq_full", "xreq_short"])
        text = run_ab.with_ids(text, "screen", ["xreq_short"])
        self.assertEqual(run_ab.ids_in(text, "screen"), ["xreq_short"])
        self.assertEqual(run_ab.paired_ids(text), ["xreq_full"])  # a paired --resume leaves the screen out

        args = argparse.Namespace(record="2026-01-01-x", a="p:v2", b="p:v1", field_set="set-5", episodes=1,
                                  config=["end_year=1903"])
        full = [str(part) for part in run_ab.paired_request(args, Path("x.json"))]
        short = [str(part) for part in run_ab.paired_request(args, Path("x-screen.json"), "classic-press-short")]
        self.assertNotIn("--variant", full)
        self.assertEqual(short[-4:], ["--variant", "classic-press-short", "--config", "end_year=1903"])
        self.assertIn("2026-01-01-x screen stage on classic-press-short", short)

    def test_evals_round_trip_and_status(self):
        self.assertEqual(run_ab.evals_in(self.FILLED), [])
        text = run_ab.with_evals(self.FILLED, ["xreq_1", "xreq_2"], status="running")
        self.assertEqual(run_ab.evals_in(text), ["xreq_1", "xreq_2"])
        self.assertIn("status: running        # proposed | running", text)  # the comment survives
        more = run_ab.with_evals(text, run_ab.evals_in(text) + ["xreq_3"])
        self.assertEqual(run_ab.evals_in(more), ["xreq_1", "xreq_2", "xreq_3"])
        self.assertIn("status: running", more)  # untouched without a status argument
        self.assertIn("Body mentions --- a dash rule.", more)

    def test_credit_limit_stops_when_the_rest_would_pass_it(self):
        # 14 bodies at 6.7 credits each is 93.8: over 60 after the first, under 100.
        self.assertAlmostEqual(run_ab.over_limit(6.7, 6.7, 13, 60), 93.8)
        self.assertIsNone(run_ab.over_limit(6.7, 6.7, 13, 100))
        self.assertIsNone(run_ab.over_limit(6.7, 6.7, 13, None))   # no limit given
        self.assertIsNone(run_ab.over_limit(93.8, 6.7, 0, 60))     # nothing left to stop
        # The price rose mid-launch: seven bodies in at 6.7, the eighth quoted 9.8.
        self.assertAlmostEqual(run_ab.over_limit(56.7, 9.8, 6, 100), 115.5)
        line = run_ab.stopped_line(1, 14, 3, 6.7, 93.8, 60)
        self.assertIn("1 of 14 batches launched, 3 games, 6.7 credits", line)
        self.assertIn("The limit covers 8 of 14 batches", line)

    def test_added_sets_get_their_own_body_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            bodies = Path(tmp)
            (bodies / "2026-01-01-x-r0.json").write_text("{}")
            self.assertEqual(run_ab.add_set_stem(bodies, "2026-01-01-x"), "2026-01-01-x-add2")
            (bodies / "2026-01-01-x-add2-r0.json").write_text("{}")
            (bodies / "2026-01-01-x-add2-r1.json").write_text("{}")
            self.assertEqual(run_ab.add_set_stem(bodies, "2026-01-01-x"), "2026-01-01-x-add3")

    def test_record_without_an_evals_line_is_an_error(self):
        with self.assertRaises(ValueError):
            run_ab.with_evals("---\nid: x\n---\n", ["xreq_1"])

    def test_the_read_covers_the_folders_the_record_names_and_always_its_own(self):
        base = run_ab.LAB / ".runtime" / "artifacts"
        self.assertEqual(run_ab.artifact_dirs(self.FILLED, "x"), [base / "x"])
        self.assertEqual(run_ab.artifact_dirs(self.FILLED.replace("evals: []", "evals: []\nartifacts: []"), "x"),
                         [base / "x"])
        pooled = self.FILLED.replace("evals: []", "evals: []\nartifacts: [first, .runtime/artifacts/x]  # pooled")
        self.assertEqual(run_ab.artifact_dirs(pooled, "x"), [base / "first", base / "x"])
        other = self.FILLED.replace("evals: []", "evals: []\nartifacts: [first]")
        self.assertEqual(run_ab.artifact_dirs(other, "x"), [base / "first", base / "x"])
        own_first = self.FILLED.replace("evals: []", "evals: []\nartifacts: [`x`, first/, first]")
        self.assertEqual(run_ab.artifact_dirs(own_first, "x"), [base / "x", base / "first"])
        not_a_name = self.FILLED.replace("evals: []", "evals: []\nartifacts: [.., first]")
        self.assertEqual(run_ab.artifact_dirs(not_a_name, "x"), [base / "first", base / "x"])
        # Nothing in the body is read: not a front-matter-like line, and not an `Artifacts:` line.
        body_only = self.FILLED + "\nartifacts: [not-front-matter]\n\nArtifacts: `.runtime/artifacts/elsewhere`\n"
        self.assertEqual(run_ab.artifact_dirs(body_only, "x"), [base / "x"])

    def test_alone_ids_are_kept_apart_so_each_run_can_be_resumed(self):
        text = run_ab.with_evals(self.FILLED, ["xreq_p1", "xreq_p2"], status="running")
        self.assertEqual(run_ab.paired_ids(text), ["xreq_p1", "xreq_p2"])  # no alone lists yet
        text = run_ab.with_ids(run_ab.with_evals(text, run_ab.evals_in(text) + ["xreq_a1"]), "alone_a", ["xreq_a1"])
        text = run_ab.with_ids(run_ab.with_evals(text, run_ab.evals_in(text) + ["xreq_b1"]), "alone_b", ["xreq_b1"])
        text = run_ab.with_ids(run_ab.with_evals(text, run_ab.evals_in(text) + ["xreq_a2"]), "alone_a",
                               ["xreq_a1", "xreq_a2"])
        self.assertEqual(run_ab.evals_in(text), ["xreq_p1", "xreq_p2", "xreq_a1", "xreq_b1", "xreq_a2"])
        self.assertEqual(run_ab.ids_in(text, "alone_a"), ["xreq_a1", "xreq_a2"])
        self.assertEqual(run_ab.ids_in(text, "alone_b"), ["xreq_b1"])
        self.assertEqual(run_ab.paired_ids(text), ["xreq_p1", "xreq_p2"])
        self.assertEqual(text.count("alone_a:"), 1)
        self.assertLess(text.index("alone_a:"), text.index("\n---\n"))  # in the front matter
        self.assertIn("Body mentions --- a dash rule.", text)
        with self.assertRaises(ValueError):
            run_ab.with_ids("---\nid: x\n---\n", "alone_a", ["xreq_1"])

    def test_launch_keeps_an_edit_made_to_the_record_meanwhile_and_prints_the_estimate(self):
        import contextlib
        import io
        import tempfile
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmp:
            lab = Path(tmp)
            (lab / "experiments").mkdir()
            record = lab / "experiments" / "x.md"
            record.write_text(self.FILLED)
            requests = lab / ".runtime" / "requests"
            requests.mkdir(parents=True)
            created = iter(["xreq_1", "xreq_2"])

            def fake_run(cmd, capture=True):
                if "make_request.py" in str(cmd[1]):
                    for name in ("x-r0.json", "x-r0m.json"):
                        (requests / name).write_text("{}")
                    return ""
                if "--dry-run" in cmd:
                    return ""
                batch = next(created)
                if batch == "xreq_1":  # the agent edits the record while the launch is under way
                    record.write_text(record.read_text().replace("Real text.", "Edited meanwhile."))
                return json.dumps({"created": batch, "cost_preview": {"estimated_cost_credits": 1.5}})

            args = mock.Mock(record="x", a="p:v2", b="p:v1", field_set="set", episodes=2,
                             add_set=False, max_credits=None)
            err = io.StringIO()
            with mock.patch.object(run_ab, "LAB", lab), mock.patch.object(run_ab, "run", fake_run), \
                    contextlib.redirect_stderr(err):
                ids = run_ab.launch(args, record)
            text = record.read_text()
        self.assertEqual(ids, ["xreq_1", "xreq_2"])
        self.assertEqual(run_ab.evals_in(text), ["xreq_1", "xreq_2"])
        self.assertIn("Edited meanwhile.", text)
        self.assertIn("status: running", text)
        self.assertIn("launched 2 batches, 4 games; the platform estimates 3.0 credits (0.75 a game)", err.getvalue())

    def launch_in_a_lab(self, record_text, quotes, **options):
        """Run `run_ab.launch` with three bodies and the platform's quote for each; returns (ids, record, stderr)."""
        import contextlib
        import io
        import tempfile
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmp:
            lab = Path(tmp)
            (lab / "experiments").mkdir()
            record = lab / "experiments" / "x.md"
            record.write_text(record_text)
            requests = lab / ".runtime" / "requests"
            requests.mkdir(parents=True)
            created = iter(enumerate(quotes, start=1))

            def fake_run(cmd, capture=True):
                if "make_request.py" in str(cmd[1]):
                    stem = Path(str(cmd[cmd.index("--out") + 1])).stem
                    for index in range(len(quotes)):
                        (requests / f"{stem}-r{index}.json").write_text("{}")
                    return ""
                if "--dry-run" in cmd:
                    return ""
                number, quote = next(created)
                return json.dumps({"created": f"xreq_new{number}", "cost_preview": {"estimated_cost_credits": quote}})

            args = mock.Mock(record="x", a="p:v2", b="p:v1", field_set="set", episodes=3,
                             **{"add_set": False, "max_credits": None, **options})
            err = io.StringIO()
            with mock.patch.object(run_ab, "LAB", lab), mock.patch.object(run_ab, "run", fake_run), \
                    contextlib.redirect_stderr(err):
                ids = run_ab.launch(args, record)
            return ids, record.read_text(), err.getvalue()

    def test_a_credit_limit_stops_the_launch_after_the_first_quote(self):
        ids, text, err = self.launch_in_a_lab(self.FILLED, [6.7, 6.7, 6.7], max_credits=15)
        self.assertEqual(ids, ["xreq_new1"])                       # 3 x 6.7 = 20.1 would pass 15
        self.assertEqual(run_ab.evals_in(text), ["xreq_new1"])     # what was launched is in the record
        self.assertIn("STOPPED at the credit limit: 1 of 3 batches launched, 3 games, 6.7 credits", err)
        ids, _, err = self.launch_in_a_lab(self.FILLED, [6.7, 6.7, 6.7], max_credits=25)
        self.assertEqual(len(ids), 3)
        self.assertNotIn("STOPPED", err)

    def test_a_price_that_rises_during_the_launch_stops_it(self):
        ids, _, err = self.launch_in_a_lab(self.FILLED, [6.7, 9.9, 9.9], max_credits=25)
        self.assertEqual(ids, ["xreq_new1", "xreq_new2"])          # 6.7 + 9.9 + 9.9 = 26.5 would pass 25
        self.assertIn("2 of 3 batches launched", err)

    def test_add_set_appends_to_a_launched_record_and_keeps_the_other_lists(self):
        launched = run_ab.with_ids(run_ab.with_evals(self.FILLED, ["xreq_1", "xreq_alone"], status="running"),
                                   "alone_a", ["xreq_alone"])
        ids, text, _ = self.launch_in_a_lab(launched, [6.7, 6.7, 6.7], add_set=True)
        self.assertEqual(ids, ["xreq_1", "xreq_new1", "xreq_new2", "xreq_new3"])   # every paired id, to fetch
        self.assertEqual(run_ab.evals_in(text), ["xreq_1", "xreq_alone", "xreq_new1", "xreq_new2", "xreq_new3"])
        self.assertEqual(run_ab.ids_in(text, "alone_a"), ["xreq_alone"])
        with self.assertRaises(SystemExit):   # a second plain launch still refuses
            self.launch_in_a_lab(launched, [6.7])
        with self.assertRaises(SystemExit):   # and --add-set needs a launched record
            self.launch_in_a_lab(self.FILLED, [6.7], add_set=True)

    def test_health_launches_the_asked_number_of_games_and_notes_the_id_outside_evals(self):
        import contextlib
        import io
        import tempfile
        from unittest import mock

        commands = []

        def fake_run(cmd, capture=True):
            commands.append([str(part) for part in cmd])
            return "" if "make_request.py" in str(cmd[1]) else json.dumps({"created": "xreq_h"})

        with tempfile.TemporaryDirectory() as tmp:
            record = Path(tmp) / "x.md"
            record.write_text(self.FILLED)
            args = mock.Mock(record="x", a="p:v2", health="set", health_games=3)
            with mock.patch.object(run_ab, "LAB", Path(tmp)), mock.patch.object(run_ab, "run", fake_run), \
                    contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(run_ab.launch_health(args, record), "xreq_h")
            text = record.read_text()
        build = commands[0]
        self.assertEqual(build[build.index("-n") + 1], "3")
        self.assertEqual(build[build.index("--variant") + 1], "classic-press-short")
        self.assertIn("Health game: `xreq_h` (3 games,", text)
        self.assertEqual(run_ab.evals_in(text), [])

    def test_launched_line_without_an_estimate(self):
        self.assertEqual(run_ab.estimate({"created": "x"}), 0.0)
        self.assertEqual(run_ab.launched_line(14, 28, 0.0, "ids are in x.md"),
                         "launched 14 batches, 28 games; the platform gave no estimate; ids are in x.md")

    def test_the_shipped_template_is_a_placeholder_and_names_no_folders(self):
        template = (run_ab.LAB / "experiments" / "_template.md").read_text()
        unfilled = run_ab.placeholders(template)
        for field_name in ("<policy name>", "<policy:vN>", "<metric>", "<what a run would spend"):
            self.assertTrue(any(found.startswith(field_name) for found in unfilled), field_name)
        self.assertEqual(run_ab.artifact_dirs(template, "x"), [run_ab.LAB / ".runtime" / "artifacts" / "x"])


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

    def test_a_deleted_pod_is_flagged_as_a_crash(self):
        seats = [seat("g1", 0, "A", 0.1, taint=["pod_deleted"]), seat("g2", 0, "A", 0.2)]
        found = flag_episodes.seat_flags(seats, "A")[2]
        self.assertEqual([(f["flag"], f["episode_id"], f["detail"]) for f in found],
                         [("crash or dropped orders", "g1", "pod deleted mid-game, no seat log")])

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
