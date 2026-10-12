import contextlib
import io
import json
import statistics
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401  (puts the tools folder on sys.path)
import matchups
from helpers import write_episode

COUNTRIES = [1, 2, 3, 4, 5, 6, 7]  # slot 0 is England ... slot 6 is Russia
FIELD = ["rival-a:v1", "rival-a:v1", "rival-b:v2", "rival-b:v2", "rival-c:v1", "rival-c:v1"]


def game(root: Path, name: str, our_score: float, ours="mine:v1", field=FIELD, hosted=True, variant=None,
         our_centers=5, logs=None, **kwargs):
    """One game with our seat in slot 0 (England) and the rest of the score shared by the field."""
    rest = (1 - our_score) / 6
    ep = write_episode(root / name, [our_score] + [rest] * 6, COUNTRIES, [our_centers] + [4] * 6,
                       seating=[ours, *field], status="completed" if hosted else None, logs=logs, **kwargs)
    if hosted:
        row = json.loads((ep / "episode.json").read_text())
        row.update({"created_at": f"2026-10-{len(name):02d}T00:00:00Z", "variant_name": variant or "Classic press"})
        (ep / "episode.json").write_text(json.dumps(row))
    return ep


class Statistics(unittest.TestCase):
    def test_one_seat_per_game_gives_the_plain_standard_error(self):
        values = [0.1, -0.05, 0.2, 0.0, 0.15]
        s = matchups.stat([(f"g{i}", v) for i, v in enumerate(values)])
        self.assertEqual(s["n"], 5)
        self.assertAlmostEqual(s["se"], statistics.stdev(values) / 5 ** 0.5, places=4)
        self.assertAlmostEqual(s["z"], statistics.mean(values) / (statistics.stdev(values) / 5 ** 0.5), places=2)
        self.assertTrue(s["low_n"])
        self.assertEqual(s["verdict"], "too few games")
        # 95% t interval on 4 degrees of freedom: the critical value is 2.776, not 1.96.
        self.assertAlmostEqual((s["ci"][1] - s["ci"][0]) / 2 / s["se"], 2.776, places=2)

    def test_two_seats_in_one_game_are_not_two_independent_observations(self):
        values = [0.3, 0.1, -0.2, 0.25, -0.1, 0.05]
        apart = matchups.stat([(f"g{i}", v) for i, v in enumerate(values)])
        # The same six values, but seats that agree with each other share a game.
        together = matchups.stat([("a", 0.3), ("a", 0.25), ("b", 0.1), ("b", 0.05), ("c", -0.2), ("c", -0.1)])
        self.assertEqual(together["mean"], apart["mean"])
        self.assertEqual(together["games"], 3)
        self.assertGreater(together["se"], apart["se"])

    def test_verdict_needs_enough_games_and_z_of_two(self):
        strong = matchups.stat([(f"g{i}", 0.1 + 0.01 * (i % 3)) for i in range(20)])
        weak = matchups.stat([(f"g{i}", 0.3 * (-1) ** i + 0.01) for i in range(20)])
        self.assertEqual(strong["verdict"], "above par")
        self.assertEqual(weak["verdict"], "no result")
        self.assertEqual(matchups.stat([])["mean"], None)
        self.assertEqual(matchups.stat([("g", 0.2)])["se"], None)

    def test_several_seats_in_a_game_do_not_reach_the_floor_sooner(self):
        """Sixteen seats in four games are four games: no verdict, however large z is."""
        s = matchups.stat([(f"g{i % 4}", 0.2 + 0.01 * (i % 4)) for i in range(16)])
        self.assertEqual((s["n"], s["games"]), (16, 4))
        self.assertGreater(s["z"], 2)
        self.assertTrue(s["low_n"])
        self.assertEqual(s["verdict"], "too few games")
        # It is still said which way the row leans, as a lead and beside its count.
        self.assertEqual(s["lean"], "above par")
        self.assertEqual(matchups.reading(s), "too few games (4 of 16), leaning above par")

    def test_a_lean_is_only_for_a_row_below_the_floor_whose_interval_excludes_par(self):
        below = matchups.stat([(f"g{i}", -0.06 + 0.02 * (i % 3)) for i in range(14)])
        self.assertEqual((below["verdict"], below["lean"]), ("too few games", "below par"))
        self.assertEqual(matchups.reading(below), "too few games (14 of 16), leaning below par")
        # Two games can give a large z, but their t interval is far too wide to lean on.
        two = matchups.stat([("a", 0.30), ("b", 0.36)])
        self.assertGreater(two["z"], 2)
        self.assertIsNone(two["lean"])
        self.assertEqual(matchups.reading(two), "too few games (2 of 16)")
        noise = matchups.stat([(f"g{i}", 0.3 * (-1) ** i + 0.01) for i in range(10)])
        self.assertIsNone(noise["lean"])
        # At the floor the verdict speaks; there is nothing to lean.
        enough = matchups.stat([(f"g{i}", 0.1 + 0.01 * (i % 3)) for i in range(16)])
        self.assertEqual((enough["verdict"], enough["lean"]), ("above par", None))
        self.assertEqual(matchups.reading(enough), "above par")
        self.assertIsNone(matchups.stat([])["lean"])

    def test_a_local_batch_takes_its_variant_from_run_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            for batch, variant in (("press", "classic-press"), ("gunboat", "classic-gunboat")):
                ep = game(Path(tmp) / batch, "ep-1", 0.3, hosted=False)
                (ep.parent / "run.json").write_text(json.dumps({"variant": variant}))
            bare = game(Path(tmp) / "bare", "ep-1", 0.3, hosted=False)
            self.assertEqual(matchups.variant_of(Path(tmp) / "press" / "ep-1"), "classic-press")
            self.assertEqual(matchups.variant_of(Path(tmp) / "gunboat" / "ep-1"), "classic-gunboat")
            self.assertEqual(matchups.variant_of(bare), "unknown")

    def test_sign_test(self):
        h = matchups.sign_test(16, 4, 2)
        self.assertEqual((h["rate"], h["z"], h["verdict"]), (0.8, 2.68, "we finish ahead"))
        self.assertEqual(matchups.sign_test(3, 0, 0)["verdict"], "too few games")


class Report(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def report(self, policy="mine", **filters):
        return matchups.report(matchups.load_games([self.root]), policy, **filters)

    def test_score_vs_par_uses_the_field_at_our_power(self):
        game(self.root / "xreq_1", "a", 0.4)
        game(self.root / "xreq_1", "bb", 0.1)
        # A game without us: its England seat (a rival, score 0.2) is the only par for England.
        game(self.root / "xreq_1", "ccc", 0.2, ours="rival-d:v1")
        r = self.report()
        self.assertEqual((r["games"], r["seats"]), (2, 2))
        self.assertEqual(r["par"]["classic-press"]["England"], {"n": 1, "score": 0.2, "final_centers": 5.0})
        self.assertAlmostEqual(r["overall"]["vs_par"]["mean"], 0.05)  # mean of +0.2 and -0.1
        self.assertEqual(r["overall"]["score"], 0.25)
        england = r["by_power"][0]
        self.assertEqual((england["power"], england["vs_par"]["n"], england["par"]), ("England", 2, 0.2))
        self.assertEqual(r["by_power"][1]["vs_par"]["n"], 0)  # the six other powers stay as empty rows
        self.assertEqual([s["vs_par"] for s in r["our_seats"]], [0.2, -0.1])
        self.assertEqual(r["our_seats"][0]["opponents"]["rival-a"], ["France", "Italy"])

    def test_sibling_versions_are_neither_par_nor_opponents(self):
        game(self.root, "a", 0.4, field=["mine:v2", *FIELD[1:]])
        game(self.root, "bb", 0.2, ours="rival-d:v1")
        r = self.report("mine:v1")
        self.assertEqual(r["seats"], 1)
        self.assertNotIn("mine", [o["opponent"] for o in r["by_opponent"]])
        self.assertEqual(r["par"]["classic-press"]["France"]["n"], 1)  # v2's France seat is not par
        both = self.report("mine")
        self.assertEqual((both["seats"], both["several_of_ours_games"]), (2, 1))
        self.assertEqual([v["policy"] for v in both["by_version"]], ["mine:v1", "mine:v2"])
        self.assertIn("more than one of our seats", both["caveats"][0])

    def test_tainted_games_are_dropped_and_counted(self):
        game(self.root, "a", 0.4)
        game(self.root, "bb", 0.0, logs={0: [{"event": "exception"}]})
        game(self.root, "ccc", 1 / 7, outcome="cancelled")
        game(self.root, "dddd", 0.2, ours="rival-d:v1")
        r = self.report()
        self.assertEqual(r["seats"], 1)
        self.assertEqual(r["taint"]["games_dropped"], 2)
        self.assertEqual(r["taint"]["flags"], {"cancelled": 1, "exception": 1, "no_decisions": 1})
        self.assertEqual(r["overall"]["raw_including_tainted"]["n"], 3)

    def test_a_seat_whose_pod_was_deleted_drops_its_game_and_is_named(self):
        game(self.root, "a", 0.4)
        dead = game(self.root, "bb", 0.0, logs={0: []})
        (dead / "logs" / "policy_agent_0.log").write_text(
            "No logs collected for pod wd-bb-0: the pod was deleted before log collection\n")
        # A rival's dead pod does not drop the game: only our own seats' taints do.
        theirs = game(self.root, "ccc", 0.3, logs={1: []})
        (theirs / "logs" / "policy_agent_1.log").write_text("No logs collected for pod wd-ccc-1\n")
        game(self.root, "dddd", 0.2, ours="rival-d:v1")
        r = self.report()
        self.assertEqual(r["episodes"], ["a", "ccc"])
        self.assertEqual(r["taint"]["flags"], {"pod_deleted": 1})
        self.assertEqual(r["taint"]["games_dropped"], 1)
        self.assertIn("taint: {'pod_deleted': 1}; games dropped 1", matchups.render(r))

    def test_alone_leaves_paired_games_out_of_everything(self):
        game(self.root, "a", 0.4)
        game(self.root, "bb", 0.3, field=["mine:v2", *FIELD[1:]])  # two of our family: a paired run
        game(self.root, "ccc", 0.2, ours="rival-d:v1")
        both = self.report()
        self.assertEqual((both["games"], both["alone_games"], both["paired_games"]), (2, 1, 1))
        self.assertFalse(both["filters"]["alone"])
        self.assertEqual(both["par"]["classic-press"]["Italy"]["n"], 3)
        alone = self.report(alone=True)
        self.assertEqual((alone["games"], alone["seats"], alone["alone_games"], alone["paired_games"]), (1, 1, 1, 1))
        self.assertEqual(alone["several_of_ours_games"], 0)
        self.assertEqual(alone["episodes"], ["a"])
        self.assertEqual(alone["episodes_read"], ["a", "ccc"])
        self.assertEqual(alone["par"]["classic-press"]["Italy"]["n"], 2)  # the paired game's field is not par
        self.assertIn("alone runs only: 1 paired games left out", matchups.render(alone))
        # One version's seat beside a sibling version is still a paired game.
        self.assertEqual(self.report("mine:v2", alone=True)["games"], 0)
        self.assertEqual(self.report("mine:v2")["paired_games"], 1)

    def test_another_policy_of_ours_is_paired_with_us_and_is_not_an_opponent(self):
        game(self.root, "a", 0.4)
        game(self.root, "bb", 0.3, field=["mine-search:v1", *FIELD[1:]])  # our other name in slot 1 (France)
        plain = self.report(alone=True)
        self.assertEqual((plain["games"], plain["paired_games"], plain["also_ours"]), (2, 0, []))
        self.assertIn("mine-search", [row["opponent"] for row in plain["by_opponent"]])
        named = self.report(alone=True, also_ours=("mine-search",))
        self.assertEqual((named["games"], named["alone_games"], named["paired_games"]), (1, 1, 1))
        self.assertEqual(named["episodes"], ["a"])
        self.assertIn("1 seat one seat of mine or mine-search, 1 seat two or more (left out)", matchups.render(named))
        both = self.report(also_ours=("mine-search:v1",))  # a version is read as its name
        self.assertEqual(both["also_ours"], ["mine-search"])
        self.assertNotIn("mine-search", [row["opponent"] for row in both["by_opponent"]])
        self.assertEqual(both["par"]["classic-press"]["France"]["n"], 1)  # its seat is not par
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = matchups.main([str(self.root), "--policy", "mine", "--alone", "--ours", "mine-search", "--json"])
        self.assertEqual((code, json.loads(out.getvalue())["paired_games"]), (0, 1))

    def test_a_source_read_with_none_of_our_games_is_named(self):
        game(self.root / "league-press", "a", 0.2, ours="rival-d:v1")
        game(self.root / "xreq_1", "bb", 0.3)
        r = self.report()
        self.assertEqual((r["sources"]["league"], r["sources_read"]["league"]), (0, 1))
        text = matchups.render(r)
        self.assertIn("no clean game of mine from league matches: 1 such games were read and count toward par only",
                      text)
        self.assertNotIn("from experience requests:", text)

    def test_sources_and_episode_lists(self):
        game(self.root / "league-press", "a", 0.5)
        game(self.root / "xreq_1", "bb", 0.3)
        game(self.root / "xreq_1", "ccc", 0.0, logs={0: [{"event": "exception"}]})
        game(self.root / "xreq_1", "dddd", 0.1, ours="rival-d:v1")
        r = self.report()
        self.assertEqual(r["sources"], {"league": 1, "xp": 1, "local": 0})
        self.assertEqual(r["episodes"], ["a", "bb"])  # our clean games
        self.assertEqual(r["episodes_read"], ["a", "bb", "ccc", "dddd"])  # the tainted game and the field's too
        self.assertEqual(self.report(source="league")["episodes_read"], ["a"])
        self.assertIn("sources: 1 games from league matches, 1 from experience requests, 0 local | "
                      "2 seat one seat of mine, 0 seat two or more", matchups.render(r))

    def test_the_opponent_table_prints_verdicts_and_no_none(self):
        for i, score in enumerate([0.1, 0.13, 0.19]):
            game(self.root, "w" * (i + 1), score)
        game(self.root, "p" * 6, 0.3, ours="rival-d:v1")
        text = matchups.render(self.report())
        row = next(line for line in text.splitlines() if line.startswith("| rival-a "))
        # Every opponent sat in every game (no "without"), and three games are too few for a verdict.
        self.assertEqual(row, "| rival-a | 3* | -0.160 | -6.05 | - (n=0) | - | - | no comparison | +0.007 | 1-2 "
                              "| -0.58 | too few games | -0.167 | -5.40 | too few games (3 of 16), leaning below par |")
        self.assertNotIn("None", text)

    def test_sources_and_variants_are_kept_apart(self):
        game(self.root / "league-gunboat", "a", 0.5, variant="Classic gunboat")
        game(self.root / "league-gunboat", "bb", 0.3, ours="rival-d:v1", variant="Classic gunboat")
        game(self.root / "xreq_1", "ccc", 0.3)
        game(self.root / "xreq_1", "dddd", 0.1, ours="rival-d:v1")
        game(self.root / "runs", "eeeee", 0.2, hosted=False)
        r = self.report()
        self.assertTrue(r["mixed_variants"])
        self.assertEqual({(s["variant"], s["source"]): s["vs_par"]["mean"] for s in r["by_segment"]},
                         {("classic-gunboat", "league"): 0.2, ("classic-press", "xp"): 0.2, ("unknown", "local"): None})
        self.assertEqual(r["no_par_seats"], 1)  # the local run has no field seat as England
        self.assertEqual([s["source"] for s in r["by_source"]], ["league", "local", "xp"])
        league = self.report(source="league")
        self.assertEqual((league["seats"], league["variants"]), (1, {"classic-gunboat": 1}))
        self.assertFalse(league["mixed_variants"])
        self.assertEqual(self.report(variant="classic-press")["overall"]["vs_par"]["mean"], 0.2)

    def test_opponent_rows(self):
        with_e = ["rival-e:v3", *FIELD[1:]]  # rival-e plays France in these games
        for i, score in enumerate([0.1, 0.1, 0.2]):
            game(self.root, "w" * (i + 1), score, field=with_e)
        for i, score in enumerate([0.4, 0.5]):
            game(self.root, "o" * (i + 4), score)
        game(self.root, "p" * 6, 0.3, ours="rival-d:v1")  # England par 0.3
        r = self.report()
        e = next(o for o in r["by_opponent"] if o["opponent"] == "rival-e")
        self.assertEqual((e["games"], e["versions"]), (3, {"rival-e:v3": 3}))
        self.assertAlmostEqual(e["with"]["mean"], (0.1 + 0.1 + 0.2) / 3 - 0.3, places=4)
        self.assertAlmostEqual(e["without"]["mean"], 0.15, places=4)
        self.assertAlmostEqual(e["difference"]["diff"], e["with"]["mean"] - e["without"]["mean"], places=3)
        # rival-e's share is (1 - ours) / 6: 0.15, 0.15, 0.133 against our 0.1, 0.1, 0.2.
        self.assertEqual((e["head_to_head"]["ahead"], e["head_to_head"]["behind"]), (1, 2))
        self.assertEqual(e["outgrew_us"], {"k": 0, "n": 3, "rate": 0.0})
        self.assertEqual(list(e["by_their_power"]), ["France"])
        self.assertEqual([(p["ours"], p["theirs"], p["vs_par"]["n"]) for p in e["pairs"]], [("England", "France", 3)])
        self.assertEqual(e["paired"]["n"], 3)
        self.assertEqual(r["by_opponent"][0]["games"], 5)  # most games first
        only = self.report(opponent="rival-e")
        self.assertEqual(only["seats"], 3)
        self.assertEqual(only["overall"]["vs_par"]["mean"], e["with"]["mean"])  # the filter does not move par

    def test_cost_and_trajectory(self):
        calls = [{"event": "decision"}, {"event": "llm_call", "status": 200, "cost_usd": 0.02},
                 {"event": "llm_call", "status": 200, "usage": {"cost": 0.01}}]
        game(self.root, "a", 0.4, logs={0: calls}, our_centers=7)
        game(self.root, "bb", 0.2, ours="rival-d:v1")
        r = self.report()
        self.assertEqual(r["cost"], {"seats_with_log": 1, "llm_seats": 1, "usd_per_seat_game": 0.03,
                                     "usd_total": 0.03, "llm_calls": 2, "llm_failed": 0})
        # Fixture games end after turn 4 (autumn 1902) and have no replay: one point, from results.json.
        self.assertEqual(r["trajectory"][0]["years"],
                         [{"year": 1902, "n": 1, "ours": 7.0, "field": 5.0, "diff": 2.0, "se": None}])

    def test_policies_with_seat_logs_come_first(self):
        game(self.root, "a", 0.4, logs={0: [{"event": "decision"}]})
        game(self.root, "bb", 0.2, ours="newer:v1")
        names = [p["name"] for p in matchups.list_policies(matchups.load_games([self.root]))]
        self.assertEqual(names[0], "mine")  # the only one with a log, though "newer" played later
        self.assertEqual(names[1], "newer")

    def test_cli(self):
        game(self.root, "a", 0.4)
        game(self.root, "bb", 0.2, ours="rival-d:v1")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(matchups.main([str(self.root), "--policy", "mine", "--json"]), 0)
        self.assertEqual(json.loads(out.getvalue())["overall"]["vs_par"]["mean"], 0.2)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(matchups.main([str(self.root), "--policy", "mine"]), 0)
            self.assertEqual(matchups.main([str(self.root), "--policy", "nobody"]), 2)
            self.assertEqual(matchups.main([str(self.root), "--list"]), 0)
        self.assertIn("score vs par +0.200", out.getvalue())
        self.assertIn("no seats for this policy", out.getvalue())

    def run_main(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = matchups.main([str(self.root), *args])
        return code, out.getvalue()

    def test_out_saves_the_run_and_episodes_repeats_it(self):
        game(self.root, "a", 0.4)
        game(self.root, "bb", 0.2, ours="rival-d:v1")
        with tempfile.TemporaryDirectory() as scratch:
            prefix = str(Path(scratch) / "run")
            code, text = self.run_main("--policy", "mine", "--out", prefix)
            self.assertEqual(code, 0)
            self.assertEqual(Path(prefix + ".txt").read_text(), text)
            saved = json.loads(Path(prefix + ".json").read_text())
            self.assertEqual((saved["episodes"], saved["episodes_read"]), (["a"], ["a", "bb"]))
            # Games that arrive later do not move a pinned run.
            game(self.root, "ccc", 0.9)
            game(self.root, "dddd", 0.6, ours="rival-d:v1")
            code, text = self.run_main("--policy", "mine", "--episodes", prefix + ".json", "--json")
            self.assertEqual(json.loads(text), saved)
            self.assertEqual(json.loads(self.run_main("--policy", "mine", "--json")[1])["games"], 2)
            # A profile saved by opponent_profile.py --out, and a plain list, pin a run the same way.
            profile, plain = Path(scratch) / "profile.json", Path(scratch) / "ids.txt"
            profile.write_text(json.dumps({"opponent": "rival-a", "episodes": ["a"], "episodes_read": ["a", "bb"]}))
            plain.write_text("a\nbb\n\n")
            for file in (profile, plain):
                code, text = self.run_main("--policy", "mine", "--episodes", str(file), "--json")
                self.assertEqual(json.loads(text), saved)
            # A report saved before `episodes` was written lists only our games: no field, so no par.
            old = Path(scratch) / "old.json"
            old.write_text(json.dumps({"our_seats": [{"episode": "a"}]}))
            code, text = self.run_main("--policy", "mine", "--episodes", str(old), "--json")
            self.assertEqual((json.loads(text)["episodes_read"], json.loads(text)["no_par_seats"]), (["a"], 1))
            (Path(scratch) / "bad.json").write_text("{}")
            with self.assertRaises(SystemExit):
                self.run_main("--policy", "mine", "--episodes", str(Path(scratch) / "bad.json"))

    def test_opponent_profile_reads_a_saved_run(self):
        import opponent_profile
        game(self.root, "a", 0.4)
        game(self.root, "bb", 0.2, ours="rival-d:v1")
        with tempfile.TemporaryDirectory() as scratch:
            prefix = str(Path(scratch) / "run")
            self.run_main("--policy", "mine", "--out", prefix)
            self.assertEqual(opponent_profile.read_episode_list(Path(prefix + ".json")), {"a", "bb"})

    def test_list_takes_the_variant_and_source(self):
        game(self.root / "league-gunboat", "a", 0.5, variant="Classic gunboat")
        game(self.root / "xreq_1", "bb", 0.3, ours="other:v1")
        code, text = self.run_main("--list", "--variant", "classic-gunboat", "--json")
        self.assertEqual(code, 0)
        self.assertEqual([(p["name"], p["games"]) for p in json.loads(text) if p["name"] in ("mine", "other")],
                         [("mine", 1)])
        code, text = self.run_main("--list", "--source", "xp", "--json")
        self.assertEqual([p["name"] for p in json.loads(text) if p["name"] in ("mine", "other")], ["other"])
        self.assertEqual(len([p for p in json.loads(self.run_main("--list", "--json")[1])
                              if p["name"] in ("mine", "other")]), 2)


if __name__ == "__main__":
    unittest.main()
