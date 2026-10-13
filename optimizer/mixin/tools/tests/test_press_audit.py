"""press_audit.py: reading orders, checking claims against them, and building the ledger."""

import contextlib
import inspect
import io
import json
import re
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401  (puts the tools folder on sys.path)
import press_audit as pa
import press_report
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


def message(mid="prv-1", turn=0, sender="GERMANY", to="RUSSIA", direction="in", text="words"):
    return {
        "id": mid,
        "turn": turn,
        "sent_in": "Spring 1901 Diplomacy",
        "time": 1,
        "from": sender,
        "to": to,
        "direction": direction,
        "text": text,
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
        # The reference policy's word for it is "hostile", usually logged with no trust number.
        self.assertFalse(pa.relied_on("GERMANY", {"stances": {"GERMANY": "hostile"}}, SPRING))
        self.assertIsNone(pa.relied_on("GERMANY", {"stances": {"GERMANY": "neutral"}}, SPRING))
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
        # a promise to attack us is not one we could rely on or doubt
        self.assertEqual(cat("promise", "GERMANY", "broken", True, "RUSSIA", against_us=True), "attack_not_made")
        self.assertEqual(cat("promise", "GERMANY", "kept", False, "RUSSIA", against_us=True), "attack_announced")
        self.assertEqual(cat("statement", "GERMANY", "false", True, "RUSSIA", against_us=True), "deceived")
        # requests and proposals do not put anyone's honesty on the line
        self.assertEqual(cat("request", "GERMANY", "refused", True, "RUSSIA"), "none")
        self.assertEqual(cat("proposal", "GERMANY", "not_followed", True, "RUSSIA"), "none")


def bul_is_yours():
    return {"kind": "promise", "commitment": [{"not": {"p": "attacks", "power": "TURKEY", "provinces": ["BUL"]}}]}


class HelpIsNotAnAttack(unittest.TestCase):
    # Hosted 2026-10-10: Turkey said "BUL is yours this autumn", then supported our RUM - BUL twice.
    BOARD = phase(
        5,
        [order("RUSSIA", "A RUM - BUL"), order("TURKEY", "A GRE S A RUM - BUL"), order("AUSTRIA", "A BUL H")],
        [("RUSSIA", "RUM"), ("TURKEY", "GRE"), ("AUSTRIA", "BUL")],
        centers={"BUL": "AUSTRIA"},
    )
    def outcome(self, to):
        said = message("prv-9", turn=5, sender="TURKEY", to=to)
        return pa.check_claim(bul_is_yours(), said, [self.BOARD])["outcome"]

    def test_supporting_the_addressees_own_move_keeps_x_is_yours(self):
        self.assertEqual(self.outcome("RUSSIA"), "kept")

    def test_the_same_support_breaks_it_when_said_to_someone_else(self):
        self.assertEqual(self.outcome("AUSTRIA"), "broken")

    def test_the_claim_itself_is_not_modified(self):
        claim = bul_is_yours()
        pa.check_claim(claim, message("prv-9", turn=5, sender="TURKEY", to="RUSSIA"), [self.BOARD])
        self.assertEqual(claim, bul_is_yours())


class AimedAtUs(unittest.TestCase):
    BOARD = phase(0, [], [("RUSSIA", "WAR"), ("GERMANY", "BER")], centers={"MOS": "RUSSIA", "BER": "GERMANY"})

    def aimed(self, *preds):
        return pa.aimed_at_us(list(preds), self.BOARD, "RUSSIA")

    def test_a_move_or_support_into_our_unit_or_centre_is_aimed_at_us(self):
        self.assertTrue(self.aimed({"p": "moves_to", "power": "GERMANY", "province": "WAR"}))
        self.assertTrue(self.aimed({"p": "moves_to", "power": "GERMANY", "province": "MOS"}))
        self.assertTrue(self.aimed({"p": "supports", "power": "GERMANY", "province": "WAR", "kind": "move"}))
        self.assertTrue(self.aimed({"p": "attacks", "power": "GERMANY", "target": "RUSSIA"}))
        self.assertTrue(self.aimed({"p": "order", "power": "GERMANY", "order": "A BER - WAR"}))
        self.assertTrue(self.aimed({"any": [{"p": "holds", "power": "GERMANY", "province": "BER"},
                                            {"p": "attacks", "power": "GERMANY", "provinces": ["WAR"]}]}))

    def test_a_promise_not_to_attack_or_a_move_elsewhere_is_not(self):
        self.assertFalse(self.aimed(not_moving_to("GERMANY", "WAR")))
        self.assertFalse(self.aimed({"p": "moves_to", "power": "GERMANY", "province": "SIL"}))
        self.assertFalse(self.aimed({"p": "supports", "power": "GERMANY", "province": "WAR", "kind": "hold"}))
        self.assertFalse(self.aimed({"p": "moves_to", "power": "RUSSIA", "province": "MOS"}))  # our own move
        self.assertFalse(self.aimed({"p": "unverifiable", "why": "vague"}))


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
        "messages": [
            message("prv-1", text="PRU stays empty. Locked. Confirmed. words"),
            message("prv-2", sender="RUSSIA", to="GERMANY", direction="out"),
        ],
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

    def test_one_broken_deal_restated_is_several_claims_but_one_betrayal_event(self):
        restated = [dict(self.CLAIMS["prv-1"][0], quote=q) for q in ("PRU stays empty", "Locked.", "Confirmed.")]
        claims = {"prv-1": restated, "prv-2": []}
        germany = pa.audit(self.LEDGER, claims)["summary"]["powers"]["GERMANY"]
        self.assertEqual((germany["categories"]["betrayed"], germany["betrayal_events"]), (3, 1))

    def test_a_statement_about_another_power_is_weighed_against_its_speaker(self):
        # Germany tells us "Russia moved on SIL": true, and it is Germany's word, not Russia's.
        claims = {
            "prv-1": [
                {"kind": "statement", "quote": "words", "turns": [0, 0],
                 "commitment": [{"p": "moves_to", "power": "RUSSIA", "province": "SIL"}]},
                {"kind": "request", "quote": "words", "turns": [0, 0], "commitment": [not_moving_to("RUSSIA", "SIL")]},
                {"kind": "proposal", "quote": "words", "turns": [0, 0],
                 "commitment": [not_moving_to("GERMANY", "PRU")]},
            ],
            "prv-2": [],
        }  # fmt: skip
        # said in the autumn, about the spring: a turn already played
        ledger = dict(self.LEDGER, messages=[message("prv-1", turn=1), self.LEDGER["messages"][1]])
        data = pa.audit(ledger, claims)
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
                    "quote": "words",
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
        self.assertIn('broke their word</span><span class="stood err">we relied on it</span>', page)
        # Our seat is tinted wherever the powers are listed; the others are not.
        self.assertIn('<tr class="us"><td>Russia (us)</td>', page)
        self.assertIn('<div class="us"><b>Russia (us)</b>', page)
        self.assertNotIn("Germany (us)", page)


def audited(us, phases, said, borders=None):
    """Audit a made-up ledger. `said` is [(message, [claims])]; returns message id -> its checked claims."""
    ledger = {"episode": "ep", "slot": 0, "policy": "mine:v1", "our_power": us, "score": 0.2, "outcome": "drawn",
              "belief_logged": True, "phases": phases, "messages": [m for m, _ in said]}  # fmt: skip
    if borders:
        ledger["borders"] = borders
    data = pa.audit(ledger, {m["id"]: claims for m, claims in said})
    return {m["id"]: m["claims"] for m in data["messages"]}


def promise(*commitment, **more):
    return {"kind": "promise", "quote": "words", "commitment": list(commitment), **more}


def verdict(claim):
    return claim["outcome"], claim["category"]


TRUSTED = {"stances": {"AUSTRIA": "ally", "ITALY": "ally", "ENGLAND": "ally", "FRANCE": "ally"}}
DOUBTED = {"stances": {"ITALY": "hostile", "TURKEY": "hostile", "FRANCE": "hostile"}}


class OrderedButFailed(unittest.TestCase):
    # ereq_1a367248, Spring 1906. Austria: "GRE is empty. I'll take it with F BUL/SC - GRE." It gave the
    # order; our own A CON - BUL dislodged that fleet. The first audit said "no order matched: betrayed".
    BOARD = phase(
        10,
        [dict(order("AUSTRIA", "F BUL - GRE", False), dislodged=True), order("TURKEY", "A CON - BUL")],
        [("AUSTRIA", "BUL"), ("TURKEY", "CON")],
        belief=TRUSTED,
    )
    TAKE = [{"p": "order", "power": "AUSTRIA", "order": "F BUL - GRE", "success": True}]

    def said(self, kind, commitment, turn=10):
        text = "I'll take it with F BUL/SC - GRE"
        claim = {"kind": kind, "quote": text, "turns": [10, 10], "commitment": commitment}
        to_us = message("prv-201", turn=turn, sender="AUSTRIA", to="TURKEY", text=text)
        return audited("TURKEY", [self.BOARD], [(to_us, [claim])])["prv-201"][0]

    def test_a_promised_move_that_was_ordered_and_failed_is_not_a_broken_promise(self):
        claim = self.said("promise", self.TAKE)
        self.assertEqual(verdict(claim), ("attempted", "trusted_rightly"))
        self.assertEqual(claim["evidence"], ["AUSTRIA F BUL - GRE (Spring 1906, dislodged)"])

    def test_a_promised_move_that_was_never_ordered_is_broken(self):
        elsewhere = [{"p": "order", "power": "AUSTRIA", "order": "F BUL - AEG", "success": True}]
        self.assertEqual(verdict(self.said("promise", elsewhere)), ("broken", "betrayed"))

    def test_a_statement_that_a_move_worked_is_still_false_when_it_failed(self):
        # "my fleet took GRE", said the turn after: about what happened, not about what was ordered
        self.assertEqual(self.said("statement", self.TAKE, turn=11)["outcome"], "false")

    def test_a_unit_ordered_to_stay_and_dislodged_kept_its_promise_to_hold_the_province(self):
        # ereq_981aeddf, Autumn 1905. France: "holding BRE/PAR". A PAR stayed (it supported RUH - BUR)
        # and was dislodged by Germany's supported A BUR - PAR. A lost defence, not a broken word.
        stayed = dict(order("FRANCE", "A PAR S A RUH - BUR", False), dislodged=True)
        board = phase(9, [stayed, order("GERMANY", "A BUR - PAR")], [("FRANCE", "PAR"), ("GERMANY", "BUR")],
                      centers={"PAR": "FRANCE"}, belief=TRUSTED)  # fmt: skip
        board["units_end"], board["centers_end"] = [{"power": "GERMANY", "unit": "A", "at": "PAR"}], {"PAR": "GERMANY"}
        keep = {"any": [{"p": "unit_at", "power": "FRANCE", "province": "PAR"},
                        {"p": "owns", "power": "FRANCE", "province": "PAR"}]}  # fmt: skip
        said = message("prv-209", turn=9, sender="FRANCE", to="ENGLAND")
        claim = audited("ENGLAND", [board], [(said, [promise(keep)])])["prv-209"][0]
        self.assertEqual(verdict(claim), ("attempted", "trusted_rightly"))
        left = dict(board, orders=[order("FRANCE", "A PAR - GAS"), order("GERMANY", "A BUR - PAR")])
        self.assertEqual(verdict(audited("ENGLAND", [left], [(said, [promise(keep)])])["prv-209"][0]),
                         ("broken", "betrayed"))  # fmt: skip

    def test_i_will_not_take_it_is_kept_by_a_failed_move_and_broken_by_one_that_works(self):
        self.assertEqual(self.said("promise", [{"not": self.TAKE[0]}])["outcome"], "kept")
        worked = dict(self.BOARD, orders=[order("AUSTRIA", "F BUL - GRE")])
        to_us = message("prv-201", turn=10, sender="AUSTRIA", to="TURKEY")
        claim = {"kind": "promise", "quote": "words", "commitment": [{"not": self.TAKE[0]}]}
        self.assertEqual(audited("TURKEY", [worked], [(to_us, [claim])])["prv-201"][0]["outcome"], "broken")


class NoSuchUnit(unittest.TestCase):
    # ereq_074c7f93, Autumn 1904. We told Austria "my SEV/BLA hold"; Russia had dislodged A SEV in the spring.
    def test_a_unit_that_no_longer_exists_cannot_keep_or_break_a_promise_about_it(self):
        board = phase(7, [order("TURKEY", "F BLA S A RUM")], [("TURKEY", "BLA"), ("TURKEY", "RUM"), ("RUSSIA", "SEV")])
        held, evidence = pa.evaluate({"p": "holds", "power": "TURKEY", "province": "SEV"}, [board])
        self.assertIsNone(held)
        self.assertEqual(evidence, ["not checkable: TURKEY has no unit in SEV (Autumn 1904)"])
        self.assertTrue(pa.evaluate({"p": "holds", "power": "TURKEY", "province": "BLA"}, [board])[0])
        # over two turns, only the turn the unit was there counts
        before = phase(6, [order("TURKEY", "A SEV - MOS")], [("TURKEY", "SEV")])
        self.assertFalse(pa.evaluate({"p": "holds", "power": "TURKEY", "province": "SEV"}, [before, board])[0])


class StatementScope(unittest.TestCase):
    # ereq_1a367248: Austria "F ION goes AEG" (a guess about Italy, wrong) was "deceived".
    # ereq_a407e516: Turkey denying its A ARM - SEV of the turn before was "deceived" too.
    # ereq_08badc16: we told Austria "I have ordered A RUM - BUL" and ordered A RUM - GAL: that one is real.
    BOARD = [
        phase(10, [order("TURKEY", "A ARM - SEV"), order("ITALY", "F ION - GRE")],
              [("TURKEY", "ARM"), ("ITALY", "ION"), ("AUSTRIA", "SER")], belief=TRUSTED),
        phase(11, [order("RUSSIA", "A RUM - GAL")], [("RUSSIA", "RUM"), ("AUSTRIA", "SER")], belief=TRUSTED),
    ]  # fmt: skip

    def one(self, us, said, claim):
        return audited(us, self.BOARD, [(said, [dict(claim, kind="statement", quote="words")])])[said["id"]][0]

    def test_a_guess_about_another_powers_coming_orders_is_a_forecast_not_a_lie(self):
        said = message("prv-201", turn=10, sender="AUSTRIA", to="TURKEY")
        guess = {"commitment": [{"p": "moves_to", "power": "ITALY", "province": "AEG", "unit": "ION"}]}
        claim = self.one("TURKEY", said, guess)
        self.assertEqual((claim["scope"], *verdict(claim)), ("forecast", "forecast_wrong", "none"))
        right = {"commitment": [{"p": "moves_to", "power": "ITALY", "province": "GRE"}]}
        self.assertEqual(verdict(self.one("TURKEY", said, right)), ("forecast_right", "none"))

    def test_a_wrong_account_of_orders_already_played_is_a_slip_not_a_deception(self):
        denial = {"turns": [10, 10], "commitment": [{"not": {"p": "moves_to", "power": "TURKEY", "province": "SEV"}}]}
        to_us = message("prv-256", turn=11, sender="TURKEY", to="AUSTRIA")
        claim = self.one("AUSTRIA", to_us, denial)
        self.assertEqual((claim["scope"], *verdict(claim)), ("record", "false", "misstated"))
        ours = message("prv-9", turn=11, sender="AUSTRIA", to="TURKEY", direction="out")
        wrong = {"turns": [10, 10], "commitment": [{"p": "moves_to", "power": "TURKEY", "province": "CON"}]}
        self.assertEqual(verdict(self.one("AUSTRIA", ours, wrong)), ("false", "we_misstated"))

    def test_a_false_statement_of_the_speakers_own_orders_this_turn_is_its_word(self):
        ours = message("prv-100", turn=11, sender="RUSSIA", to="AUSTRIA", direction="out")
        claim = self.one("RUSSIA", ours, {"commitment": [{"p": "order", "power": "RUSSIA", "order": "A RUM - BUL"}]})
        self.assertEqual((claim["scope"], *verdict(claim)), ("own_orders", "false", "we_broke_our_word"))
        theirs = message("prv-100", turn=11, sender="RUSSIA", to="AUSTRIA")
        claim = self.one("AUSTRIA", theirs, {"commitment": [{"p": "order", "power": "RUSSIA", "order": "A RUM - BUL"}]})
        self.assertEqual(verdict(claim), ("false", "false_no_stance"))  # our log took no stance on Russia


class KeptWhileDoubted(unittest.TestCase):
    """`doubted_wrongly` is a missed alliance. A kept promise we had not relied on is one only when
    the speaker could have broken it, did not move on us, and we moved on the speaker."""

    LAND = {"AEG": ["CON", "SMY", "GRE"], "GRE": ["AEG"], "MOS": ["STP", "SEV"], "STP": ["MOS"], "SEV": ["MOS"],
            "CON": ["AEG", "SMY"], "SMY": ["AEG", "CON"]}  # fmt: skip
    BORDERS = {"A": LAND, "F": {}}  # every unit in these boards is an army

    def test_a_narrow_promise_kept_beside_an_attack_on_us_is_not_a_missed_alliance(self):
        # ereq_074c7f93, Spring 1905. Italy: "I will keep F AEG out of CON/SMY". The fleet stayed;
        # it convoyed A GRE - SMY onto our home centre instead.
        board = phase(
            8,
            [order("ITALY", "A GRE - SMY"), order("ITALY", "F AEG C A GRE - SMY"), order("TURKEY", "A CON H")],
            [("ITALY", "GRE"), ("ITALY", "AEG"), ("TURKEY", "CON")],
            centers={"SMY": "TURKEY", "CON": "TURKEY"},
            belief=DOUBTED,
        )
        keep_out = [{"not": {"p": "moves_to", "power": "ITALY", "province": where, "unit": "AEG"}}
                    for where in ("CON", "SMY")]  # fmt: skip
        said = message("prv-205", turn=8, sender="ITALY", to="TURKEY")
        claim = audited("TURKEY", [board], [(said, [{"kind": "promise", "quote": "words", "commitment": keep_out}])],
                        self.BORDERS)["prv-205"][0]  # fmt: skip
        self.assertEqual(verdict(claim), ("kept", "kept_but_attacked_us"))
        self.assertEqual(claim["attacks_on_us"], ["ITALY A GRE - SMY (Spring 1905, succeeded)",
                                                  "ITALY F AEG C GRE - SMY (Spring 1905, succeeded)"])  # fmt: skip
        self.assertIn("note: but ITALY moved on us: ITALY A GRE - SMY (Spring 1905, succeeded)", claim["evidence"])

    def truce(self, turkey, us, borders=BORDERS):
        # ereq_08badc16, Spring 1908. Turkey: "A MOS holds, nothing toward STP." We were Russia in STP.
        board = phase(
            14,
            [order("TURKEY", turkey), order("RUSSIA", us)],
            [("TURKEY", turkey.split()[1]), ("RUSSIA", "STP")],
            centers={"STP": "RUSSIA", "MOS": "TURKEY", "SEV": "TURKEY"},
            belief=DOUBTED,
        )
        pledge = [{"not": {"p": "attacks", "power": "TURKEY", "provinces": ["STP"]}}]
        said = message("prv-347", turn=14, sender="TURKEY", to="RUSSIA")
        claims = [{"kind": "promise", "quote": "words", "commitment": pledge}]
        return audited("RUSSIA", [board], [(said, claims)], borders)["prv-347"][0]

    def test_we_attacked_a_power_that_was_keeping_its_word_to_us(self):
        claim = self.truce("A MOS H", "A STP - MOS")
        self.assertEqual(verdict(claim), ("kept", "doubted_wrongly"))
        self.assertEqual(claim["our_attacks_on_them"], ["RUSSIA A STP - MOS (Spring 1908, succeeded)"])

    def test_a_kept_promise_we_did_not_act_against_is_only_kept(self):
        self.assertEqual(verdict(self.truce("A MOS H", "A STP H")), ("kept", "kept_despite_doubt"))

    def test_a_promise_no_unit_could_have_broken_is_not_a_missed_alliance(self):
        # ereq_08badc16 prv-116: Turkey's nearest army was in SEV, two moves from STP
        claim = self.truce("A SEV H", "A STP - MOS")
        self.assertEqual((claim["could_break"], *verdict(claim)), (False, "kept", "kept_despite_doubt"))
        # an old ledger has no border table: assume it could have been broken
        self.assertEqual(self.truce("A SEV H", "A STP - MOS", borders=None)["category"], "doubted_wrongly")

    def test_a_kept_plan_against_someone_else_is_not_a_pledge_to_us(self):
        # ereq_08badc16 prv-347: "I'm pressing RUM and VIE", Turkey's own attack on Austria
        board = phase(14, [order("TURKEY", "A MOS - SEV"), order("RUSSIA", "A STP - MOS")],
                      [("TURKEY", "MOS"), ("RUSSIA", "STP")], centers={"STP": "RUSSIA", "MOS": "TURKEY"},
                      belief=DOUBTED)  # fmt: skip
        said = message("prv-347", turn=14, sender="TURKEY", to="RUSSIA")
        plan = promise({"p": "moves_to", "power": "TURKEY", "province": "SEV"})
        claim = audited("RUSSIA", [board], [(said, [plan])], self.BORDERS)["prv-347"][0]
        self.assertEqual(verdict(claim), ("kept", "kept_despite_doubt"))

    def test_when_we_had_given_our_own_word_and_broke_it_that_is_the_finding(self):
        # ereq_53b19a6d, Autumn 1908: Austria kept the stand-down; we had answered "Agreed" and attacked VEN
        board = phase(15, [order("AUSTRIA", "A VEN H"), order("FRANCE", "A TUS - VEN")],
                      [("AUSTRIA", "VEN"), ("FRANCE", "TUS")], centers={"VEN": "AUSTRIA", "ROM": "FRANCE"},
                      belief={"stances": {"AUSTRIA": "hostile"}})  # fmt: skip
        theirs = message("prv-282", turn=15, sender="AUSTRIA", to="FRANCE")
        ours = message("prv-285", turn=15, sender="FRANCE", to="AUSTRIA", direction="out")
        peace = promise({"not": {"p": "attacks", "power": "AUSTRIA", "provinces": ["ROM", "TUS"]}})
        agreed = promise(not_moving_to("FRANCE", "VEN"))
        borders = {"A": {"VEN": ["TUS", "ROM"], "TUS": ["VEN"]}, "F": {}}
        claims = audited("FRANCE", [board], [(theirs, [peace]), (ours, [agreed])], borders)
        self.assertEqual(claims["prv-285"][0]["category"], "we_broke_our_word")
        self.assertEqual(claims["prv-282"][0]["category"], "kept_despite_doubt")
        self.assertEqual(audited("FRANCE", [board], [(theirs, [peace])], borders)["prv-282"][0]["category"],
                         "doubted_wrongly")  # fmt: skip

    def test_a_true_statement_we_doubted_is_never_a_missed_alliance(self):
        board = phase(14, [order("TURKEY", "A MOS H"), order("RUSSIA", "A STP - MOS")],
                      [("TURKEY", "MOS"), ("RUSSIA", "STP")], centers={"STP": "RUSSIA"}, belief=DOUBTED)  # fmt: skip
        said = message("prv-9", turn=14, sender="TURKEY", to="RUSSIA")
        claim = dict(promise({"p": "holds", "power": "TURKEY", "province": "MOS"}), kind="statement")
        checked = audited("RUSSIA", [board], [(said, [claim])])["prv-9"][0]
        self.assertEqual(verdict(checked), ("true", "kept_despite_doubt"))


class SaidToSomeoneElse(unittest.TestCase):
    # ereq_1a367248, Autumn 1903. Italy to us (Turkey): "as agreed with Austria, I stay out of GRE."
    # Italy then ordered F ION - GRE. Nothing was promised to Turkey.
    BOARD = phase(5, [order("ITALY", "F ION - GRE")], [("ITALY", "ION"), ("AUSTRIA", "GRE")], belief=TRUSTED)
    PLEDGE = {"kind": "promise", "quote": "words", "commitment": [not_moving_to("ITALY", "GRE")]}

    def category(self, said, **more):
        return audited("TURKEY", [self.BOARD], [(said, [dict(self.PLEDGE, **more)])])[said["id"]][0]["category"]

    def test_a_promise_made_to_a_third_power_is_seen_broken_never_a_betrayal_of_us(self):
        private = message("prv-117", turn=5, sender="ITALY", to="TURKEY")
        self.assertEqual(self.category(private), "betrayed")  # no `to`: read as made to the recipient
        self.assertEqual(self.category(private, to="AUSTRIA"), "broken_to_other")
        public = message("pub-7", turn=5, sender="ITALY", to="ALL")
        self.assertEqual(self.category(public, to="AUSTRIA"), "broken_to_other")
        self.assertEqual(self.category(public), "betrayed")  # a public pledge to everyone includes us

    def test_to_must_be_a_power(self):
        with self.assertRaisesRegex(ValueError, "'to' must be a power"):
            self.category(message("prv-117", turn=5, sender="ITALY", to="TURKEY"), to="Austria-Hungary")


class AUnitThatDidNotStayPut(unittest.TestCase):
    # ereq_53b19a6d, Spring 1905. We (France) to Germany: "A BUR holds BUR, nothing enters your territory."
    # A BUR went to MAR, away from Germany; every stay-out pledge was kept. Flagged as our broken word.
    def category(self, bur):
        board = phase(8, [order("FRANCE", bur)], [("FRANCE", "BUR"), ("GERMANY", "MUN")], centers={"MUN": "GERMANY"})
        said = message("prv-195", turn=8, sender="FRANCE", to="GERMANY", direction="out")
        claim = promise({"p": "holds", "power": "FRANCE", "province": "BUR"}, not_moving_to("FRANCE", "RUH"))
        return verdict(audited("FRANCE", [board], [(said, [claim])])["prv-195"][0])

    def test_a_promised_hold_broken_by_a_move_away_is_a_changed_plan(self):
        self.assertEqual(self.category("A BUR - MAR"), ("broken", "we_changed_plans"))

    def test_broken_by_a_move_on_the_party_it_was_said_to_it_is_a_broken_word(self):
        self.assertEqual(self.category("A BUR - MUN"), ("broken", "we_broke_our_word"))
        self.assertEqual(self.category("A BUR - RUH"), ("broken", "we_broke_our_word"))  # a pledge, not a hold
        self.assertEqual(self.category("A BUR H"), ("kept", "we_kept_our_word"))


class AnAttackWeAnnounced(unittest.TestCase):
    # ereq_981aeddf: we told Germany "I'm taking BEL this fall" (Germany's centre) and did not attack it.
    def test_not_attacking_a_power_we_threatened_is_not_our_broken_word(self):
        said = message("prv-239", turn=11, sender="ENGLAND", to="GERMANY", direction="out")
        claim = promise({"p": "moves_to", "power": "ENGLAND", "province": "BEL"})
        for ours, expected in (("F NTH H", "our_attack_not_made"), ("F NTH - BEL", "our_attack_announced")):
            board = phase(11, [order("ENGLAND", ours)], [("ENGLAND", "NTH"), ("GERMANY", "BEL")],
                          centers={"BEL": "GERMANY"})  # fmt: skip
            self.assertEqual(audited("ENGLAND", [board], [(said, [claim])])["prv-239"][0]["category"], expected)


class TheOtherSideStruckFirst(unittest.TestCase):
    # ereq_5f2f2296. We (England) to Russia, Autumn 1902: "NWY is ours, SWE yours, no English moves
    # toward STP", an open-ended pledge (four turns). Russia hit NWY that autumn and the next;
    # our F NWY - STP came in Spring 1904. The first audit called it our broken word.
    PEACE = {"kind": "promise", "quote": "words", "turns": [3, 6],
             "commitment": [{"not": {"p": "attacks", "power": "ENGLAND", "provinces": ["STP"]}}]}  # fmt: skip

    def outcome(self, russia_1902):
        phases = [
            phase(3, [order("RUSSIA", russia_1902), order("ENGLAND", "F NWY H")],
                  [("RUSSIA", "FIN"), ("ENGLAND", "NWY")], centers={"NWY": "ENGLAND", "STP": "RUSSIA"}),
            phase(6, [order("ENGLAND", "F NWY - STP")], [("ENGLAND", "NWY"), ("RUSSIA", "FIN")],
                  centers={"NWY": "ENGLAND", "STP": "RUSSIA"}),
        ]  # fmt: skip
        said = message("prv-65", turn=3, sender="ENGLAND", to="RUSSIA", direction="out")
        return audited("ENGLAND", phases, [(said, [self.PEACE])])["prv-65"][0]

    def test_a_pledge_of_peace_does_not_outlive_the_other_sides_attack(self):
        claim = self.outcome("A FIN - NWY")
        self.assertEqual(verdict(claim), ("released_by_them", "none"))
        self.assertIn("note: RUSSIA struck first: RUSSIA A FIN - NWY (Autumn 1902, succeeded)", claim["evidence"])

    def test_without_that_attack_it_is_our_broken_word(self):
        self.assertEqual(verdict(self.outcome("A FIN H")), ("broken", "we_broke_our_word"))

    def test_one_half_of_a_deal_does_not_outlive_the_other_half(self):
        # ereq_a407e516. Germany to us (Russia): "I stay out of SWE/NWY; you stay out of PRU" (two years).
        # We entered PRU in Spring 1902; Germany moved on NWY that autumn. Flagged as a betrayal.
        def germany(russia_spring):
            phases = [
                phase(2, [order("RUSSIA", russia_spring), order("GERMANY", "A DEN H")],
                      [("RUSSIA", "WAR"), ("GERMANY", "DEN")], belief={"stances": {"GERMANY": "ally"}}),
                phase(3, [order("GERMANY", "A DEN - NWY")], [("GERMANY", "DEN")]),
            ]  # fmt: skip
            said = message("prv-45", turn=2, sender="GERMANY", to="RUSSIA")
            ask = dict(promise(not_moving_to("RUSSIA", "PRU"), turns=[2, 5]), kind="request")
            deal = [promise(not_moving_to("GERMANY", "NWY"), turns=[2, 5]), ask]
            return audited("RUSSIA", phases, [(said, deal)])["prv-45"][0]

        claim = germany("A WAR - PRU")
        self.assertEqual(verdict(claim), ("released_by_them", "none"))
        self.assertEqual(claim["evidence"][-1], "note: RUSSIA had already not done its part: “words”")
        self.assertEqual(verdict(germany("A WAR H")), ("broken", "betrayed"))


class ChangedInTheOpen(unittest.TestCase):
    # ereq_981aeddf, Spring 1904. France promised "A BUR S F NTH - BEL", then wrote three times before the
    # orders "my armies are committed to striking MUN" and ordered A BUR - MUN. Not a betrayal.
    BOARD = phase(6, [order("FRANCE", "A BUR - MUN"), order("ENGLAND", "F NTH - BEL", False)],
                  [("FRANCE", "BUR"), ("ENGLAND", "NTH")], belief=TRUSTED)  # fmt: skip
    SUPPORT = {"kind": "promise", "quote": "words",
               "commitment": [{"p": "supports", "power": "FRANCE", "province": "BEL", "kind": "move"}]}  # fmt: skip
    STRIKE = promise({"p": "moves_to", "power": "FRANCE", "province": "MUN"})

    def audit(self, later_claim, sender="FRANCE"):
        first = message("prv-99", turn=6, sender="FRANCE", to="ENGLAND")
        later = message("prv-145", turn=6, sender=sender, to="ENGLAND" if sender == "FRANCE" else "FRANCE")
        return audited("ENGLAND", [self.BOARD], [(first, [self.SUPPORT]), (later, [later_claim])])

    def test_a_claim_that_replaces_an_earlier_one_ends_it(self):
        claims = self.audit(dict(self.STRIKE, replaces=["prv-99#1"]))
        old = claims["prv-99"][0]
        self.assertEqual(verdict(old), ("superseded", "none"))
        self.assertEqual(old["replaced_by"], "prv-145")
        self.assertEqual(verdict(claims["prv-145"][0]), ("kept", "trusted_rightly"))
        self.assertEqual(self.audit(dict(self.STRIKE, replaces=["prv-99"]))["prv-99"][0]["outcome"], "superseded")

    def test_with_no_replaces_the_dropped_support_is_a_betrayal(self):
        self.assertEqual(verdict(self.audit(self.STRIKE)["prv-99"][0]), ("broken", "betrayed"))

    def test_a_change_told_only_to_another_power_is_no_notice(self):
        # ereq_08badc16: we promised Germany A STP - MOS stays off, then told only England the new order
        first = message("prv-99", turn=6, sender="FRANCE", to="ENGLAND")
        later = message("prv-145", turn=6, sender="FRANCE", to="GERMANY")
        claims = audited("ENGLAND", [self.BOARD], [(first, [self.SUPPORT]),
                                                   (later, [dict(self.STRIKE, replaces=["prv-99#1"])])])  # fmt: skip
        self.assertEqual(verdict(claims["prv-99"][0]), ("broken", "betrayed"))

    def test_replaces_must_name_an_earlier_claim_of_the_same_sender(self):
        for bad, why in ((["prv-7"], "not a message id"), (["prv-99#3"], "prv-99 has no claim 3"),
                         (["prv-145"], "earlier message from the same sender")):  # fmt: skip
            with self.assertRaisesRegex(ValueError, why):
                self.audit(dict(self.STRIKE, replaces=bad))

    def test_the_party_a_promise_was_made_to_can_let_it_go(self):
        # ereq_074c7f93: Austria promised a joint attack on GRE; we declined it ourselves before the orders
        no_need = dict(promise({"p": "unverifiable", "why": "withdrawal"}), replaces=["prv-99#1"])
        self.assertEqual(verdict(self.audit(no_need, sender="ENGLAND")["prv-99"][0]), ("superseded", "none"))
        # a third power cannot: Germany's message names a promise France made to England
        first = message("prv-99", turn=6, sender="FRANCE", to="ENGLAND")
        other = message("prv-145", turn=6, sender="GERMANY", to="ENGLAND")
        with self.assertRaisesRegex(ValueError, "earlier message from the same sender"):
            audited("ENGLAND", [self.BOARD], [(first, [self.SUPPORT]), (other, [no_need])])

    def test_a_replaced_open_ended_promise_still_answers_for_the_turns_before(self):
        # "No moves on MUN" for two years, called off in the open in the second spring: the first
        # year, when it was kept, still counts; the attack after the notice does not break it.
        quiet = phase(4, [order("FRANCE", "A BUR H")], [("FRANCE", "BUR")], belief=TRUSTED)
        peace = promise(not_moving_to("FRANCE", "MUN"), turns=[4, 7])
        first = message("prv-50", turn=4, sender="FRANCE", to="ENGLAND")
        later = message("prv-145", turn=6, sender="FRANCE", to="ENGLAND")
        called_off = dict(self.STRIKE, replaces=["prv-50"])
        claims = audited("ENGLAND", [quiet, self.BOARD], [(first, [peace]), (later, [called_off])])
        self.assertEqual((claims["prv-50"][0]["outcome"], claims["prv-50"][0]["window"]), ("kept", [4, 5]))
        unannounced = audited("ENGLAND", [quiet, self.BOARD], [(first, [peace]), (later, [])])
        self.assertEqual(verdict(unannounced["prv-50"][0]), ("broken", "betrayed"))


class SaidBeforehand(unittest.TestCase):
    # ereq_08badc16, Spring 1907. England had pledged "no moves into NWY/DEN/SWE/NTH". We then asked
    # England four times to move F YOR - NTH, and it did. The first audit flagged a betrayal.
    BOARD = phase(12, [order("ENGLAND", "F YOR - NTH")], [("ENGLAND", "YOR"), ("RUSSIA", "NWY")], belief=TRUSTED)
    PLEDGE = {"kind": "promise", "quote": "words", "commitment": [not_moving_to("ENGLAND", "NTH")]}
    MOVE = [{"p": "moves_to", "power": "ENGLAND", "province": "NTH"}]

    def pledge(self, *later):
        first = message("prv-241", turn=12, sender="ENGLAND", to="RUSSIA")
        return audited("RUSSIA", [self.BOARD], [(first, [self.PLEDGE]), *later])["prv-241"][0]

    def test_a_move_the_other_party_asked_for_does_not_break_the_earlier_pledge(self):
        asked = message("prv-275", turn=12, sender="RUSSIA", to="ENGLAND", direction="out")
        claim = self.pledge((asked, [{"kind": "request", "quote": "words", "commitment": self.MOVE}]))
        self.assertEqual(verdict(claim), ("superseded", "none"))
        self.assertIn("note: said or asked for beforehand in prv-275", claim["evidence"])

    def test_nor_does_a_move_the_speaker_announced_to_the_same_party_before_the_orders(self):
        # ereq_a407e516: we told Turkey "F BLA - SEV" three times before ordering it
        told = message("prv-294", turn=12, sender="ENGLAND", to="RUSSIA")
        claim = self.pledge((told, [{"kind": "promise", "quote": "words", "commitment": self.MOVE}]))
        self.assertEqual(claim["outcome"], "superseded")

    def test_an_unannounced_move_or_one_told_to_someone_else_or_afterwards_still_breaks_it(self):
        self.assertEqual(verdict(self.pledge()), ("broken", "betrayed"))
        elsewhere = message("prv-294", turn=12, sender="ENGLAND", to="FRANCE")
        announced = [{"kind": "promise", "quote": "words", "commitment": self.MOVE}]
        self.assertEqual(self.pledge((elsewhere, announced))["outcome"], "broken")
        # told the turn after the move: a report, not a notice
        late = message("prv-300", turn=13, sender="ENGLAND", to="RUSSIA")
        report = [{"kind": "statement", "quote": "words", "turns": [12, 12], "commitment": self.MOVE}]
        self.assertEqual(self.pledge((late, report))["outcome"], "broken")

    def test_keeping_a_province_then_announcing_the_unit_will_leave_it(self):
        # ereq_981aeddf, 1906. France: "I'm holding BUR, BRE, SPA", then "BUR presses MAR" before the orders
        board = phase(11, [order("FRANCE", "A BUR - MAR")], [("FRANCE", "BUR")], belief=TRUSTED)
        board["units_end"] = [{"power": "FRANCE", "unit": "A", "at": "MAR"}]
        keep = promise({"any": [{"p": "unit_at", "power": "FRANCE", "province": "BUR"},
                                {"p": "owns", "power": "FRANCE", "province": "BUR"}]})  # fmt: skip
        first = message("prv-248", turn=11, sender="FRANCE", to="ENGLAND")
        later = message("prv-272", turn=11, sender="FRANCE", to="ENGLAND")
        press = promise({"p": "moves_to", "power": "FRANCE", "province": "MAR", "unit": "BUR"})
        claims = audited("ENGLAND", [board], [(first, [keep]), (later, [press])])
        self.assertEqual(verdict(claims["prv-248"][0]), ("superseded", "none"))
        self.assertEqual(verdict(audited("ENGLAND", [board], [(first, [keep])])["prv-248"][0]), ("broken", "betrayed"))

    def test_a_named_unit_that_did_something_else_as_announced(self):
        # ereq_5f2f2296: "F NTH - HOL", then "Change: my F NTH supports my F NWY this fall", then that order
        board = phase(9, [order("ENGLAND", "F NTH S F NWY")], [("ENGLAND", "NTH"), ("ENGLAND", "NWY")])
        first = message("prv-168", turn=9, sender="ENGLAND", to="GERMANY", direction="out")
        change = message("prv-175", turn=9, sender="ENGLAND", to="GERMANY", direction="out")
        plan = promise({"p": "order", "power": "ENGLAND", "order": "F NTH - HOL"})
        new = {"kind": "promise", "quote": "words",
               "commitment": [{"p": "supports", "power": "ENGLAND", "unit": "NTH", "kind": "hold"}]}  # fmt: skip
        claims = audited("ENGLAND", [board], [(first, [plan]), (change, [new])])
        self.assertEqual(verdict(claims["prv-168"][0]), ("superseded", "none"))
        self.assertEqual(verdict(audited("ENGLAND", [board], [(first, [plan])])["prv-168"][0]),
                         ("broken", "we_broke_our_word"))  # fmt: skip


class Quotes(unittest.TestCase):
    TEXT = "Agreed &mdash; I&rsquo;ll hold VIE,<br />and stay out of TRI. Good luck."

    def test_a_quote_must_be_the_messages_own_words(self):
        for quote in ("I'll hold VIE, and stay out of TRI", "Agreed - I’ll hold VIE", "agreed ... stay out of TRI",
                      "Agreed [to prv-209: hold VIE]"):  # fmt: skip
            self.assertIsNone(pa.quote_missing(quote, self.TEXT), quote)
        self.assertEqual(pa.quote_missing("I will hold VIE", self.TEXT), "i will hold vie")
        self.assertEqual(pa.quote_missing("Agreed ... leave TRI alone", self.TEXT), "leave tri alone")
        self.assertIsNotNone(pa.quote_missing("", self.TEXT))

    def test_a_line_break_in_the_press_is_a_new_line_and_quotes_still_match(self):
        raw = {"id": 7, "turn": 0, "phase": "Diplomacy", "fromCountryID": 4, "toCountryID": 5, "message": self.TEXT}
        text = pa.ledger_messages([raw], [], "AUSTRIA")[0]["text"]
        self.assertEqual(text, "Agreed \u2014 I\u2019ll hold VIE,\nand stay out of TRI. Good luck.")
        self.assertIsNone(pa.quote_missing("I'll hold VIE, and stay out of TRI", text))
        self.assertIsNotNone(pa.quote_missing("[terms of prv-187]", self.TEXT))  # a note is not a quote


class EdgesOfTheRules(unittest.TestCase):
    """Made-up boards for rule edges a second reviewer found (no real game showed them yet)."""

    def test_support_promised_to_the_other_party_and_withheld_is_not_a_changed_plan(self):
        # France to us (England): "A PIC supports your army in BEL." A PIC held instead.
        board = phase(4, [order("FRANCE", "A PIC H"), order("ENGLAND", "A BEL H")],
                      [("FRANCE", "PIC"), ("ENGLAND", "BEL")], centers={"BEL": "ENGLAND"}, belief=TRUSTED)  # fmt: skip
        said = message("prv-1", turn=4, sender="FRANCE", to="ENGLAND")
        claim = promise({"p": "order", "power": "FRANCE", "order": "A PIC S A BEL"})
        self.assertEqual(verdict(audited("ENGLAND", [board], [(said, [claim])])["prv-1"][0]), ("broken", "betrayed"))
        # Its own arrangement ("PIC supports my army in BUR"), dropped without a move on us, stays a changed plan.
        board = phase(4, [order("FRANCE", "A PIC H"), order("FRANCE", "A BUR H")],
                      [("FRANCE", "PIC"), ("FRANCE", "BUR"), ("ENGLAND", "BEL")], belief=TRUSTED)  # fmt: skip
        claim = promise({"p": "order", "power": "FRANCE", "order": "A PIC S A BUR"})
        self.assertEqual(verdict(audited("ENGLAND", [board], [(said, [claim])])["prv-1"][0]),
                         ("broken", "changed_plans"))  # fmt: skip

    def test_a_request_whose_condition_never_came_about_releases_nothing(self):
        # Germany to us (Russia): "I support you into GAL this autumn. If France enters BUR this spring, hold WAR."
        # France stayed out, so the request never applied; our move from WAR is not our half of the deal undone.
        spring = phase(0, [order("RUSSIA", "A WAR - GAL"), order("GERMANY", "A SIL H"), order("FRANCE", "A PAR H")],
                       [("RUSSIA", "WAR"), ("GERMANY", "SIL"), ("FRANCE", "PAR")],
                       belief=TRUSTED | {"trust": {"GERMANY": 0.9}})  # fmt: skip
        autumn = phase(1, [order("RUSSIA", "A GAL H"), order("GERMANY", "A SIL H")],
                       [("RUSSIA", "GAL"), ("GERMANY", "SIL")])  # fmt: skip
        said = message("prv-1", turn=0, sender="GERMANY", to="RUSSIA")
        claims = [
            promise({"p": "supports", "power": "GERMANY", "of": "RUSSIA"}, turns=[0, 1]),
            {"kind": "request", "quote": "words", "turns": [0, 0],
             "condition": [{"p": "moves_to", "power": "FRANCE", "province": "BUR"}],
             "commitment": [{"p": "holds", "power": "RUSSIA", "province": "WAR"}]},
        ]
        got = audited("RUSSIA", [spring, autumn], [(said, claims)])["prv-1"]
        self.assertEqual(got[1]["outcome"], "not_applicable")
        self.assertEqual(got[0]["outcome"], "broken")  # was released_by_them

    def test_the_power_a_public_promise_was_made_to_can_let_it_go(self):
        board = phase(1, [order("GERMANY", "A SIL H")], [("GERMANY", "SIL"), ("RUSSIA", "WAR")])
        first = message("pub-1", turn=0, sender="GERMANY", to="ALL")
        later = message("prv-2", turn=1, sender="RUSSIA", to="GERMANY", direction="out")
        said = [(first, [promise({"p": "supports", "power": "GERMANY", "of": "RUSSIA"}, to="RUSSIA", turns=[1, 1])]),
                (later, [{"kind": "request", "quote": "words", "replaces": ["pub-1"],
                          "commitment": [{"p": "holds", "power": "GERMANY", "province": "SIL"}]}])]  # fmt: skip
        self.assertEqual(audited("RUSSIA", [board], said)["pub-1"][0]["outcome"], "superseded")

    def test_helping_the_named_power_in_is_not_an_attack_in_public_press_either(self):
        # Turkey, in public, to us (Russia): "Bulgaria is yours." Then it supports our army into BUL.
        board = phase(2, [order("TURKEY", "A CON S A RUM - BUL"), order("RUSSIA", "A RUM - BUL")],
                      [("TURKEY", "CON"), ("RUSSIA", "RUM")], belief=TRUSTED | {"trust": {"TURKEY": 0.9}})  # fmt: skip
        said = message("pub-1", turn=2, sender="TURKEY", to="ALL")
        claim = promise({"not": {"p": "attacks", "power": "TURKEY", "provinces": ["BUL"]}}, to="RUSSIA")
        self.assertEqual(audited("RUSSIA", [board], [(said, [claim])])["pub-1"][0]["outcome"], "kept")

    def test_our_public_word_broken_to_a_power_is_not_also_a_doubt_that_turned_out_wrong(self):
        # We (Russia), in public, to Germany: "I will not move on you." Germany, privately: the same. We attacked.
        board = phase(2, [order("RUSSIA", "A WAR - SIL"), order("GERMANY", "A SIL H")],
                      [("RUSSIA", "WAR"), ("GERMANY", "SIL")], centers={"WAR": "RUSSIA"},
                      belief={"stances": {"GERMANY": "hostile"}})  # fmt: skip
        ours = message("pub-1", turn=2, sender="RUSSIA", to="ALL", direction="out")
        theirs = message("prv-2", turn=2, sender="GERMANY", to="RUSSIA")
        said = [(ours, [promise({"not": {"p": "attacks", "power": "RUSSIA", "target": "GERMANY"}}, to="GERMANY")]),
                (theirs, [promise({"not": {"p": "attacks", "power": "GERMANY", "target": "RUSSIA"}})])]
        got = audited("RUSSIA", [board], said, {"A": {"SIL": ["WAR"], "WAR": ["SIL"]}, "F": {}})
        self.assertEqual(got["pub-1"][0]["category"], "we_broke_our_word")
        self.assertEqual(got["prv-2"][0]["category"], "kept_despite_doubt")

    def test_a_pledge_that_protects_a_third_power_is_not_a_missed_alliance_with_us(self):
        # France to us (Russia): "I will not attack Italy." Kept. We moved on France.
        board = phase(2, [order("FRANCE", "A MAR H"), order("RUSSIA", "A BUR - MAR"), order("ITALY", "A PIE H")],
                      [("FRANCE", "MAR"), ("RUSSIA", "BUR"), ("ITALY", "PIE")], centers={"MAR": "FRANCE"},
                      belief=DOUBTED)  # fmt: skip
        said = message("prv-1", turn=2, sender="FRANCE", to="RUSSIA")
        claim = promise({"not": {"p": "attacks", "power": "FRANCE", "target": "ITALY"}})
        got = audited("RUSSIA", [board], [(said, [claim])], {"A": {"MAR": ["PIE", "BUR"]}, "F": {}})["prv-1"][0]
        self.assertEqual(verdict(got), ("kept", "kept_despite_doubt"))

    def test_a_misspelt_predicate_is_refused_even_for_a_turn_the_game_never_reached(self):
        said = message("prv-1", turn=0, sender="GERMANY", to="RUSSIA")
        for bad in ({"p": "typo"}, {"p": "order", "power": "GERMANY", "order": "A BER X PRU"},
                    {"not": {"p": "movesto", "power": "GERMANY"}},
                    {"any": [{"p": "holds", "power": "GERMANY"}]}):  # fmt: skip
            with self.assertRaises(ValueError, msg=bad):
                audited("RUSSIA", [SPRING], [(said, [promise(bad, turns=[30, 31])])])
            with self.assertRaises(ValueError, msg=bad):  # nor behind a condition that was not met
                audited("RUSSIA", [SPRING], [(said, [promise(
                    bad, condition=[{"p": "moves_to", "power": "RUSSIA", "province": "MOS"}])])])  # fmt: skip

    def test_the_parts_of_a_quote_must_come_in_the_messages_order(self):
        self.assertIsNone(pa.quote_missing("never ... France", "I will never attack France"))
        self.assertEqual(pa.quote_missing("attack France ... never", "I will never attack France"), "never")


class PlansAndBoards(unittest.TestCase):
    def test_things_promised_together_must_be_ordered_in_the_same_turn(self):
        # "BUD moves to SER with RUM's support this year": the move in spring and the support in
        # autumn are two failed attacks, not the plan.
        spring = phase(2, [order("AUSTRIA", "A BUD - SER", False), order("AUSTRIA", "A RUM H")],
                       [("AUSTRIA", "BUD"), ("AUSTRIA", "RUM")])  # fmt: skip
        autumn = phase(3, [order("AUSTRIA", "A BUD H"), order("AUSTRIA", "A RUM S A BUD - SER", False)],
                       [("AUSTRIA", "BUD"), ("AUSTRIA", "RUM")])  # fmt: skip
        plan = [{"p": "moves_to", "power": "AUSTRIA", "province": "SER"},
                {"p": "supports", "power": "AUSTRIA", "province": "SER", "kind": "move"}]  # fmt: skip
        held, evidence = pa.evaluate_all(plan, [spring, autumn])
        self.assertFalse(held)
        self.assertEqual(evidence[-1], "but never all in the same turn (Spring 1902 to Autumn 1902)")
        together = dict(autumn, orders=[order("AUSTRIA", "A BUD - SER"), order("AUSTRIA", "A RUM S A BUD - SER")])
        self.assertTrue(pa.evaluate_all(plan, [spring, together])[0])
        # a "not" beside them still covers every turn of the window
        quiet = plan + [{"not": {"p": "holds", "power": "AUSTRIA", "province": "RUM"}}]
        self.assertFalse(pa.evaluate_all(quiet, [spring, together])[0])

    def test_the_board_after_the_last_turn_is_not_in_the_record(self):
        last = dict(SPRING, end_known=False)
        fact = {"p": "owns", "power": "GERMANY", "province": "BER"}
        self.assertIsNone(pa.evaluate(fact, [last])[0])
        self.assertTrue(pa.evaluate(dict(fact, when="start"), [last])[0])
        self.assertTrue(pa.evaluate(fact, [SPRING])[0])  # an older ledger without the mark: as before


class Ledger(unittest.TestCase):
    def test_extract_reads_orders_press_and_beliefs_for_our_seat(self):
        territories = [
            {"id": 1, "name": "Berlin", "supply": True, "coast": "No",
             "borders": [{"id": 2, "army": True, "fleet": True}]},
            {"id": 2, "name": "Prussia", "supply": False, "coast": "No",
             "borders": [{"id": 1, "army": True, "fleet": True}]},
            {"id": 3, "name": "St. Petersburg (South Coast)", "supply": False, "coast": "Child",
             "borders": [{"id": 4, "army": False, "fleet": True}]},
            {"id": 4, "name": "Gulf of Bothnia", "supply": False, "coast": "No",
             "borders": [{"id": 3, "army": False, "fleet": True}]},
        ]  # fmt: skip
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
        # where an army or a fleet can go next, coasts folded in: `verify` uses it to tell a promise
        # that could not be broken
        land = {"BER": ["PRU"], "PRU": ["BER"]}
        self.assertEqual(ledger["borders"], {"A": land, "F": {**land, "BOT": ["STP"], "STP": ["BOT"]}})
        self.assertFalse(spring["end_known"])  # the last turn: the record holds no board after it

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
            # the annotator's file: the press and the starting board, and nothing about how the turn came out
            view = json.loads((out / "annotate.json").read_text())
            self.assertEqual(view["turns"][0]["units_at_start"], ["GERMANY A BER"])
            self.assertEqual(view["turns"][0]["messages"][0]["text"], "PRU stays empty")
            self.assertNotIn("orders", json.dumps(view))
            self.assertNotIn("success", json.dumps(view))
            # `check` is the annotator's format test: it prints no verdict and names a bad entry
            shown = io.StringIO()
            with contextlib.redirect_stdout(shown):
                pa.main(["check", str(out)])
            self.assertEqual(shown.getvalue().strip(), "ok: 1 messages, 1 with claims, 1 claims")
            (out / "claims.json").write_text(json.dumps({"prv-1": [dict(claim, quote="PRU will stay empty")]}))
            with self.assertRaisesRegex(SystemExit, "prv-1 claim 1: the quote is not in the message"):
                pa.main(["check", str(out)])

    def test_a_hold_has_no_result_and_verify_says_why_its_columns_differ_from_check(self):
        territories = [{"id": 1, "name": "Berlin", "supply": True, "coast": "No"},
                       {"id": 2, "name": "Prussia", "supply": False, "coast": "No"}]
        hold = {"countryID": 4, "terrID": 1, "unitType": "Army", "type": "Hold", "toTerrID": None, "fromTerrID": None,
                "success": False, "dislodged": False}  # upstream marks every hold `success: false`
        history = [{"turn": turn, "phase": "Diplomacy", "units": [{"countryID": 4, "type": "Army", "terrID": 1}],
                    "centers": [{"terrID": 1, "countryID": 4}], "orders": [hold]} for turn in (0, 1, 2)]
        frame = {"variant": {"territories": territories}, "history": {"phases": history}, "messages": {"messages": []}}
        said = [{"id": turn + 1, "turn": turn, "phase": "Diplomacy", "timeSent": turn, "fromCountryID": 4,
                 "toCountryID": 7, "message": "BER holds; keep out of PRU"} for turn in (0, 2)]
        logs = {6: [{"event": "private_press", "archive": {"messages": said}}]}
        with tempfile.TemporaryDirectory() as tmp:
            ep = write_episode(Path(tmp) / "ep", [1 / 7] * 7, list(range(1, 8)), [3] * 7, logs=logs)
            (ep / "replay").write_text(json.dumps([frame]))
            out = Path(tmp) / "out"
            printed = io.StringIO()
            with contextlib.redirect_stdout(printed):
                pa.main(["extract", str(ep), "--slot", "6", "--out", str(out), "--by-year"])
            # one file per game year, for a reader that cannot take annotate.json in one read
            parts = [Path(path) for path in json.loads(printed.getvalue())["annotate_by_year"]]
            self.assertEqual([path.name for path in parts], ["annotate-1901.json", "annotate-1902.json"])
            whole = json.loads((out / "annotate.json").read_text())
            views = [json.loads(path.read_text()) for path in parts]
            self.assertEqual([turn for view in views for turn in view["turns"]], whole["turns"])
            self.assertEqual([[turn["turn"] for turn in view["turns"]] for view in views], [[0, 1], [2]])
            self.assertIn("This file holds 1902 only", views[1]["read_me"])
            self.assertEqual(views[0]["our_power"], "RUSSIA")
            claims = [{"kind": "promise", "quote": "BER holds",
                       "commitment": [{"p": "holds", "power": "GERMANY", "province": "BER"}]},
                      {"kind": "request", "quote": "keep out of PRU", "commitment": [not_moving_to("RUSSIA", "PRU")]}]
            (out / "claims.json").write_text(json.dumps({"prv-1": claims, "prv-3": claims}))
            checked, printed = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(checked):
                pa.main(["check", str(out)])
            with contextlib.redirect_stdout(printed):
                pa.main(["verify", str(out)])
            shown = json.loads(printed.getvalue())
            self.assertIn("4 claims", checked.getvalue())
            self.assertEqual(shown["claims"], 4)  # the number `check` prints
            germany = shown["powers"]["GERMANY"]
            self.assertEqual((germany["claims_without_requests"], germany["requests_made"], germany["held"]), (2, 2, 2))
            self.assertNotIn("claims", germany)
            self.assertIn("a request is weighed against the power asked", shown["note"])
            audit = json.loads((out / "audit.json").read_text())
            self.assertEqual(audit["summary"]["powers"]["GERMANY"]["claims"], 2)  # the file's key is unchanged
            self.assertEqual([o["success"] for phase in audit["phases"] for o in phase["orders"]], [None] * 3)
            with contextlib.redirect_stdout(io.StringIO()):
                pa.main(["report", str(out)])
            self.assertNotIn("(failed)", (out / "audit.html").read_text())

    def test_a_move_keeps_its_result(self):
        move = {"countryID": 4, "terrID": 1, "unitType": "Army", "type": "Move", "toTerrID": 2, "fromTerrID": None,
                "success": False, "dislodged": False}
        territories = [{"id": 1, "name": "Berlin", "supply": True, "coast": "No"},
                       {"id": 2, "name": "Prussia", "supply": False, "coast": "No"}]
        phase = {"turn": 0, "phase": "Diplomacy", "units": [], "centers": [], "orders": [move]}
        frame = {"variant": {"territories": territories}, "history": {"phases": [phase]}}
        self.assertIs(pa.movement_phases([frame])[0]["orders"][0]["success"], False)

    def test_the_province_table_matches_the_reference_policy(self):
        dipmap = Path(pa.__file__).resolve().parents[1] / "players" / "castlereagh" / "castlereagh" / "dipmap.py"
        if not dipmap.exists():
            self.skipTest("the reference policy is not in this lab")
        scope: dict = {}
        exec(dipmap.read_text().split("class DipMap")[0], scope)  # the tables only, no imports needed
        self.assertEqual(pa.ABBREVIATION, scope["ABBREVIATION"])
        self.assertEqual(pa.POWER, scope["POWER"])


class WordsForAVerdict(unittest.TestCase):
    """What a reader sees in place of the audit's outcome and category codes (press_report.py)."""

    OUTCOMES = ({word for pair in pa.OUTCOMES.values() for word in pair} | set(pa.UNMET.values())
                | {"not_applicable", "not_reached", "attempted", "superseded", "released_by_them", "unverifiable",
                   "forecast_right", "forecast_wrong"})  # fmt: skip
    # Every category `press_audit.category` can return, read from its source so that a new one fails here.
    CATEGORIES = set(re.findall(r'"([a-z_]+)"', inspect.getsource(pa.category).split('"""')[2])) - {
        "none", "statement", "record", "promise"}  # fmt: skip

    @staticmethod
    def said(kind, outcome, category="none", speaker="GERMANY", to="TURKEY", **more):
        claim = {"kind": kind, "outcome": outcome, "category": category, "to": to, **more}
        return press_report.verdict(claim, {"from": speaker, "to": to}, "TURKEY")

    def test_every_code_the_audit_writes_has_plain_words(self):
        self.assertGreaterEqual(len(self.CATEGORIES), 21)
        self.assertLessEqual(set(pa.FLAGGED), self.CATEGORIES)
        for code in sorted(self.OUTCOMES | self.CATEGORIES):
            self.assertIn(code, press_report.WORDS)
            words = press_report.WORDS[code]
            self.assertNotIn("_", words)
            self.assertNotIn("stance", words, "tool vocabulary: say whether we relied on it")
        self.assertLessEqual(set(press_report.TONE) | set(press_report.LEGEND), set(press_report.WORDS))
        # Every category has its one line: none of them is plain from the label alone.
        self.assertLessEqual(self.CATEGORIES, set(press_report.LEGEND))

    def test_only_what_cost_us_or_was_our_own_doing_is_loud(self):
        loud = {code for code, tone in press_report.TONE.items() if tone == "err"}
        self.assertEqual(loud, {"betrayed", "deceived", "we_broke_our_word"})
        self.assertLessEqual(loud, set(pa.FLAGGED))
        for kind, (held, not_held) in pa.OUTCOMES.items():
            for outcome in (held, not_held):
                self.assertEqual(self.said(kind, outcome)["tone"], "quiet", "an outcome alone is nobody's alarm")
        self.assertEqual(self.said("promise", "broken", "doubted_rightly")["tone"], "quiet")
        self.assertEqual(self.said("promise", "kept", "trusted_rightly")["tone"], "ok")

    def test_a_claim_reads_as_what_happened_and_how_we_stood(self):
        def read(*args, **more):
            said = self.said(*args, **more)
            return said["label"], said["note"]

        self.assertEqual(read("promise", "broken", "betrayed"), ("broke their word", "we relied on it"))
        self.assertEqual(read("promise", "kept", "true_no_stance"), ("kept their word", ""))
        self.assertIn("logged no trust", self.said("promise", "kept", "true_no_stance")["tip"])
        self.assertEqual(read("promise", "attempted", "trusted_rightly"),
                         ("tried, but the move failed", "we relied on it"))  # fmt: skip
        self.assertEqual(read("promise", "superseded"), ("plan changed openly", ""))
        self.assertEqual(read("statement", "false", "deceived"), ("not true", "we relied on it"))
        self.assertEqual(read("statement", "false", "misstated"), ("wrong about past orders", "a slip, not a lie"))
        self.assertEqual(read("promise", "kept", "kept_to_other", to="RUSSIA"),
                         ("kept their word", "promise was to Russia, not us"))  # fmt: skip
        self.assertEqual(read("promise", "broken", "changed_plans"),
                         ("a unit moved that was to stay put", "no attack on us"))  # fmt: skip
        self.assertEqual(read("promise", "kept", "attack_announced"), ("said they would attack us, and did", ""))
        # Our own words are said of us.
        ours = {"speaker": "TURKEY", "to": "GERMANY"}
        self.assertEqual(read("promise", "broken", "we_broke_our_word", **ours), ("we broke our word", ""))
        self.assertEqual(read("promise", "attempted", "we_kept_our_word", **ours),
                         ("we tried, but the move failed", ""))  # fmt: skip
        self.assertEqual(read("statement", "true", "we_kept_our_word", scope="record", **ours), ("true", ""))
        self.assertEqual(read("statement", "false", "we_broke_our_word", scope="own_orders", **ours),
                         ("we broke our word", ""))  # fmt: skip
        self.assertEqual(read("promise", "broken", "we_changed_plans", **ours),
                         ("our unit moved that was to stay put", "no attack on Germany"))  # fmt: skip
        # A request is counted for the power that was asked, so the label names it.
        self.assertEqual(read("request", "refused", **ours)[0], "Germany did not do as asked")
        self.assertEqual(read("request", "complied")[0], "we did as asked")
        self.assertEqual(read("request", "complied", to="ALL", asked="RUSSIA")[0], "Russia did as asked")

    def test_the_page_shows_the_words_and_never_a_code(self):
        claim = {"kind": "promise", "quote": "PRU stays empty", "outcome": "broken", "category": "betrayed",
                 "to": "TURKEY", "condition": "met", "evidence": []}  # fmt: skip
        message = {"id": "prv-1", "from": "GERMANY", "to": "TURKEY", "turn": 0, "direction": "in",
                   "sent_in": "Spring 1901 Diplomacy", "text": "PRU stays empty<br />Germany",
                   "claims": [claim]}  # fmt: skip
        row = {"messages": 1, "claims": 1, "held": 0, "did_not_hold": 1, "held_share": 0.0, "unverifiable": 0,
               "asked": 0, "complied": 0, "categories": {"betrayed": 1, "false_no_stance": 2}}  # fmt: skip
        page = press_report.render_report({
            "episode": "e", "score": 0.1, "our_power": "TURKEY", "policy": "ours:v1", "belief_logged": True,
            "messages": [message], "phases": [],
            "summary": {"messages": 1, "messages_with_claims": 1, "our_power": "TURKEY", "powers": {"GERMANY": row}},
        })  # fmt: skip
        self.assertIn('<span class="chip err"', page)
        self.assertIn("broke their word</span>", page)
        self.assertIn('<span class="stood err">we relied on it</span>', page)
        self.assertIn("its condition was met", page)
        self.assertIn("What the labels mean", page)
        self.assertEqual(press_report.legend([message])[0]["words"], "broke a promise we relied on")
        # Two codes with the same words are one line of the legend.
        both = [dict(claim, outcome=o, category="none") for o in ("released", "not_applicable")]
        self.assertEqual(len(press_report.legend([dict(message, claims=both)])), 1)
        self.assertNotIn("false_no_stance", page)
        self.assertNotIn("no stance", page)
        self.assertIn("PRU stays empty\nGermany", page)  # an older audit's line break, shown as one


if __name__ == "__main__":
    unittest.main()
