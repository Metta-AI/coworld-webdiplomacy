"""Mode selection, config overrides and per-model sidecar settings."""

import contextlib
import io
import json
import os
import unittest
from unittest import mock

import _support  # noqa: F401  (import path)
from castlereagh import bot, config
from castlereagh.press import llm
from castlereagh.press.service import check_policy_shape


class ModeTest(unittest.TestCase):
    def test_default_is_press(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(bot.policy_mode(), "press")

    def test_press(self):
        with mock.patch.dict(os.environ, {"CASTLEREAGH_POLICY": "press"}):
            self.assertEqual(bot.policy_mode(), "press")

    def test_any_other_value_is_an_error(self):
        for value in ("dumbbot", "kissinger", "Search"):
            with mock.patch.dict(os.environ, {"CASTLEREAGH_POLICY": value}):
                with self.assertRaises(SystemExit) as raised:
                    bot.policy_mode()
                self.assertIn("search, press", str(raised.exception))


class OverridesTest(unittest.TestCase):
    def test_types_follow_the_current_value(self):
        with mock.patch.multiple(config, SEARCH_SEEDS=12, SEARCH_RISK=0.0, PRESS_TEMPERATURE=0.4,
                                 PRESS_SOUL="default"):
            bot.apply_overrides("SEARCH_SEEDS=4, SEARCH_RISK=0.5,PRESS_SOUL=mine")
            self.assertEqual((config.SEARCH_SEEDS, config.SEARCH_RISK, config.PRESS_SOUL), (4, 0.5, "mine"))

    def test_an_on_off_value_can_be_turned_off(self):
        with mock.patch.object(config, "SWITCH", True, create=True):
            for text, wanted in (("0", False), ("false", False), ("False", False), ("1", True), ("true", True)):
                bot.apply_overrides(f"SWITCH={text}")
                self.assertIs(config.SWITCH, wanted, text)
            with self.assertRaises(ValueError):
                bot.apply_overrides("SWITCH=off")

    def test_unknown_knob_fails(self):
        with self.assertRaises(AttributeError):
            bot.apply_overrides("NO_SUCH_KNOB=1")

    def test_a_fatal_startup_error_is_logged_as_an_exception_event(self):
        # A bot that dies before its first phase must leave an `exception` line in the seat log
        # (the analysis tools count those), not only a Python traceback on stderr.
        out = io.StringIO()
        env = {"CASTLEREAGH_POLICY": "search", "CASTLEREAGH_OVERRIDES": "NO_SUCH_KNOB=1"}
        with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(out), self.assertRaises(AttributeError):
            bot.main()
        event = json.loads(out.getvalue().splitlines()[-1])
        self.assertEqual((event["event"], event["fatal"]), ("exception", True))
        self.assertIn("NO_SUCH_KNOB", event["error"])


class ModelSettingsTest(unittest.TestCase):
    def test_default_model(self):
        settings, _ = llm.model_settings("z-ai/glm-5.3-flash")
        self.assertEqual(settings["temperature"], config.PRESS_TEMPERATURE)
        self.assertEqual(settings["extra_body"], {"reasoning": {"effort": "low"}})

    def test_quirks(self):
        self.assertNotIn("temperature", llm.model_settings("openai/gpt-6-luna")[0])
        self.assertNotIn("temperature", llm.model_settings("anthropic/claude-haiku-5.5")[0])
        self.assertEqual(llm.model_settings("deepseek/deepseek-v4.1-flash")[0]["extra_body"],
                         {"reasoning": {"effort": "none"}})

    def test_system_prompt_has_the_default_soul_the_harness_rules_and_every_shipped_skill(self):
        prompt = llm.system_prompt(config.PRESS_SOUL)
        self.assertEqual(config.PRESS_SOUL, "default")
        self.assertTrue(prompt.startswith((llm.HERE / "souls" / "default" / "SOUL.md").read_text()))
        self.assertIn("How the harness works", prompt)
        skills = sorted(path.parent.name for path in (llm.HERE / "skills").glob("*/SKILL.md"))
        self.assertEqual(skills, ["agreements", "game-end"])
        for name in skills:
            line = next(line for line in prompt.splitlines() if line.startswith(f"- {name}: "))
            self.assertGreater(len(line), len(f"- {name}: "), "a skill needs a description")

    def test_the_shipped_prompt_names_no_persona(self):
        prompt = llm.system_prompt(config.PRESS_SOUL)
        for word in ("Castlereagh", "Kissinger", "statesman"):
            self.assertNotIn(word, prompt)


if __name__ == "__main__":
    unittest.main()


class PolicyShapeTest(unittest.TestCase):
    """The model writes the policy. A wrong shape must come back as a ValueError it can read."""

    def test_a_well_formed_policy_passes(self):
        check_policy_shape({"stances": {"FRANCE": "ally"}, "trust": {"FRANCE": 0.7}, "risk": 0.2,
                            "expected_orders": ["A PAR - BUR"], "forbid_moves_into": [], "center_values": None})

    def test_each_wrong_shape_names_its_field(self):
        cases = (
            ({"trust": 0.7}, "trust"),
            ({"stances": "ally"}, "stances"),
            ({"center_values": [1]}, "center_values"),
            ({"expected_orders": "A PAR - BUR"}, "expected_orders"),
            ({"require_orders": [{"unit": "A PAR"}]}, "require_orders"),
            ({"forbid_moves_into": {"BUR": True}}, "forbid_moves_into"),
            ({"trust": {"FRANCE": "high"}}, "trust for FRANCE"),
            ({"center_values": {"FRANCE": None}}, "center_values for FRANCE"),
            ({"risk": "low"}, "risk"),
            ("ally with France", "policy"),
        )
        for policy, named in cases:
            with self.assertRaises(ValueError) as raised:
                check_policy_shape(policy)
            self.assertIn(named, str(raised.exception))
