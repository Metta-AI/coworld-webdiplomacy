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


if __name__ == "__main__":
    unittest.main()
