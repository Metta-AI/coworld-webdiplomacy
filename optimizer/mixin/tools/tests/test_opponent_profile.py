"""opponent_profile.py: what one policy did, measured from the public orders of small synthetic games."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401  (puts the tools folder on sys.path)
import opponent_profile as op
from helpers import FIXTURES

GERMANY, RUSSIA, FRANCE = 4, 7, 2
NAMES = ["Berlin", "Kiel", "Munich", "Prussia", "Warsaw", "Moscow", "Denmark", "Paris", "Burgundy", "Ruhr"]
TERR = {name: i + 1 for i, name in enumerate(NAMES)}
SUPPLY = {"Berlin", "Kiel", "Munich", "Warsaw", "Moscow", "Denmark", "Paris"}
START_UNITS = [(GERMANY, "Army", "Berlin"), (GERMANY, "Fleet", "Kiel"), (GERMANY, "Army", "Munich"),
               (RUSSIA, "Army", "Warsaw"), (RUSSIA, "Army", "Moscow"), (FRANCE, "Army", "Paris")]
START_CENTERS = {"Berlin": GERMANY, "Kiel": GERMANY, "Munich": GERMANY, "Warsaw": RUSSIA, "Moscow": RUSSIA,
                 "Paris": FRANCE}


def order(country, unit, at, kind="Hold", to=None, src=None, success=True, dislodged=False):
    return {"countryID": country, "terrID": TERR[at], "unitType": unit, "type": kind,
            "toTerrID": TERR[to] if to else None, "fromTerrID": TERR[src] if src else None,
            "success": success, "dislodged": dislodged}


def board(turn, phase, units, centers, orders):
    return {"turn": turn, "phase": phase,
            "units": [{"countryID": c, "type": kind, "terrID": TERR[at]} for c, kind, at in units],
            "centers": [{"terrID": TERR[at], "countryID": c} for at, c in centers.items()],
            "orders": orders}


def history(german_spring, attack_russia=True):
    """Spring 1901 (Germany's orders given), Autumn 1901 (Germany takes Warsaw and Denmark when
    `attack_russia`), a winter build, then Spring and Autumn 1902 with everyone holding."""
    spring = german_spring + [order(RUSSIA, "Army", "Warsaw"), order(RUSSIA, "Army", "Moscow"),
                              order(FRANCE, "Army", "Paris", "Move", to="Burgundy")]
    units_autumn = [(GERMANY, "Army", "Prussia"), (GERMANY, "Fleet", "Denmark"), (GERMANY, "Army", "Munich"),
                    (RUSSIA, "Army", "Warsaw"), (RUSSIA, "Army", "Moscow"), (FRANCE, "Army", "Burgundy")]
    if attack_russia:
        autumn = [order(GERMANY, "Army", "Prussia", "Move", to="Warsaw"), order(GERMANY, "Fleet", "Denmark"),
                  order(GERMANY, "Army", "Munich", "Support hold", to="Denmark", success=False),
                  order(RUSSIA, "Army", "Warsaw", dislodged=True), order(RUSSIA, "Army", "Moscow"),
                  # France helps Germany into Warsaw: a support for another power's unit.
                  order(FRANCE, "Army", "Burgundy", "Support move", to="Warsaw", src="Prussia")]
        centers_1902 = {**START_CENTERS, "Warsaw": GERMANY, "Denmark": GERMANY}
        units_1902 = [(GERMANY, "Army", "Warsaw"), (GERMANY, "Fleet", "Denmark"), (GERMANY, "Army", "Munich"),
                      (GERMANY, "Fleet", "Kiel"), (RUSSIA, "Army", "Moscow"), (FRANCE, "Army", "Burgundy")]
    else:
        autumn = [order(c, kind, at) for c, kind, at in units_autumn]
        centers_1902 = {**START_CENTERS, "Denmark": GERMANY}
        units_1902 = units_autumn + [(GERMANY, "Fleet", "Kiel")]
    holds = [order(c, kind, at) for c, kind, at in units_1902]
    return [
        board(0, "Diplomacy", START_UNITS, START_CENTERS, spring),
        board(1, "Diplomacy", units_autumn, START_CENTERS, autumn),
        board(1, "Builds", units_1902, centers_1902, [
            {"countryID": GERMANY, "terrID": TERR["Kiel"], "unitType": None, "type": "Build Fleet",
             "toTerrID": None, "fromTerrID": None, "success": True, "dislodged": False}]),
        board(2, "Diplomacy", units_1902, centers_1902, holds),
        board(3, "Diplomacy", units_1902, centers_1902, holds),
        board(3, "Finished", units_1902, centers_1902, []),
    ]


BLITZ = [order(GERMANY, "Army", "Berlin", "Move", to="Kiel"), order(GERMANY, "Fleet", "Kiel", "Move", to="Denmark"),
         order(GERMANY, "Army", "Munich", "Move", to="Ruhr")]
EAST = [order(GERMANY, "Army", "Berlin", "Move", to="Prussia"), order(GERMANY, "Fleet", "Kiel", "Move", to="Denmark"),
        order(GERMANY, "Army", "Munich")]


def write_game(root: Path, name: str, phases, policies, scores, centers, press=(), variant="Classic press",
               outcome="drawn"):
    """One hosted-layout episode with three seats: Germany, Russia, France (slots 0, 1, 2)."""
    ep = root / name
    ep.mkdir(parents=True)
    countries = [GERMANY, RUSSIA, FRANCE]
    territories = [{"id": TERR[n], "name": n, "supply": n in SUPPLY, "coast": "No"} for n in NAMES]
    frame = {"variant": {"territories": territories}, "history": {"phases": phases},
             "messages": {"messages": list(press)}}
    (ep / "replay.json").write_text(json.dumps([frame]))
    (ep / "results.json").write_text(json.dumps({
        "scores": scores, "countries": countries, "outcome": outcome, "reason": "end_year",
        "members": [{"countryID": str(c), "supplyCenterNo": str(n)} for c, n in zip(countries, centers)],
        "final_state": {"turn": "4", "phase": "Finished"}}))
    participants = [{"position": i, "policy_name": p.split(":v")[0], "version": int(p.split(":v")[1])}
                    for i, p in enumerate(policies)]
    (ep / "episode.json").write_text(json.dumps({"id": name, "status": "completed", "variant_name": variant,
                                                 "participants": participants}))
    return ep


class Profile(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        seats = ["rival:v2", "ours:v1", "filler:v1"]
        write_game(self.root, "ereq_a", history(EAST), seats, [0.6, 0.1, 0.3], [5, 1, 1],
                   press=[{"id": 1, "turn": 0, "phase": "Diplomacy", "timeSent": 1, "fromCountryID": GERMANY,
                           "toCountryID": 0, "message": "Peace"}])
        write_game(self.root, "ereq_b", history(EAST), seats, [0.5, 0.2, 0.3], [5, 1, 1])
        write_game(self.root, "ereq_c", history(BLITZ, attack_russia=False), seats, [0.2, 0.5, 0.3], [4, 2, 1])
        # The field's Germany, for par: another policy at the same power.
        write_game(self.root, "ereq_d", history(BLITZ, attack_russia=False), ["filler:v1", "rival:v2", "ours:v1"],
                   [0.3, 0.4, 0.3], [4, 2, 1])
        games, dropped = op.load_games([self.root])
        self.profile = op.build_profile(games, dropped, "rival", versus="ours")
        self.germany = self.profile["by_power"]["Germany"]

    def test_counts_seats_games_and_versions(self):
        self.assertEqual((self.profile["seats"], self.profile["games"]), (4, 4))
        self.assertEqual(self.profile["versions"], {"rival:v2": 4})
        self.assertEqual(self.profile["variants"], {"classic-press": 4})
        self.assertEqual(self.germany["n"], 3)
        self.assertTrue(self.germany["directional_only"])

    def test_openings_are_counted_and_named(self):
        spring = self.germany["spring_1901"]
        self.assertEqual(self.germany["distinct_spring_openings"], 2)
        self.assertEqual((spring[0]["n"], spring[0]["orders"]), (2, ["A BER - PRU", "A MUN H", "F KIE - DEN"]))
        self.assertIsNone(spring[0]["name"])
        self.assertEqual(spring[1]["name"], "Blitzkrieg, Danish variation")
        self.assertEqual(spring[1]["episodes"], ["ereq_c"])

    def test_first_target_and_first_hostile_turn(self):
        russia = self.germany["hostility"]["Russia"]
        self.assertEqual((russia["games"], russia["first_target_games"], russia["centre_games"]), (2, 2, 2))
        self.assertEqual(russia["median_first"], "Autumn 1901")
        self.assertEqual(self.germany["never_hostile_games"], 1)
        self.assertNotIn("France", self.germany["hostility"])

    def test_retaking_its_own_centre_is_not_a_hostile_act_and_replies_are_marked(self):
        centers = {"WAR": "RUSSIA", "BER": "GERMANY"}
        move = {"type": "move", "to": "WAR", "src": None}
        # A German unit sits in Warsaw, which Russia still owns: Russia moving in is taking back its own.
        self.assertEqual(op.hostile_to(move, "RUSSIA", {"WAR": "GERMANY"}, centers, {"WAR", "MOS"}), (None, None))
        self.assertEqual(op.hostile_to(move, "GERMANY", {"WAR": "RUSSIA"}, centers, {"BER"}), ("RUSSIA", "RUSSIA"))
        support = {"type": "support_move", "to": "WAR", "src": "MOS"}
        # Supporting Russia's own move into Warsaw is help, not an attack on Russia.
        self.assertEqual(op.hostile_to(support, "FRANCE", {"MOS": "RUSSIA", "WAR": "RUSSIA"}, centers, set()),
                         (None, None))
        facts = {1: {"episode": "g", "power": "Germany", "first_hostile": {"RUSSIA": 1}},
                 2: {"episode": "g", "power": "Russia", "first_hostile": {"GERMANY": 3}}}
        op.mark_replies(facts)
        self.assertEqual((facts[1]["replying_to"], facts[2]["replying_to"]), ([], ["GERMANY"]))

    def test_the_field_is_shown_beside_order_mix_and_defence(self):
        self.assertEqual(self.germany["field_order_mix"]["orders"], 3 + 3 + 4 + 4)  # the filler's Germany
        self.assertEqual(self.germany["field_home_centre_lost"], 0)
        # Its Russia in the game without an attack never moves at all: four movement phases of holds.
        self.assertEqual(self.profile["held_to_the_end"],
                         [{"episode": "ereq_d", "power": "Russia", "phases": 4, "units": 2}])

    def test_centres_taken_and_home_centres_lost(self):
        self.assertEqual(self.germany["takes_from"], {"Neutral": 3, "Russia": 2})
        self.assertEqual(self.germany["captured"], {"DEN": 3, "WAR": 2})
        self.assertEqual(self.germany["home_centre_lost"], 0)
        games, dropped = op.load_games([self.root])
        ours = op.build_profile(games, dropped, "ours")["by_power"]["Russia"]
        self.assertEqual(ours["loses_to"], {"Germany": 2})
        self.assertEqual((ours["home_centre_lost"], ours["home_centre_lost_median_year"]), (2, 1901))

    def test_order_mix_supports_and_builds(self):
        mix = self.germany["order_mix"]
        self.assertEqual(mix["orders"], 3 * 3 + 3 * 3 + 2 * 3 * 4)
        self.assertEqual(mix["supports"], 2)
        self.assertEqual(mix["supports_for_another_power"], 0.0)
        self.assertEqual(self.germany["builds"], {"builds": 3, "fleet_share": 1.0, "disbands": 0})
        # The cut support in each of the two attacking games is the only failed order.
        self.assertEqual(mix["failed"], round(2 / mix["orders"], 3))

    def test_results_against_field_par_at_the_same_power(self):
        self.assertAlmostEqual(self.germany["par_score"], 0.3)
        self.assertAlmostEqual(self.germany["score_vs_par"], round((0.6 + 0.5 + 0.2) / 3 - 0.3, 4))
        self.assertEqual(self.germany["top_of_board"], 3)
        self.assertEqual(self.germany["centers_by_year"][1901]["mean"], round((5 + 5 + 4) / 3, 4))
        self.assertEqual(self.germany["centers_by_year"][1901]["field_n"], 1)

    def test_public_press_is_counted_per_power(self):
        self.assertEqual(self.profile["games_with_any_public_press"], 1)
        self.assertEqual(self.germany["press"]["games_with_messages"], 1)
        self.assertEqual(self.germany["press"]["by_year"], {1901: 1})

    def test_versus_says_who_struck_first_and_links_the_phase(self):
        vs = self.profile["versus"]
        self.assertEqual((vs["games_together"], vs["all"]["pairs"]), (4, 4))
        self.assertEqual(vs["all"]["first_hostile_by"], {"them": 2, "neither": 2})
        self.assertEqual(vs["all"]["we_were_first_target"], 2)
        self.assertEqual(vs["all"]["centres_they_took_from_us"], 2)
        self.assertEqual(vs["neighbours"]["pairs"], 3)  # Germany and Russia; France and Russia are not
        self.assertEqual(vs["our_versions"], {"ours:v1": 4})
        self.assertEqual(vs["games_with_two_of_ours"], 0)
        self.assertEqual((vs["all"]["ahead"], vs["all"]["behind"], vs["all"]["tied"]), (1, 3, 0))
        self.assertEqual(vs["one_of_ours"]["pairs"], 4)
        pair = vs["by_powers"][0]  # neighbours first: its Germany beside our Russia, one table
        self.assertEqual((pair["their_power"], pair["our_power"], pair["tables"], pair["pairs"]),
                         ("Germany", "Russia", 1, 3))
        # No other policy ever sat at Russia beside its Germany; the filler's France did, three times.
        self.assertEqual(pair["other_policies_at_our_power"], {"ahead": 0, "behind": 0, "tied": 0})
        worst = vs["our_worst_games"][0]
        self.assertEqual((worst["episode"], worst["link"]), ("ereq_a", "/replays/ereq_a?phase=1"))
        self.assertEqual((worst["first_hostile_turn"], worst["first_capture_turn"]), (1, 1))
        self.assertEqual(len(vs["pairs"]), 4)
        # Par at Russia is the one Russia seat that is not ours (the rival's, 0.4).
        self.assertAlmostEqual(worst["our_vs_par"], round(0.1 - 0.4, 4))
        self.assertAlmostEqual(worst["ours_minus_theirs"], round(0.1 - 0.6, 4))

    def test_supports_for_another_power_are_attributed(self):
        games, dropped = op.load_games([self.root])
        france = op.build_profile(games, dropped, "filler")["by_power"]["France"]
        self.assertEqual(france["order_mix"]["supports_for_another_power"], 1.0)
        # Supporting Germany's move into Warsaw is a hostile act on Russia, not on Germany.
        self.assertEqual(list(france["hostility"]), ["Russia"])

    def test_header_facts_say_where_the_games_came_from_and_what_is_missing(self):
        self.assertEqual(self.profile["sources"], {self.root.name: 4})
        self.assertEqual(self.profile["not_seen_as"], ["England", "France", "Italy", "Austria", "Turkey"])
        self.assertEqual(self.profile["episodes"], ["ereq_a", "ereq_b", "ereq_c", "ereq_d"])
        self.assertEqual(self.germany["tables"], 1)  # the same policy at every power in all three games
        self.assertEqual(self.profile["another_seat_tainted"]["seats"], 0)

    def test_openings_say_how_much_of_the_field_plays_the_same(self):
        spring = self.germany["spring_1901"]
        self.assertEqual((spring[0]["field_same"], spring[0]["field_n"]), (0, 1))
        self.assertEqual((spring[1]["field_same"], spring[1]["field_n"]), (1, 1))  # the filler's Germany

    def test_episodes_to_open_point_at_the_phase(self):
        picks = self.germany["episodes_to_open"]
        misfit = ("one of the 1 games that do not fit the usual first target (Russia); "
                  "in this one it is first on nobody")
        self.assertEqual(picks[misfit], ["/replays/ereq_c"])
        self.assertEqual(picks["usual opening"], ["/replays/ereq_a?phase=0", "/replays/ereq_b?phase=0"])
        self.assertEqual(picks["earliest attack (Autumn 1901 on Russia)"], ["/replays/ereq_a?phase=1"])

    def test_one_version_and_variant_can_be_selected(self):
        write_game(self.root, "ereq_e", history(BLITZ), ["rival:v3", "ours:v1", "filler:v1"], [0.4, 0.3, 0.3],
                   [5, 1, 1], variant="Classic gunboat")
        games, dropped = op.load_games([self.root])
        self.assertEqual(op.build_profile(games, dropped, "rival:v3")["seats"], 1)
        pooled = op.build_profile(games, dropped, "rival")
        self.assertEqual(pooled["variants"], {"classic-press": 4, "classic-gunboat": 1})
        games, dropped = op.load_games([self.root], "classic-press")
        self.assertEqual(dropped, {"not classic-press": 1})
        self.assertEqual(op.build_profile(games, dropped, "rival")["seats"], 4)

    def test_cancelled_games_are_dropped_and_counted(self):
        write_game(self.root, "ereq_x", history(BLITZ), ["rival:v2", "ours:v1", "filler:v1"], [1 / 7] * 3, [3, 2, 1],
                   outcome="cancelled")
        games, dropped = op.load_games([self.root])
        self.assertEqual(len(games), 4)
        self.assertEqual(dropped, {"cancelled, failed or timed out": 1})


class Cli(unittest.TestCase):
    def run_main(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = op.main(argv)
        return code, out.getvalue()

    def test_text_and_json_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_game(Path(tmp), "ereq_a", history(EAST), ["rival:v2", "ours:v1", "filler:v1"], [0.6, 0.1, 0.3],
                       [5, 1, 1])
            code, text = self.run_main([tmp, "--opponent", "rival", "--versus", "ours"])
            self.assertEqual(code, 0)
            for heading in ("# rival: 1 seats in 1 games", "## Openings", "## Whom it attacks", "## Versus ours",
                            "## Episodes to open", "## Limits", "reports/opponents/rival.md"):
                self.assertIn(heading, text)
            code, text = self.run_main([tmp, "--opponent", "rival:v2", "--json"])
            self.assertEqual(json.loads(text)["slug"], "rival")

    def test_one_game_can_be_printed_and_a_profile_repeated_on_the_same_episodes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "batch"
            seats = ["rival:v2", "ours:v1", "filler:v1"]
            write_game(root / "xreq_1", "ereq_a", history(EAST), seats, [0.6, 0.1, 0.3], [5, 1, 1])
            code, text = self.run_main([tmp, "--game", "ereq_a", "--powers", "germany"])
            self.assertEqual(code, 0)
            self.assertIn("## Autumn 1901  (/replays/ereq_a?phase=1)", text)
            self.assertIn("Germany  A PRU - WAR; F DEN H; A MUN S DEN (failed)", text)
            self.assertIn("centres changed: DEN Neutral -> Germany, WAR Russia -> Germany", text)
            self.assertIn("then: Germany build fleet KIE", text)
            self.assertNotIn("Russia   A", text)
            code, text = self.run_main([tmp, "--game", "ereq_a", "--years", "1902", "--logs"])
            self.assertNotIn("## Autumn 1901", text)
            self.assertIn("## Spring 1902", text)
            self.assertNotIn("(ours)", text)  # without --versus nothing is marked
            code, text = self.run_main([tmp, "--game", "ereq_a", "--versus", "ours"])
            seat_lines = {line.split()[0].upper(): line for line in text.splitlines()[2:5]}
            self.assertIn(" (ours) | centres by year", seat_lines["RUSSIA"])
            self.assertNotIn("(ours)", seat_lines["GERMANY"])
            self.assertIn("\nRussia (ours) ", text)
            self.assertNotIn("Germany (ours)", text)
            self.assertEqual(self.run_main([tmp, "--game", "ereq_none"])[0], 2)
            self.assertEqual(self.run_main([tmp, "--game", "ereq_"])[0], 0)  # a unique prefix is enough

            prefix = str(Path(tmp) / "saved")
            code, text = self.run_main([tmp, "--opponent", "rival", "--out", prefix])
            self.assertIn("sources: batch (1 game)", text)
            self.assertEqual(Path(prefix + ".md").read_text(), text)
            write_game(root / "xreq_1", "ereq_late", history(EAST), seats, [0.6, 0.1, 0.3], [5, 1, 1])
            code, text = self.run_main([tmp, "--opponent", "rival", "--episodes", prefix + ".json", "--json"])
            self.assertEqual(json.loads(text)["episodes"], ["ereq_a"])
            self.assertEqual(json.loads(Path(prefix + ".json").read_text())["episodes_read"], ["ereq_a"])
            matchups_json = Path(tmp) / "matchups.json"
            matchups_json.write_text(json.dumps({"our_seats": [{"episode": "ereq_late"}]}))
            code, text = self.run_main([tmp, "--opponent", "rival", "--episodes", str(matchups_json), "--json"])
            self.assertEqual(json.loads(text)["episodes"], ["ereq_late"])

    def test_decisions_come_from_our_own_seats_log_only_without_press_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            ep = write_game(Path(tmp), "ereq_a", history(EAST), ["rival:v2", "ours:v1", "filler:v1"],
                            [0.6, 0.1, 0.3], [5, 1, 1])
            (ep / "policy-logs").mkdir()
            row = {"event": "decision", "turn": 1, "phase": "Diplomacy",
                   "press_policy": {"stances": {"GERMANY": "ally"}, "require_orders": ["A WAR H"], "notes": "secret"}}
            (ep / "policy-logs" / "pv.1.log").write_text(json.dumps(row) + "\n")
            # a rival's log on disk (an account that owns the house bots downloads every seat's)
            theirs = {**row, "press_policy": {"require_orders": ["F KIE - DEN"]}}
            (ep / "policy-logs" / "pv.0.log").write_text(json.dumps(theirs) + "\n")
            ours = 'Russia committed (its log): {"stances": {"GERMANY": "ally"}, "require_orders": ["A WAR H"]}'
            code, text = self.run_main([tmp, "--game", "ereq_a", "--decisions", "--versus", "ours"])
            self.assertIn(ours, text)
            self.assertNotIn("secret", text)
            self.assertNotIn("Germany committed", text)
            self.assertIn("--decisions: seat logs on disk for Germany were left out (not seats of ours)", text)
            # without a name for our policy no log line is printed, and the header says why
            code, text = self.run_main([tmp, "--game", "ereq_a", "--decisions"])
            self.assertNotIn("committed (its log)", text)
            self.assertIn("--decisions printed nothing: it reads only our own seats' logs", text)
            code, text = self.run_main([tmp, "--game", "ereq_a", "--decisions", "--versus", "nobody"])
            self.assertNotIn("committed (its log)", text)
            self.assertIn("--decisions printed nothing: no shown seat is a seat of nobody", text)

    def test_a_pod_deleted_before_log_collection_is_a_tainted_seat(self):
        with tempfile.TemporaryDirectory() as tmp:
            ep = write_game(Path(tmp), "ereq_a", history(EAST), ["rival:v2", "ours:v1", "filler:v1"],
                            [0.6, 0.1, 0.3], [5, 1, 1])
            (ep / "policy-logs").mkdir()
            (ep / "policy-logs" / "pv.1.log").write_text(
                "No logs collected for pod job-1-game-player-1 container player: the pod was deleted.\n")
            games, dropped = op.load_games([Path(tmp)])
            profile = op.build_profile(games, dropped, "rival", versus="ours")
            self.assertEqual(profile["another_seat_tainted"]["seats"], 1)
            self.assertTrue(profile["versus"]["pairs"][0]["tainted"])
            ours = op.build_profile(games, dropped, "ours")
            self.assertEqual(ours["tainted_seats"], {"pod_deleted": 1})
            self.assertEqual(ours["tainted_and_eliminated"], 0)

    def test_a_gunboat_profile_gets_its_own_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_game(Path(tmp), "ereq_a", history(EAST), ["rival:v2", "ours:v1", "filler:v1"], [0.6, 0.1, 0.3],
                       [5, 1, 1], variant="Classic gunboat")
            code, text = self.run_main([tmp, "--opponent", "rival"])
            self.assertIn("reports/opponents/rival-gunboat.md", text)

    def test_unknown_opponent_exits_2_and_lists_who_is_there(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_game(Path(tmp), "ereq_a", history(EAST), ["rival:v2", "ours:v1", "filler:v1"], [0.6, 0.1, 0.3],
                       [5, 1, 1])
            code, text = self.run_main([tmp, "--opponent", "nobody"])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(text)["policies"], ["filler:v1", "ours:v1", "rival:v2"])

    def test_trimmed_replays_are_left_out_not_fatal(self):
        games, dropped = op.load_games([FIXTURES / "hosted"])
        self.assertEqual(games, [])
        self.assertEqual(sum(dropped.values()), 2)


class Helpers(unittest.TestCase):
    def test_policy_matcher_takes_a_name_or_one_version(self):
        self.assertTrue(op.policy_matcher("bot")("bot:v3"))
        self.assertFalse(op.policy_matcher("bot")("bot-press:v3"))
        self.assertFalse(op.policy_matcher("bot:v2")("bot:v3"))

    def test_standard_errors_are_clustered_by_game(self):
        # One score per game: the usual sd / sqrt(n).
        self.assertEqual(op._se([("g1", 0.0), ("g2", 1.0)]), 0.5)
        # The same two games seen twice each (our one score paired with each of its two seats)
        # are still two draws, not four: counting four would give 0.2887.
        self.assertEqual(op._se([("g1", 0.0), ("g1", 0.0), ("g2", 1.0), ("g2", 1.0)]), 0.5)
        self.assertIsNone(op._se([("g1", 0.0), ("g1", 1.0)]))

    def test_slug_drops_the_version(self):
        self.assertEqual(op.slug("Some-Bot:v2"), "some-bot")

    def test_named_openings_use_orders_the_tool_can_print(self):
        for power, table in op.OPENINGS.items():
            self.assertIn(power, op.NEIGHBOURS)
            for _, orders in table:
                for text in orders:
                    self.assertRegex(text, r"^[AF] [A-Z]{3} (H|- [A-Z]{3}|S [A-Z]{3} - [A-Z]{3})$")

    def test_neighbours_are_symmetric(self):
        for power, near in op.NEIGHBOURS.items():
            for other in near:
                self.assertIn(power, op.NEIGHBOURS[other])


if __name__ == "__main__":
    unittest.main()
