"""press_audit.py: reading orders, checking claims against them, and building the ledger."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401  (puts the tools folder on sys.path)
import press_audit as pa
from helpers import write_episode


def order(power, text, success=True):
    parsed = pa.parse_order(text)
    row = {
        "power": power,
        "unit": text.split()[0],
        "to": None,
        "src": None,
        "success": success,
        "dislodged": False,
        **parsed,
    }
    row["text"] = pa.order_text(row)
    return row


def phase(turn, orders, units, centers=None, belief=None):
    units = [{"power": p, "unit": "A", "at": at} for p, at in units]
    centers = centers or {}
    return {
        "turn": turn,
        "label": pa.turn_label(turn),
        "orders": orders,
        "units": units,
        "centers": centers,
        "units_end": units,
        "centers_end": centers,
        "belief": belief,
    }


def message(mid="prv-1", turn=0, sender="GERMANY", to="RUSSIA", direction="in"):
    return {
        "id": mid,
        "turn": turn,
        "sent_in": "Spring 1901 Diplomacy",
        "time": 1,
        "from": sender,
        "to": to,
        "direction": direction,
        "text": "words",
    }


def not_moving_to(power, where):
    return {"not": {"p": "moves_to", "power": power, "province": where}}


SPRING = phase(
    0,
    [
        order("GERMANY", "A BER - PRU"),
        order("GERMANY", "A MUN H"),
        order("RUSSIA", "A WAR - SIL", False),
        order("AUSTRIA", "A VIE S A BUD - GAL"),
        order("AUSTRIA", "A BUD - GAL"),
    ],
    [("GERMANY", "BER"), ("GERMANY", "MUN"), ("RUSSIA", "WAR"), ("AUSTRIA", "VIE"), ("AUSTRIA", "BUD")],
    centers={"BER": "GERMANY", "MUN": "GERMANY", "WAR": "RUSSIA", "VIE": "AUSTRIA", "BUD": "AUSTRIA"},
)


class ParseOrder(unittest.TestCase):
    def test_every_order_shape(self):
        self.assertEqual(pa.parse_order("A BUD - SER"), {"at": "BUD", "type": "move", "to": "SER"})
        self.assertEqual(pa.parse_order("a bud-ser"), {"at": "BUD", "type": "move", "to": "SER"})
        self.assertEqual(pa.parse_order("F DEN H"), {"at": "DEN", "type": "hold"})
        self.assertEqual(pa.parse_order("A MUN S A BER"), {"at": "MUN", "type": "support_hold", "to": "BER"})
        self.assertEqual(
            pa.parse_order("A PRU S A WAR - SIL"), {"at": "PRU", "type": "support_move", "src": "WAR", "to": "SIL"}
        )
        self.assertEqual(
            pa.parse_order("F NTH C A LON - NWY"), {"at": "NTH", "type": "convoy", "src": "LON", "to": "NWY"}
        )
        self.assertEqual(pa.parse_order("F STP/SC - BOT")["at"], "STP")  # coasts are dropped

    def test_unreadable_orders_raise(self):
        for text in ("", "A BUD - ", "A BUD X SER"):
            with self.assertRaises(ValueError):
                pa.parse_order(text)


class Predicates(unittest.TestCase):
    def holds(self, pred, window=(SPRING,)):
        return pa.evaluate(pred, list(window))[0]

    def test_order_and_moves_to(self):
        self.assertTrue(self.holds({"p": "order", "power": "GERMANY", "order": "A BER - PRU"}))
        self.assertFalse(self.holds({"p": "order", "power": "GERMANY", "order": "A BER - SIL"}))
        self.assertTrue(self.holds({"p": "moves_to", "power": "RUSSIA", "province": "SIL"}))
        # "success" asks whether the move worked, not only whether it was ordered
        self.assertFalse(self.holds({"p": "moves_to", "power": "RUSSIA", "province": "SIL", "success": True}))

    def test_holds_supports_attacks(self):
        self.assertTrue(self.holds({"p": "holds", "power": "GERMANY", "province": "MUN"}))
        self.assertFalse(self.holds({"p": "holds", "power": "GERMANY", "province": "BER"}))
        self.assertTrue(self.holds({"p": "supports", "power": "AUSTRIA", "of": "AUSTRIA", "province": "GAL"}))
        self.assertFalse(self.holds({"p": "supports", "power": "AUSTRIA", "of": "RUSSIA"}))
        attack = phase(
            1, [order("RUSSIA", "A SIL - BER")], [("RUSSIA", "SIL"), ("GERMANY", "MUN")], centers={"BER": "GERMANY"}
        )
        self.assertTrue(
            self.holds({"p": "attacks", "power": "RUSSIA", "target": "GERMANY"}, [attack])
        )  # an owned centre
        self.assertFalse(self.holds({"p": "attacks", "power": "RUSSIA", "target": "AUSTRIA"}, [attack]))

    def test_leaves_dislodged_bounced_and_narrowed_attacks(self):
        self.assertTrue(self.holds({"p": "leaves", "power": "GERMANY", "province": "BER"}))
        self.assertFalse(self.holds({"p": "leaves", "power": "GERMANY", "province": "MUN"}))
        # success false = ordered and failed (a bounce)
        self.assertTrue(self.holds({"p": "moves_to", "power": "RUSSIA", "province": "SIL", "success": False}))
        self.assertFalse(self.holds({"p": "moves_to", "power": "GERMANY", "province": "PRU", "success": False}))
        self.assertTrue(self.holds({"p": "supports", "power": "AUSTRIA", "province": "GAL", "kind": "move"}))  # no "of"
        self.assertFalse(self.holds({"p": "supports", "power": "AUSTRIA", "province": "GAL", "kind": "hold"}))
        hit = dict(order("FRANCE", "A RUH H"), dislodged=True)
        ruhr = phase(
            2,
            [hit, order("GERMANY", "A MUN - RUH"), order("GERMANY", "A KIE - HOL")],
            [("FRANCE", "RUH"), ("GERMANY", "MUN"), ("GERMANY", "KIE")],
            centers={"HOL": "FRANCE"},
        )
        self.assertTrue(self.holds({"p": "dislodged", "power": "FRANCE", "province": "RUH"}, [ruhr]))
        # "I won't attack your centres" is not broken by bumping a unit
        self.assertTrue(self.holds({"p": "attacks", "power": "GERMANY", "target": "FRANCE", "what": "unit"}, [ruhr]))
        centre = {"p": "attacks", "power": "GERMANY", "target": "FRANCE", "what": "centre"}
        self.assertTrue(self.holds(centre, [ruhr]))
        self.assertFalse(self.holds(dict(centre, unit="MUN"), [ruhr]))  # only the Kiel army went for a centre
        self.assertTrue(self.holds({"p": "attacks", "power": "GERMANY", "provinces": ["RUH", "BUR"]}, [ruhr]))

    def test_unit_filters_support_only_attacks_and_all_inside_any(self):
        self.assertTrue(self.holds({"p": "moves_to", "power": "GERMANY", "province": "PRU", "unit": "BER"}))
        self.assertFalse(self.holds({"p": "moves_to", "power": "GERMANY", "province": "PRU", "unit": "MUN"}))
        galicia = {"p": "attacks", "power": "AUSTRIA", "provinces": ["GAL"]}
        self.assertTrue(self.holds(dict(galicia, how="support")))
        self.assertTrue(self.holds(dict(galicia, how="support", unit="VIE")))
        self.assertFalse(self.holds(dict(galicia, how="support", unit="BUD")))  # BUD moved, it did not support
        munich_holds = {"p": "holds", "power": "GERMANY", "province": "MUN"}
        to_silesia = {"all": [{"p": "order", "power": "GERMANY", "order": "A BER - SIL"}, munich_holds]}
        to_prussia = {"all": [{"p": "order", "power": "GERMANY", "order": "A BER - PRU"}, munich_holds]}
        self.assertFalse(self.holds(to_silesia))
        either = {"any": [to_silesia, to_prussia]}
        self.assertTrue(self.holds(either))

    def test_centre_counts(self):
        board = dict(SPRING, centers_end={"BER": "GERMANY", "MUN": "GERMANY", "WAR": "GERMANY"})
        self.assertTrue(self.holds({"p": "centers", "power": "GERMANY", "count": 3}, [board]))
        self.assertTrue(self.holds({"p": "centers", "power": "GERMANY", "at_least": 2}, [board]))
        self.assertFalse(self.holds({"p": "centers", "power": "GERMANY", "count": 2, "when": "end"}, [board]))
        self.assertTrue(self.holds({"p": "centers", "power": "GERMANY", "count": 2, "when": "start"}, [board]))

    def test_board_facts_use_start_or_end(self):
        later = dict(SPRING, units_end=[{"power": "GERMANY", "unit": "A", "at": "PRU"}], centers_end={"WAR": "GERMANY"})
        self.assertTrue(self.holds({"p": "unit_at", "power": "GERMANY", "province": "BER", "when": "start"}, [later]))
        self.assertFalse(self.holds({"p": "unit_at", "power": "GERMANY", "province": "BER"}, [later]))
        self.assertTrue(self.holds({"p": "owns", "power": "GERMANY", "province": "WAR"}, [later]))

    def test_not_any_and_unverifiable(self):
        self.assertFalse(self.holds(not_moving_to("GERMANY", "PRU")))
        self.assertTrue(self.holds(not_moving_to("GERMANY", "SIL")))
        self.assertTrue(self.holds({"any": [not_moving_to("GERMANY", "PRU"), not_moving_to("GERMANY", "SIL")]}))
        self.assertIsNone(self.holds({"p": "unverifiable", "why": "intent"}))

    def test_over_several_turns_any_phase_counts_and_not_means_never(self):
        autumn = phase(1, [order("GERMANY", "A PRU - WAR")], [("GERMANY", "PRU")])
        self.assertTrue(self.holds({"p": "moves_to", "power": "GERMANY", "province": "WAR"}, [SPRING, autumn]))
        self.assertFalse(self.holds(not_moving_to("GERMANY", "WAR"), [SPRING, autumn]))

    def test_a_broken_part_outweighs_an_unknown_part(self):
        held, _ = pa.evaluate_all([{"p": "unverifiable"}, not_moving_to("GERMANY", "PRU")], [SPRING])
        self.assertIs(held, False)


class CheckClaim(unittest.TestCase):
    def outcome(self, claim, msg=None, phases=(SPRING,)):
        return pa.check_claim(claim, msg or message(), list(phases))

    def test_promise_kept_broken_and_released(self):
        kept = {"kind": "promise", "by": "GERMANY", "commitment": [not_moving_to("GERMANY", "SIL")]}
        broken = {"kind": "promise", "by": "GERMANY", "commitment": [not_moving_to("GERMANY", "PRU")]}
        self.assertEqual(self.outcome(kept)["outcome"], "kept")
        result = self.outcome(broken)
        self.assertEqual(result["outcome"], "broken")
        self.assertIn("GERMANY A BER - PRU (Spring 1901, succeeded)", result["evidence"])
        # "I stay out of PRU if you stay out of SIL": Russia moved on SIL, so Germany is released
        conditional = dict(broken, condition=[not_moving_to("RUSSIA", "SIL")])
        result = self.outcome(conditional)
        self.assertEqual((result["condition"], result["outcome"]), ("unmet", "released"))

    def test_threat_statement_and_request(self):
        threat = {
            "kind": "threat",
            "by": "GERMANY",
            "condition": [{"p": "moves_to", "power": "RUSSIA", "province": "SIL"}],
            "commitment": [{"p": "moves_to", "power": "GERMANY", "province": "PRU"}],
        }
        self.assertEqual(self.outcome(threat)["outcome"], "carried_out")
        bluff = dict(threat, commitment=[{"p": "moves_to", "power": "GERMANY", "province": "WAR"}])
        self.assertEqual(self.outcome(bluff)["outcome"], "not_carried_out")
        idle = dict(threat, condition=[{"p": "moves_to", "power": "RUSSIA", "province": "PRU"}])
        self.assertEqual(self.outcome(idle)["outcome"], "not_triggered")
        statement = {
            "kind": "statement",
            "by": "GERMANY",
            "commitment": [{"p": "holds", "power": "GERMANY", "province": "MUN"}],
        }
        self.assertEqual(self.outcome(statement)["outcome"], "true")
        request = {"kind": "request", "by": "RUSSIA", "commitment": [not_moving_to("RUSSIA", "SIL")]}
        self.assertEqual(self.outcome(request)["outcome"], "refused")

    def test_unverifiable_and_a_window_past_the_end_of_the_game(self):
        vague = {"kind": "promise", "by": "GERMANY", "commitment": [{"p": "unverifiable", "why": "goodwill"}]}
        self.assertEqual(self.outcome(vague)["outcome"], "unverifiable")
        late = {"kind": "promise", "by": "GERMANY", "turns": [8, 9], "commitment": [not_moving_to("GERMANY", "PRU")]}
        self.assertEqual(self.outcome(late)["outcome"], "not_reached")

    def test_a_claim_defaults_to_the_turn_it_was_said_in(self):
        autumn = phase(1, [order("GERMANY", "A PRU H")], [("GERMANY", "PRU")])
        claim = {"kind": "promise", "by": "GERMANY", "commitment": [not_moving_to("GERMANY", "PRU")]}
        self.assertEqual(self.outcome(claim, message(turn=1), [SPRING, autumn])["outcome"], "kept")
        self.assertEqual(self.outcome(claim, message(turn=0), [SPRING, autumn])["outcome"], "broken")


class Stance(unittest.TestCase):
    def test_relied_on_reads_stance_trust_and_expected_orders(self):
        self.assertIsNone(pa.relied_on("GERMANY", None, SPRING))
        self.assertIsNone(pa.relied_on("GERMANY", {}, SPRING))
        self.assertTrue(pa.relied_on("GERMANY", {"stances": {"GERMANY": "ally"}}, SPRING))
        self.assertTrue(pa.relied_on("GERMANY", {"trust": {"GERMANY": 0.8}}, SPRING))
        self.assertFalse(pa.relied_on("GERMANY", {"trust": {"GERMANY": 0.2}}, SPRING))
        self.assertFalse(pa.relied_on("GERMANY", {"stances": {"GERMANY": "enemy"}, "trust": {"GERMANY": 0.9}}, SPRING))
        # an expected order counts for the power whose unit it names
        expecting = {"expected_orders": ["A BER - PRU"]}
        self.assertTrue(pa.relied_on("GERMANY", expecting, SPRING))
        self.assertIsNone(pa.relied_on("AUSTRIA", expecting, SPRING))

    def test_categories_weigh_the_speakers_word(self):
        cat = pa.category
        self.assertEqual(cat("promise", "GERMANY", "broken", True, "RUSSIA"), "betrayed")
        self.assertEqual(cat("statement", "GERMANY", "false", True, "RUSSIA"), "deceived")
        self.assertEqual(cat("promise", "GERMANY", "kept", True, "RUSSIA"), "trusted_rightly")
        self.assertEqual(cat("promise", "GERMANY", "kept", False, "RUSSIA"), "doubted_wrongly")
        self.assertEqual(cat("promise", "GERMANY", "broken", False, "RUSSIA"), "doubted_rightly")
        self.assertEqual(cat("promise", "GERMANY", "broken", None, "RUSSIA"), "false_no_stance")
        self.assertEqual(cat("promise", "GERMANY", "released", True, "RUSSIA"), "none")
        self.assertEqual(cat("promise", "RUSSIA", "broken", None, "RUSSIA"), "we_broke_our_word")
        # requests and proposals do not put anyone's honesty on the line
        self.assertEqual(cat("request", "GERMANY", "refused", True, "RUSSIA"), "none")
        self.assertEqual(cat("proposal", "GERMANY", "not_followed", True, "RUSSIA"), "none")


class Audit(unittest.TestCase):
    LEDGER = {
        "episode": "ep",
        "slot": 0,
        "policy": "mine:v1",
        "our_power": "RUSSIA",
        "score": 0.2,
        "outcome": "drawn",
        "belief_logged": True,
        "phases": [dict(SPRING, belief={"stances": {"GERMANY": "ally"}})],
        "messages": [message("prv-1"), message("prv-2", sender="RUSSIA", to="GERMANY", direction="out")],
    }
    CLAIMS = {
        "prv-1": [
            {
                "kind": "promise",
                "by": "GERMANY",
                "quote": "PRU stays empty",
                "commitment": [not_moving_to("GERMANY", "PRU")],
            }
        ],
        "prv-2": [],
    }

    def test_audit_marks_the_betrayal_and_summarizes_by_power(self):
        data = pa.audit(self.LEDGER, self.CLAIMS)
        claim = data["messages"][0]["claims"][0]
        self.assertEqual((claim["outcome"], claim["relied"], claim["category"]), ("broken", True, "betrayed"))
        germany = data["summary"]["powers"]["GERMANY"]
        self.assertEqual((germany["claims"], germany["did_not_hold"], germany["held_share"]), (1, 1, 0.0))
        self.assertEqual(germany["flagged"][0]["quote"], "PRU stays empty")
        self.assertEqual(data["summary"]["messages_with_claims"], 1)

    def test_a_statement_about_another_power_is_weighed_against_its_speaker(self):
        # Germany tells us "Russia moved on SIL": true, and it is Germany's word, not Russia's.
        claims = {
            "prv-1": [
                {"kind": "statement", "commitment": [{"p": "moves_to", "power": "RUSSIA", "province": "SIL"}]},
                {"kind": "request", "commitment": [not_moving_to("RUSSIA", "SIL")]},
                {"kind": "proposal", "commitment": [not_moving_to("GERMANY", "PRU")]},
            ],
            "prv-2": [],
        }
        data = pa.audit(self.LEDGER, claims)
        statement, request, proposal = data["messages"][0]["claims"]
        self.assertEqual((statement["outcome"], statement["category"]), ("true", "trusted_rightly"))
        self.assertEqual((request["outcome"], proposal["outcome"]), ("refused", "not_followed"))
        powers = data["summary"]["powers"]
        self.assertEqual((powers["GERMANY"]["claims"], powers["GERMANY"]["held"]), (2, 1))  # statement + proposal
        # the request counts against the power that was asked: us
        self.assertEqual(
            (powers["RUSSIA"]["asked"], powers["RUSSIA"]["complied"], powers["RUSSIA"]["claims"]), (1, 0, 0)
        )

    def test_every_message_needs_an_entry_and_claims_are_validated(self):
        with self.assertRaisesRegex(ValueError, "no entry for 1 message"):
            pa.audit(self.LEDGER, {"prv-1": []})
        bad_kind = {"prv-1": [{"kind": "lie", "by": "GERMANY", "commitment": [{"p": "unverifiable"}]}], "prv-2": []}
        with self.assertRaisesRegex(ValueError, "prv-1 claim 1: kind"):
            pa.audit(self.LEDGER, bad_kind)
        no_trigger = {
            "prv-1": [{"kind": "threat", "by": "GERMANY", "commitment": [{"p": "unverifiable"}]}],
            "prv-2": [],
        }
        with self.assertRaisesRegex(ValueError, "a threat needs a condition"):
            pa.audit(self.LEDGER, no_trigger)
        public = dict(self.LEDGER, messages=[dict(message("pub-1"), to="ALL"), self.LEDGER["messages"][1]])
        with self.assertRaisesRegex(ValueError, "needs 'asked'"):
            pa.audit(public, {"pub-1": [{"kind": "request", "commitment": [{"p": "unverifiable"}]}], "prv-2": []})
        bad_order = {
            "prv-1": [
                {
                    "kind": "promise",
                    "by": "GERMANY",
                    "commitment": [{"p": "order", "power": "GERMANY", "order": "nonsense here now"}],
                }
            ],
            "prv-2": [],
        }
        with self.assertRaisesRegex(ValueError, "prv-1 claim 1: cannot read order"):
            pa.audit(self.LEDGER, bad_order)

    def test_the_report_shows_text_as_text(self):
        ledger = dict(
            self.LEDGER,
            messages=[dict(message("prv-1"), text="<script>x</script> PRU stays empty"), self.LEDGER["messages"][1]],
        )
        page = pa.render_report(pa.audit(ledger, self.CLAIMS))
        self.assertNotIn("<script>x", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("we relied on it: betrayed", page)


class Ledger(unittest.TestCase):
    def test_extract_reads_orders_press_and_beliefs_for_our_seat(self):
        territories = [
            {"id": 1, "name": "Berlin", "supply": True, "coast": "No"},
            {"id": 2, "name": "Prussia", "supply": False, "coast": "No"},
            {"id": 3, "name": "St. Petersburg (South Coast)", "supply": False, "coast": "Child"},
            {"id": 4, "name": "Gulf of Bothnia", "supply": False, "coast": "No"},
        ]
        history = [
            {
                "turn": 0,
                "phase": "Diplomacy",
                "units": [
                    {"countryID": 4, "type": "Army", "terrID": 1},
                    {"countryID": 7, "type": "Fleet", "terrID": 3},
                ],
                "centers": [{"terrID": 1, "countryID": 4}],
                "orders": [
                    {
                        "countryID": 4,
                        "terrID": 1,
                        "unitType": "Army",
                        "type": "Move",
                        "toTerrID": 2,
                        "fromTerrID": None,
                        "success": True,
                        "dislodged": False,
                    },
                    {
                        "countryID": 7,
                        "terrID": 3,
                        "unitType": "Fleet",
                        "type": "Move",
                        "toTerrID": 4,
                        "fromTerrID": None,
                        "success": True,
                        "dislodged": False,
                    },
                ],
            },
            {"turn": 0, "phase": "Retreats", "units": [], "centers": [], "orders": []},
        ]
        public = {
            "id": 9,
            "turn": 0,
            "phase": "Diplomacy",
            "timeSent": 5,
            "fromCountryID": 4,
            "toCountryID": 0,
            "message": "Peace to all",
        }
        frame = {
            "variant": {"territories": territories},
            "history": {"phases": history},
            "messages": {"messages": [public]},
        }
        private = [
            {
                "id": 1,
                "turn": 0,
                "phase": "Diplomacy",
                "timeSent": 3,
                "fromCountryID": 4,
                "toCountryID": 7,
                "message": "I&rsquo;ll leave PRU empty",
            },
            {
                "id": 2,
                "turn": 0,
                "phase": "Retreats",
                "timeSent": 8,
                "fromCountryID": 7,
                "toCountryID": 4,
                "message": "Noted",
            },
        ]
        logs = {
            6: [
                {"event": "press_commit", "turn": 0, "press_policy": {"stances": {"GERMANY": "ally"}}},
                {"event": "decision", "turn": 0, "phase": "Diplomacy", "rejected": 0},
                {"event": "private_press", "archive": {"messages": private}},
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            ep = write_episode(Path(tmp) / "ep", [1 / 7] * 7, list(range(1, 8)), [3] * 7, logs=logs)
            (ep / "replay").write_text(json.dumps([frame]))
            ledger = pa.build_ledger(ep, 6)
            with self.assertRaisesRegex(ValueError, "no seat log for slot 2"):
                pa.build_ledger(ep, 2)
        self.assertEqual(ledger["our_power"], "RUSSIA")
        self.assertEqual(len(ledger["phases"]), 1)  # only movement phases
        spring = ledger["phases"][0]
        self.assertEqual([o["text"] for o in spring["orders"]], ["A BER - PRU", "F STP - BOT"])
        self.assertEqual(spring["centers"], {"BER": "GERMANY"})
        self.assertEqual(spring["belief"], {"stances": {"GERMANY": "ally"}})
        said = {m["id"]: m for m in ledger["messages"]}
        self.assertEqual(said["prv-1"]["text"], "I’ll leave PRU empty")  # HTML entities decoded
        self.assertEqual((said["prv-1"]["direction"], said["prv-2"]["direction"]), ("in", "out"))
        self.assertEqual(said["prv-2"]["turn"], 1)  # press during retreats is about the next movement turn
        self.assertEqual((said["pub-9"]["to"], said["pub-9"]["turn"]), ("ALL", 0))

    def test_the_three_commands_run_end_to_end(self):
        # extract -> (claims filled in) -> verify -> report, through the command line
        territories = [
            {"id": 1, "name": "Berlin", "supply": True, "coast": "No"},
            {"id": 2, "name": "Prussia", "supply": False, "coast": "No"},
        ]
        move = {"countryID": 4, "terrID": 1, "unitType": "Army", "type": "Move", "toTerrID": 2, "fromTerrID": None,
                "success": True, "dislodged": False}  # fmt: skip
        history = [{"turn": 0, "phase": "Diplomacy", "units": [{"countryID": 4, "type": "Army", "terrID": 1}],
                    "centers": [{"terrID": 1, "countryID": 4}], "orders": [move]}]  # fmt: skip
        frame = {"variant": {"territories": territories}, "history": {"phases": history}, "messages": {"messages": []}}
        said = {"id": 1, "turn": 0, "phase": "Diplomacy", "timeSent": 3, "fromCountryID": 4, "toCountryID": 7,
                "message": "PRU stays empty"}  # fmt: skip
        logs = {6: [{"event": "decision", "turn": 0, "phase": "Diplomacy", "rejected": 0},
                    {"event": "private_press", "archive": {"messages": [said]}}]}  # fmt: skip
        with tempfile.TemporaryDirectory() as tmp:
            ep = write_episode(Path(tmp) / "ep", [1 / 7] * 7, list(range(1, 8)), [3] * 7, logs=logs)
            (ep / "replay").write_text(json.dumps([frame]))
            out = Path(tmp) / "out"
            with contextlib.redirect_stdout(io.StringIO()):
                pa.main(["extract", str(ep), "--slot", "6", "--out", str(out)])
                self.assertEqual(json.loads((out / "claims.json").read_text()), {"prv-1": []})
                claim = {"kind": "promise", "quote": "PRU stays empty", "commitment": [not_moving_to("GERMANY", "PRU")]}
                (out / "claims.json").write_text(json.dumps({"prv-1": [claim]}))
                pa.main(["extract", str(ep), "--slot", "6", "--out", str(out)])  # must not wipe filled-in claims
                printed = io.StringIO()
                with contextlib.redirect_stdout(printed):
                    pa.main(["verify", str(out)])
                pa.main(["report", str(out)])
            self.assertEqual(json.loads(printed.getvalue())["powers"]["GERMANY"]["did_not_hold"], 1)
            self.assertEqual(
                json.loads((out / "audit.json").read_text())["messages"][0]["claims"][0]["outcome"], "broken"
            )
            self.assertIn("PRU stays empty", (out / "audit.html").read_text())

    def test_the_province_table_matches_the_reference_policy(self):
        dipmap = Path(pa.__file__).resolve().parents[1] / "players" / "castlereagh" / "castlereagh" / "dipmap.py"
        if not dipmap.exists():
            self.skipTest("the reference policy is not in this lab")
        scope: dict = {}
        exec(dipmap.read_text().split("class DipMap")[0], scope)  # the tables only, no imports needed
        self.assertEqual(pa.ABBREVIATION, scope["ABBREVIATION"])
        self.assertEqual(pa.POWER, scope["POWER"])


if __name__ == "__main__":
    unittest.main()
