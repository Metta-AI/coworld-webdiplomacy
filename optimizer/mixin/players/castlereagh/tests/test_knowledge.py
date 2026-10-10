"""Notes store, press log and referee facts."""

import tempfile
import unittest
from pathlib import Path

import _support
from castlereagh import golden
from castlereagh.dumbbot import Board
from castlereagh.press.knowledge import Notes, PressLog, RefereeFacts
from castlereagh.search_orders import dipmap


class NotesTest(unittest.TestCase):
    def test_write_read_delete_and_persist(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "g" / "notes.json"
            notes = Notes(path)
            self.assertEqual(notes.read(), "(no notes yet)")
            notes.write("plan", "Take MUN with Russia")
            notes.write("FRANCE", "wants BEL")
            self.assertIn("### plan\nTake MUN with Russia", notes.read())
            notes.write("FRANCE", "")
            self.assertEqual(Notes(path).data, {"plan": "Take MUN with Russia"})  # survives a restart
            with self.assertRaises(ValueError):
                notes.write("  ", "x")


class PressLogTest(unittest.TestCase):
    def test_season_inline_and_conversation_across_seasons(self):
        events = []
        log = PressLog(2, lambda **f: events.append(f))
        fresh = log.ingest([
            {"id": 2, "turn": 1, "fromCountryID": 2, "toCountryID": 1, "message": "ours"},
            {"id": 1, "turn": 0, "fromCountryID": 1, "toCountryID": 2, "message": "hello"},
            {"id": 3, "turn": 1, "fromCountryID": 4, "toCountryID": 0, "message": "public"},
        ])
        self.assertEqual([m["id"] for m in fresh], [1, 3])  # our own message is not "new press"
        again = [{"id": 1, "turn": 0, "fromCountryID": 1, "toCountryID": 2, "message": "hello"}]
        self.assertEqual(log.ingest(again), [])
        self.assertEqual(len(log.season(1)), 2)
        thread = log.conversation(1)
        self.assertEqual(len(thread), 2)
        self.assertIn('phase="S1901" from="ENGLAND" to="you"', thread[0])
        self.assertEqual([e["event"] for e in events], ["press_in", "press_in"])


class RefereeFactsTest(unittest.TestCase):
    def test_facts_come_from_adjudicated_orders(self):
        data = _support.golden_data()
        variant = data["variant"]
        case = data["cases"][0]
        b = Board(variant, golden._board(variant, case["units"], case["centers"]))
        dm = dipmap(variant)
        terr = dm.terr
        # France (2) moves PAR -> BUR (empty, not owned: no fact) and MAR -> PIE (Italy's unit there).
        units = [{"countryID": 2, "terrID": terr["PAR"]}, {"countryID": 2, "terrID": terr["MAR"]},
                 {"countryID": 3, "terrID": terr["PIE"]}]
        orders = [{"countryID": 2, "terrID": terr["PAR"], "type": "Move", "toTerrID": terr["BUR"], "success": True},
                  {"countryID": 2, "terrID": terr["MAR"], "type": "Move", "toTerrID": terr["PIE"], "success": False}]
        history = {"phases": [{"turn": 0, "phase": "Diplomacy", "units": units, "centers": [], "orders": orders}]}
        events = []
        facts = RefereeFacts(3, lambda **f: events.append(f))
        facts.update(history, b, lambda p: dm.loc[p])
        facts.update(history, b, lambda p: dm.loc[p])  # idempotent per phase
        self.assertEqual(len(facts.events), 1)
        self.assertEqual(facts.events[0]["order"], "MAR -> PIE")
        self.assertTrue(facts.events[0]["against_us"])
        self.assertIn("S1901 FRANCE MAR -> PIE vs US (failed)", facts.recent(1))
        self.assertIn("Attacks on us all game: FRANCE 1", facts.recent(1))
        self.assertIn("MAR -> PIE", facts.of("FRANCE"))
        self.assertEqual(len(events), 1)


if __name__ == "__main__":
    unittest.main()
