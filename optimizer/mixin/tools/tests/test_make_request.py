import contextlib
import io
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

import _path  # noqa: F401  (puts the tools folder on sys.path)
import make_request


def field(seats: int) -> dict:
    return {"league": "gunboat", "variant": "classic-gunboat",
            "seats": [{"label": f"f{i}:v1", "policy_ref": f"id-{i}"} for i in range(seats)]}


def refs(body: dict) -> list[str]:
    return [seat["player"]["policy_ref"] for seat in body["roster"]]


class Help(unittest.TestCase):
    def test_one_help_screen_serves_both_kinds_and_marks_each_option(self):
        screens = []
        for kind in ("paired", "field"):
            out = io.StringIO()
            with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
                make_request.main([kind, "--help"])
            screens.append(out.getvalue())
        self.assertEqual(screens[0], screens[1])
        text = " ".join(screens[0].split())
        self.assertIn("One help screen serves both kinds", text)
        options = text.split("options:", 1)[1]
        self.assertEqual((options.count("both kinds:"), options.count("paired only"), options.count("field only:")),
                         (10, 1, 1))


class PlainBodies(unittest.TestCase):
    def test_paired_is_one_body_with_free_slots(self):
        bodies = make_request.build_bodies("paired", "me:v2", "me:v1", field(5), "set", 16, note="exp-1")
        self.assertEqual([suffix for suffix, _ in bodies], [""])
        body = bodies[0][1]
        self.assertEqual(refs(body), ["me:v2", "me:v1", "id-0", "id-1", "id-2", "id-3", "id-4"])
        self.assertTrue(all(seat["slot"] == -1 for seat in body["roster"]))
        self.assertNotIn("game_config_overrides", body)
        self.assertEqual(body["num_episodes"], 16)
        self.assertEqual(body["target"]["variant_id"], "classic-gunboat")
        self.assertIn("field set set", body["notes"])
        self.assertIn("exp-1", body["notes"])

    def test_wrong_combinations_are_refused(self):
        with self.assertRaises(ValueError):
            make_request.build_bodies("paired", "a", "b", field(6), "set", 1)   # paired needs five field seats
        with self.assertRaises(ValueError):
            make_request.build_bodies("paired", "a", None, field(5), "set", 1)  # paired needs --b
        with self.assertRaises(ValueError):
            make_request.build_bodies("field", "a", "b", field(6), "set", 1)    # field takes no --b
        with self.assertRaises(ValueError):
            make_request.build_bodies("field", "a", None, field(6), "set", 1, balanced=True, pin_a="Austria")

    def test_config_goes_into_the_overrides_and_the_notes(self):
        config = make_request.parse_config(["end_year=1903", "phase_minutes=2", "press=Regular"])
        self.assertEqual(config, {"end_year": 1903, "phase_minutes": 2, "press": "Regular"})
        (_, body), = make_request.build_bodies("field", "a", None, field(6), "set", 1, no_maps=True, config=config)
        self.assertEqual(body["game_config_overrides"], {"render_maps": False, **config})
        self.assertIn('config end_year=1903 phase_minutes=2 press="Regular"', body["notes"])
        with self.assertRaises(ValueError):
            make_request.parse_config(["end_year"])
        with self.assertRaises(ValueError):   # --balanced already sets countries
            make_request.build_bodies("field", "a", None, field(6), "set", 1, balanced=True,
                                      config={"countries": [1, 2, 3, 4, 5, 6, 7]})

    def test_press_sets_get_an_llm_budget_by_default_and_gunboat_sets_do_not(self):
        # A press game with a zero budget leaves every LLM seat playing its fallback, silently.
        self.assertEqual(make_request.default_llm_budget({"league": "press"}), make_request.PRESS_LLM_BUDGET_USD)
        self.assertGreater(make_request.PRESS_LLM_BUDGET_USD, 0)
        self.assertEqual(make_request.default_llm_budget({"league": "gunboat"}), 0.0)

    def test_a_set_with_placeholder_ids_is_refused(self):
        # field_sets.json ships with the format only; a real set needs ids from tools/field.py.
        # Built here, not read from field_sets.json: that file is the user's and holds real sets.
        for kind, seats in (("paired", 5), ("field", 6)):
            placeholder = field(seats)
            placeholder["seats"][0]["policy_ref"] = "<policy version id from tools/field.py>"
            with self.assertRaisesRegex(ValueError, "placeholder"):
                make_request.build_bodies(kind, "a", "b" if kind == "paired" else None, placeholder, "example", 1)


class BalancedPaired(unittest.TestCase):
    def setUp(self):
        self.bodies = make_request.build_bodies("paired", "A", "B", field(5), "set", 6, balanced=True, no_maps=True)

    def test_fourteen_bodies_both_seat_orders(self):
        self.assertEqual(len(self.bodies), 14)
        suffixes = [suffix for suffix, _ in self.bodies]
        self.assertEqual(len(set(suffixes)), 14)
        for r in range(7):
            plain = dict(self.bodies)[f"-r{r}"]
            mirror = dict(self.bodies)[f"-r{r}m"]
            self.assertEqual(refs(plain)[:2], ["A", "B"])
            self.assertEqual(refs(mirror)[:2], ["B", "A"])
            # Same powers and the same field arrangement in both seat orders.
            self.assertEqual(plain["game_config_overrides"]["countries"], mirror["game_config_overrides"]["countries"])
            self.assertEqual(refs(plain)[2:], refs(mirror)[2:])

    def test_every_policy_plays_every_power_equally_in_each_seat_order(self):
        played = Counter()
        for _, body in self.bodies:
            countries = body["game_config_overrides"]["countries"]
            self.assertEqual(sorted(countries), [1, 2, 3, 4, 5, 6, 7])
            self.assertEqual([seat["slot"] for seat in body["roster"]], list(range(7)))  # pins need fixed slots
            for slot, ref in enumerate(refs(body)):
                played[(ref, countries[slot])] += 1
        for ref in ("A", "B"):
            self.assertEqual([played[(ref, c)] for c in range(1, 8)], [2] * 7)
        for i in range(5):
            self.assertEqual(sum(played[(f"id-{i}", c)] for c in range(1, 8)), 14)

    def test_each_of_a_and_b_holds_each_seat_half_the_time(self):
        first = Counter(refs(body)[0] for _, body in self.bodies)
        self.assertEqual(first, {"A": 7, "B": 7})

    def test_field_order_changes_between_rotations_but_is_reproducible(self):
        orders = {tuple(refs(body)[2:]) for _, body in self.bodies}
        self.assertGreater(len(orders), 1)  # no seat keeps the same neighbours in every game
        again = make_request.build_bodies("paired", "A", "B", field(5), "set", 6, balanced=True, no_maps=True)
        self.assertEqual(self.bodies, again)

    def test_no_maps_override(self):
        self.assertTrue(all(body["game_config_overrides"]["render_maps"] is False for _, body in self.bodies))


class BalancedFieldAndPin(unittest.TestCase):
    def test_balanced_field_is_seven_bodies_and_arms_match(self):
        arm_a = make_request.build_bodies("field", "A", None, field(6), "set", 12, balanced=True)
        arm_b = make_request.build_bodies("field", "B", None, field(6), "set", 12, balanced=True)
        self.assertEqual([suffix for suffix, _ in arm_a], [f"-r{r}" for r in range(7)])
        self.assertEqual(sorted(body["game_config_overrides"]["countries"][0] for _, body in arm_a), list(range(1, 8)))
        for (_, a), (_, b) in zip(arm_a, arm_b):  # the two arms face the same field in the same seats
            self.assertEqual(refs(a)[1:], refs(b)[1:])
            self.assertEqual(a["game_config_overrides"], b["game_config_overrides"])

    def test_pin_a_keeps_our_power_and_rotates_the_field(self):
        bodies = make_request.build_bodies("field", "A", None, field(6), "set", 10, pin_a="Austria")
        self.assertEqual([suffix for suffix, _ in bodies], [f"-p{r}" for r in range(6)])
        seen = Counter()
        for _, body in bodies:
            countries = body["game_config_overrides"]["countries"]
            self.assertEqual(countries[0], 5)  # Austria
            self.assertEqual(sorted(countries), [1, 2, 3, 4, 5, 6, 7])
            self.assertEqual(refs(body)[0], "A")
            for slot in range(1, 7):
                seen[(slot, countries[slot])] += 1
        self.assertTrue(all(count == 1 for count in seen.values()))  # each field slot gets each other power once
        self.assertEqual(len(seen), 36)


class CommandLine(unittest.TestCase):
    def test_writes_one_file_per_body_and_skips_comment_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            sets = Path(tmp) / "field_sets.json"
            sets.write_text(json.dumps({"_note": "example", "five": field(5)}))
            self.assertEqual(sorted(make_request.load_field_sets(sets)), ["five"])
            original = make_request.LAB
            make_request.LAB = Path(tmp)
            out = Path(tmp) / "requests" / "x.json"
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    make_request.main(["paired", "--a", "A", "--b", "B", "--field-set", "five", "-n", "3",
                                       "--balanced", "--out", str(out)])
                written = sorted(p.name for p in out.parent.iterdir())
                self.assertEqual(len(written), 14)
                self.assertIn("x-r0.json", written)
                self.assertIn("x-r6m.json", written)
                self.assertEqual(json.loads((out.parent / "x-r0.json").read_text())["num_episodes"], 3)
                with self.assertRaises(SystemExit):
                    make_request.main(["paired", "--a", "A", "--b", "B", "--field-set", "missing", "-n", "1",
                                       "--out", str(out)])
            finally:
                make_request.LAB = original

if __name__ == "__main__":
    unittest.main()
