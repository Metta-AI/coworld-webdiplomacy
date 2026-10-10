"""The real pydantic-ai agent path with a scripted model: tool schemas, tool calls, run_wake.

Needs pydantic-ai (in the image; locally: uv run --with "pydantic-ai-slim[openai]==2.54.0").
Skipped without it."""

import importlib.util
import unittest
from unittest import mock

import _support
from castlereagh import bot, config
from test_press_player import make_api

HAS_PYDANTIC_AI = importlib.util.find_spec("pydantic_ai") is not None


@unittest.skipUnless(HAS_PYDANTIC_AI, "pydantic-ai not installed")
class AgentWiringTest(unittest.TestCase):
    def test_scripted_model_calls_tools_through_a_wake(self):
        from castlereagh.press import llm
        from castlereagh.press.player import PressPlayer
        from castlereagh.press.tools import Toolbox
        from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
        from pydantic_ai.models.function import FunctionModel

        script = [
            [ToolCallPart("notes", {"key": "plan", "text": "hold the line"})],
            [ToolCallPart("connections", {"province": "PAR"}), ToolCallPart("predict", {"power": "FRANCE"})],
            [ToolCallPart("commit_orders", {"policy": {"risk": 0.5}})],
            [ToolCallPart("send_press", {"to": "FRANCE", "text": "Peace in BUR?"})],
            [TextPart("done")],
        ]
        seen_tools = []

        def model(messages, info):
            seen_tools.extend(t.name for t in info.function_tools) if not seen_tools else None
            return ModelResponse(parts=script.pop(0) if script else [TextPart("done")])

        clock = _support.FakeClock()
        api, *_ = make_api(clock, phase_seconds=60)
        events = []
        with mock.patch.multiple(config, PRESS_STATE_DIR="/tmp/castlereagh-test", SEARCH_TIME_BUDGET_S=2.0):
            player = PressPlayer("castlereagh-press", api, 1, lambda **f: events.append(f), agent=False,
                                 clock=clock, sleep=clock.sleep)
            player.agent = llm.make_agent(FunctionModel(model), "castlereagh", Toolbox(player).all())
            player.play(api.context(), bot.play_phase)
        self.assertIn("commit_orders", seen_tools)
        tools = [e["tool"] for e in events if e["event"] == "tool_call"]
        self.assertEqual(tools, ["notes", "connections", "predict", "commit_orders", "send_press"])
        self.assertEqual(player.notes.data, {"plan": "hold the line"})
        self.assertTrue(any(c[0] == "send" for c in api.calls))
        self.assertEqual(api.calls[-1][:2], ("orders", "Yes"))
        wake = next(e for e in events if e["event"] == "wake")
        self.assertEqual(wake["status"], "ok")
        results = [e["result"] for e in events if e["event"] == "tool_call"]
        self.assertFalse([r for r in results if r.startswith(("ERROR", "TIME UP"))], results)


if __name__ == "__main__":
    unittest.main()
