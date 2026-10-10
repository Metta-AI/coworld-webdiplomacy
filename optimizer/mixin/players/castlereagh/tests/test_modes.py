"""Mode selection, config overrides and per-model sidecar settings."""

import os
import unittest
from unittest import mock

import _support  # noqa: F401  (import path)
from castlereagh import bot, config
from castlereagh.press import llm


class ModeTest(unittest.TestCase):
    def test_default_is_search(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(bot.policy_mode(), "search")

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
                                 PRESS_SOUL="castlereagh"):
            bot.apply_overrides("SEARCH_SEEDS=4, SEARCH_RISK=0.5,PRESS_SOUL=bismarck")
            self.assertEqual((config.SEARCH_SEEDS, config.SEARCH_RISK, config.PRESS_SOUL), (4, 0.5, "bismarck"))

    def test_unknown_knob_fails(self):
        with self.assertRaises(AttributeError):
            bot.apply_overrides("NO_SUCH_KNOB=1")


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

    def test_system_prompt_has_soul_harness_and_skills(self):
        prompt = llm.system_prompt("castlereagh")
        self.assertIn("# Castlereagh", prompt)
        self.assertIn("harness rules", prompt)
        self.assertIn("- trust:", prompt)
        self.assertNotIn("Kissinger", prompt)


if __name__ == "__main__":
    unittest.main()
