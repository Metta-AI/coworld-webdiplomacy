"""The HTML page for a press audit (`press_audit.py report`): what was said beside what was ordered.

One self-contained page, no network. It shows private press, so it stays on the user's
machine. Standard library only.
"""

from __future__ import annotations

import html
import re

POWER_ORDER = ("ENGLAND", "FRANCE", "ITALY", "GERMANY", "AUSTRIA", "TURKEY", "RUSSIA")


def turn_label(turn: int) -> str:
    return f"{'Spring' if turn % 2 == 0 else 'Autumn'} {1901 + turn // 2}"


# --- the words for a verdict ----------------------------------------------------------
#
# `press_audit.py` writes an `outcome` and a `category` on every claim (the press-audit skill lists
# them). Those values are for code. A reader sees the words below: `verdict()` for a claim, `WORDS`
# where a category stands alone (the summary's "How we stood" column, the IDE's timeline).
# Tones: "err" only for what cost us or was our own broken word, "warn" for what is worth a look,
# "ok" for a word that held, "quiet" for everything that is nobody's honesty.

TONE = {  # category -> tone; a claim without a category is "quiet"
    "betrayed": "err",
    "deceived": "err",
    "we_broke_our_word": "err",
    "doubted_wrongly": "warn",
    "false_no_stance": "warn",
    "trusted_rightly": "ok",
    "we_kept_our_word": "ok",
    "true_no_stance": "ok",
    "kept_despite_doubt": "ok",
}
WORDS = {  # every outcome and category, as it reads standing alone
    # outcomes
    "kept": "kept their word",
    "broken": "broke their word",
    "attempted": "tried, but the move failed",
    "superseded": "plan changed openly",
    "released": "did not apply: its condition was not met",
    "released_by_them": "let off: the other side broke the deal first",
    "carried_out": "carried out the threat",
    "not_carried_out": "did not carry out the threat",
    "not_triggered": "nothing to carry out: its condition was not met",
    "true": "true",
    "false": "not true",
    "forecast_right": "guess about another power: right",
    "forecast_wrong": "guess about another power: wrong",
    "complied": "did as asked",
    "refused": "did not do as asked",
    "followed": "did their side of the offer",
    "not_followed": "did not do their side of the offer",
    "not_applicable": "did not apply: its condition was not met",
    "unverifiable": "cannot be checked",
    "not_reached": "the game ended first",
    # categories
    "trusted_rightly": "held, and we relied on it",
    "betrayed": "broke a promise we relied on",
    "deceived": "misled us, and we relied on it",
    "doubted_rightly": "did not hold; we had not relied on it",
    "doubted_wrongly": "kept, but we doubted it and attacked them",
    "kept_despite_doubt": "held; we had not relied on it",
    "kept_but_attacked_us": "held, but they attacked us",
    "true_no_stance": "kept or true",
    "false_no_stance": "broken or not true",
    "we_kept_our_word": "we kept our word",
    "we_broke_our_word": "we broke our word",
    "kept_to_other": "held; it was to another power, not us",
    "broken_to_other": "did not hold; it was to another power, not us",
    "attack_announced": "said they would attack us, and did",
    "attack_not_made": "said they would attack us, and did not",
    "our_attack_announced": "we said we would attack them, and did",
    "our_attack_not_made": "we said we would attack them, and did not",
    "changed_plans": "moved a unit that was to stay put; attacked nobody",
    "we_changed_plans": "we moved a unit that was to stay put; attacked nobody",
    "misstated": "wrong about past orders: a slip, not a lie",
    "we_misstated": "we were wrong about past orders: a slip",
}
LEGEND = {  # the one line behind a label, where the label alone could mislead
    "attempted": "The order was given as promised, then bounced, was cut, or the unit was dislodged. "
                 "Counted as keeping the word.",
    "superseded": "A later message to the same power changed this plan before the orders went in. "
                  "Not a broken word.",
    "released": "A promise with an \"if\". The condition did not happen, so the promise never applied.",
    "released_by_them": "The other side attacked first, or had not done its half of the deal, "
                        "which freed the speaker.",
    "not_triggered": "A threat with an \"if\". The condition did not happen, so there was nothing to carry out.",
    "not_applicable": "It came with an \"if\" that did not happen.",
    "unverifiable": "No order or board position settles it: feelings, vague regions, retreats and builds.",
    "not_reached": "The game ended before the turns this covers.",
    "forecast_right": "Said about another power's orders before they were in: a guess, nobody's honesty.",
    "forecast_wrong": "Said about another power's orders before they were in: a guess, nobody's honesty.",
    "complied": "A request counts for the power that was asked, not for the one asking.",
    "refused": "A request counts for the power that was asked, not for the one asking. "
               "It may never have agreed to it.",
    "followed": "An offer not yet agreed. This is whether the sender did its own side; "
                "it counts for or against nobody's honesty.",
    "not_followed": "An offer not yet agreed. This is whether the sender did its own side; "
                    "it counts for or against nobody's honesty.",
    "trusted_rightly": "Our policy counted on this power that turn (an ally, or trust of 0.5 or more), "
                       "and the word held.",
    "betrayed": "A promise to us that our policy counted on, broken with no notice beforehand. "
                "These cost centres: look at what we committed because of it.",
    "deceived": "A statement of their coming orders, or a threat, that our policy counted on and that did not hold.",
    "doubted_rightly": "It did not hold, and our policy had not counted on it (a hostile stance, or trust below 0.5).",
    "doubted_wrongly": "Perhaps a missed alliance: a pledge not to move on us, which they could have broken and "
                       "kept, while we had not counted on it and moved on them. The least certain flag.",
    "kept_despite_doubt": "It held, and our policy had not counted on it. Nothing shows we lost by that.",
    "kept_but_attacked_us": "Kept in the letter while the speaker moved on our units or centres that turn or "
                            "the turn before. The orders are listed with the claim.",
    "true_no_stance": "Nothing stands beside this label: our policy logged no trust or distrust of this power "
                      "that turn, so the audit cannot say whether we relied on it.",
    "false_no_stance": "Nothing stands beside this label: our policy logged no trust or distrust of this power "
                       "that turn, so the audit cannot say whether we relied on it. Still a count of who lied.",
    "we_kept_our_word": "Our own promise, or what we said we would order, matched our orders.",
    "we_broke_our_word": "Our policy said one thing and ordered another.",
    "kept_to_other": "A word given to another power, which we only watched. Never a betrayal of us.",
    "broken_to_other": "A word given to another power, which we only watched. Never a betrayal of us.",
    "attack_announced": "They told us they would move on our unit or centre. Nothing we could rely on, "
                        "so never counted as a betrayal.",
    "attack_not_made": "They told us they would move on our unit or centre. Nothing we could rely on, "
                       "so never counted as a betrayal.",
    "our_attack_announced": "We told a power we would move on it. Whether we did is not a matter of our word.",
    "our_attack_not_made": "We told a power we would move on it. Whether we did is not a matter of our word.",
    "changed_plans": "All that was broken is \"this unit will stay put\", and the speaker made no move on the "
                     "power it said it to. A changed plan nobody was told about, not a stab.",
    "we_changed_plans": "All that was broken is \"this unit will stay put\", and we made no move on the power "
                        "we said it to. A changed plan nobody was told about, not a stab.",
    "misstated": "A wrong statement about orders already played. Everyone can read those off the board, "
                 "so nobody was deceived.",
    "we_misstated": "A wrong statement about orders already played. Everyone can read those off the board, "
                    "so nobody was deceived.",
}
OUR_WORDS = {  # an outcome when the speaker is our own seat
    "kept": "we kept our word",
    "broken": "we broke our word",
    "attempted": "we tried, but the move failed",
    "carried_out": "we carried out our threat",
    "not_carried_out": "we did not carry out our threat",
    "followed": "we did our side of the offer",
    "not_followed": "we did not do our side of the offer",
}
REQUEST_WORDS = {  # a request's outcome, said of the power that was asked
    "complied": "did as asked",
    "refused": "did not do as asked",
    "attempted": "tried, but the move failed",
}
ANNOUNCED = {  # category -> the note when an announced attack was ordered and failed
    "attack_announced": "the attack on us they had announced",
    "our_attack_announced": "the attack on them we had announced",
}
RELIED = {  # category -> how we stood, written beside the label
    "trusted_rightly": "we relied on it",
    "betrayed": "we relied on it",
    "deceived": "we relied on it",
    "doubted_rightly": "we had not relied on it",
    "kept_despite_doubt": "we had not relied on it",
    "doubted_wrongly": "we had not relied on it, and attacked them",
    "kept_but_attacked_us": "but they attacked us that turn or the turn before",
}


def _name(power: str, our_power: str) -> str:
    return "us" if power == our_power else power.title()


def verdict(claim: dict, message: dict, our_power: str) -> dict:
    """The words for one audited claim: `{label, note, tone, tip}`.

    `label` is what happened to the words, `note` (may be empty) how that stood for us or whom it
    concerned, `tone` one of err, warn, ok, quiet, and `tip` the one-line explanation ("" when the
    label needs none). `message` is the message the claim was made in (`from`, `to`).
    """
    outcome, category, kind = claim["outcome"], claim.get("category") or "none", claim["kind"]
    ours = message["from"] == our_power
    to = claim.get("to") or message["to"]
    label = (OUR_WORDS if ours else WORDS).get(outcome) or WORDS.get(outcome) or outcome.replace("_", " ")
    note = RELIED.get(category, "")
    if kind == "request" and outcome in REQUEST_WORDS:
        asked = claim.get("asked") or message["to"]
        label = f"{'we' if asked == our_power else asked.title()} {REQUEST_WORDS[outcome]}"
    if kind == "statement" and outcome in ("true", "false") and ours and claim.get("scope") == "own_orders":
        label = OUR_WORDS["kept" if outcome == "true" else "broken"]  # what we said we would order is our word
    if category in ANNOUNCED and outcome == "attempted":
        note = ANNOUNCED[category]
    elif category in ("attack_announced", "attack_not_made", "our_attack_announced", "our_attack_not_made"):
        label = WORDS[category]
    elif category in ("changed_plans", "we_changed_plans"):
        label = f"{'our' if ours else 'a'} unit moved that was to stay put"
        note = f"no attack on {_name(to, our_power)}"
    elif category in ("misstated", "we_misstated"):
        label = f"{'we were ' if ours else ''}wrong about past orders"
        note = "a slip, not a lie"
    elif category in ("kept_to_other", "broken_to_other"):
        what = {"promise": "promise was to", "threat": "threat was to"}.get(kind, "said of a deal with")
        note = f"{what} {to.title()}, not us"
    return {"label": label, "note": note, "tone": TONE.get(category, "quiet"),
            "tip": LEGEND.get(category) or LEGEND.get(outcome) or ""}  # fmt: skip


STYLE = """
:root{--bg:#fffdf4;--surface:#fffaf0;--fg:#111827;--sub:#555;--muted:#6b6560;--navy:#1a3875;--sage:#5d6d41;
--terra:#945637;--gold:#80601f;--border:#e4dac8;--strong:#d4c9b5;--soft:#f0ebe1;--accent:#5573a0;--accent-soft:#eef2f7}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.5 "Merriweather Sans",-apple-system,"Segoe UI",sans-serif}
main{max-width:1080px;margin:0 auto;padding:28px 24px 64px}
h1{font:700 26px/1.2 Merriweather,Georgia,serif;margin:0 0 4px}
h2{font:700 13px/1.3 Merriweather,Georgia,serif;text-transform:uppercase;letter-spacing:.12em;color:var(--navy);
margin:36px 0 10px;padding-bottom:6px;border-bottom:2px solid var(--strong)}
.lede{color:var(--sub);margin:0 0 6px}.note{color:var(--muted);font-size:13px;margin:4px 0}
table{border-collapse:collapse;width:100%;font-size:14px}
th{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.1em;color:var(--sub);
border-bottom:1px solid var(--strong);padding:6px 10px 6px 0}
td{padding:7px 10px 7px 0;border-bottom:1px solid var(--soft);vertical-align:top}
td.n,th.n{text-align:right}td.n{font-family:ui-monospace,Menlo,monospace;font-feature-settings:"tnum" 1}
td:first-child{white-space:nowrap}
.turn{display:grid;grid-template-columns:minmax(0,3fr) minmax(0,2fr);gap:28px;padding:14px 0;
border-bottom:1px solid var(--border)}
.turn h3{grid-column:1/-1;font:700 17px/1.2 Merriweather,Georgia,serif;margin:0}
.msg{margin:0 0 14px}.who{font-size:11px;text-transform:uppercase;letter-spacing:.1em;color:var(--sub);font-weight:700}
.msg.out .who{color:var(--navy)}.text{margin:2px 0 6px;white-space:pre-wrap}
.claim{margin:0 0 8px 14px;padding-left:12px;border-left:1px solid var(--strong);font-size:14px}
.quote{font-style:italic}.ev{color:var(--muted);font-size:13px;margin:2px 0 0}
.chip{display:inline-block;height:20px;line-height:20px;padding:0 8px;border-radius:3px;font-size:10px;font-weight:700;
text-transform:uppercase;letter-spacing:.04em;margin-right:4px}.chip[title]{cursor:help}
.chip.ok{background:rgba(110,128,80,.12);color:var(--sage)}.chip.err{background:var(--terra);color:var(--bg)}
.chip.warn{background:rgba(128,96,31,.14);color:var(--gold)}.chip.quiet{background:var(--soft);color:var(--muted)}
.chip.kind{background:none;color:var(--sub);padding-left:0}
.count{display:inline-block;white-space:nowrap;margin:0 8px 3px 0}.count .chip{margin-right:2px}
.stood{color:var(--muted);font-size:13px;margin-right:6px}.stood.err{color:var(--terra);font-weight:700}
details{margin:10px 0 0;font-size:13px}summary{cursor:pointer;color:var(--navy)}
.legend{margin:8px 0 0;padding:0;list-style:none}
.legend li{padding:5px 0;border-bottom:1px solid var(--soft);color:var(--sub)}
.orders{font:13px/1.55 ui-monospace,Menlo,monospace;color:var(--sub)}.orders b{color:var(--fg);font-family:inherit}
.fail{color:var(--terra)}.empty{color:var(--muted);font-style:italic}
/* our seat: an accent tint wherever the powers are listed */
tr.us td{background:var(--accent-soft)}tr.us td:first-child{box-shadow:inset 2px 0 0 var(--accent);padding-left:6px}
.orders .us{background:var(--accent-soft);border-left:2px solid var(--accent);padding-left:4px}
@media(max-width:760px){.turn{grid-template-columns:minmax(0,1fr)}}
"""


def chip(words: str, tone: str = "quiet", tip: str = "") -> str:
    title = f' title="{html.escape(tip)}"' if tip else ""
    return f'<span class="chip {tone}"{title}>{html.escape(words)}</span>'


def category_chip(category: str) -> str:
    """A category standing alone, as in the summary table."""
    words = WORDS.get(category, category.replace("_", " "))
    return chip(words, TONE.get(category, "quiet"), LEGEND.get(category, ""))


CONDITION_WORDS = {"met": "its condition was met", "unverifiable": "its condition cannot be checked"}


def render_claim(claim: dict, message: dict, our_power: str) -> str:
    said = verdict(claim, message, our_power)
    chips = chip(claim["kind"], "kind") + chip(said["label"], said["tone"], said["tip"])
    if said["note"]:
        chips += f'<span class="stood {said["tone"]}">{html.escape(said["note"])}</span>'
    if claim["condition"] in CONDITION_WORDS:  # an unmet condition is already the outcome
        chips += f'<span class="stood">{CONDITION_WORDS[claim["condition"]]}</span>'
    evidence = "".join(f'<div class="ev">{html.escape(line)}</div>' for line in claim["evidence"])
    context = f' <span class="ev">[{html.escape(claim["context"])}]</span>' if claim.get("context") else ""
    return (
        f'<div class="claim">{chips}<div class="quote">{html.escape(claim.get("quote") or "")}{context}</div>'
        f"{evidence}</div>"
    )


def render_message(message: dict, our_power: str) -> str:
    to = "everyone" if message["to"] == "ALL" else message["to"].title()
    claims = "".join(render_claim(c, message, our_power) for c in message["claims"])
    return (
        f'<div class="msg {message["direction"]}"><div class="who">{html.escape(message["from"].title())} to '
        f"{html.escape(to)} · {html.escape(message['sent_in'])}</div>"
        # An audit made before `extract` turned upstream's "<br />" into a new line still has the tag.
        f'<div class="text">{html.escape(re.sub(r"<br\s*/?>", chr(10), message["text"]))}</div>{claims}</div>'
    )


def legend(messages: list[dict]) -> list[dict]:
    """What the labels in these messages mean: `{words, tone, tip}` for each kind of verdict that
    occurs and needs a line, the flagged ones first."""
    present = set()
    for message in messages:
        for claim in message["claims"]:
            present.add(claim["category"] if claim["category"] in LEGEND else claim["outcome"])
    order = {"err": 0, "warn": 1, "ok": 2}
    codes = sorted((c for c in present if c in LEGEND), key=lambda c: (order.get(TONE.get(c), 3), WORDS[c]))
    rows = {WORDS[c]: {"words": WORDS[c], "tone": TONE.get(c, "quiet"), "tip": LEGEND[c]} for c in reversed(codes)}
    return list(reversed(rows.values()))  # two codes with the same words are one row


LEGEND_LEAD = (
    "Red is kept for three things: a promise to us that we relied on and that was broken, a statement or "
    "threat we relied on that did not hold, and our own broken word. Pointing at a label shows its line."
)


def render_legend(messages: list[dict]) -> str:
    rows = "".join(f"<li>{chip(row['words'], row['tone'])} {html.escape(row['tip'])}</li>" for row in legend(messages))
    if not rows:
        return ""
    return (
        f'<details><summary>What the labels mean</summary><p class="note">{LEGEND_LEAD}</p>'
        f'<ul class="legend">{rows}</ul></details>'
    )


def render_orders(phase: dict, our_power: str) -> str:
    lines = []
    for power in POWER_ORDER:
        orders = [o for o in phase["orders"] if o["power"] == power]
        if orders:
            shown = ", ".join(
                html.escape(o["text"])
                if o["success"] or o["type"] == "hold"
                else f'<span class="fail">{html.escape(o["text"])} (failed)</span>'
                for o in orders
            )
            if power == our_power:
                lines.append(f'<div class="us"><b>{power.title()} (us)</b> {shown}</div>')
            else:
                lines.append(f"<div><b>{power.title()}</b> {shown}</div>")
    return '<div class="orders">' + "".join(lines) + "</div>"


def render_summary(summary: dict) -> str:
    rows = []
    for power, row in sorted(summary["powers"].items()):
        share = "—" if row["held_share"] is None else f"{row['held_share']:.0%}"
        asked = "—" if not row["asked"] else f"{row['complied']} of {row['asked']}"
        cats = " ".join(f'<span class="count">{category_chip(name)}×{count}</span>'
                        for name, count in sorted(row["categories"].items()))
        us = power == summary["our_power"]
        row_class = ' class="us"' if us else ""
        rows.append(
            f"<tr{row_class}><td>{power.title()}{' (us)' if us else ''}</td>"
            f'<td class="n">{row["messages"]}</td><td class="n">{row["claims"]}</td>'
            f'<td class="n">{row["held"]}</td><td class="n">{row["did_not_hold"]}</td><td class="n">{share}</td>'
            f'<td class="n">{row["unverifiable"]}</td><td class="n">{asked}</td><td>{cats}</td></tr>'
        )
    if not rows:
        rows.append('<tr><td colspan="9" class="empty">No press was seen in this game.</td></tr>')
    return (
        '<table><tr><th>Speaker</th><th class="n">Messages</th><th class="n">Claims</th><th class="n">Held</th>'
        '<th class="n">Did not hold</th><th class="n">Held, of those checked</th>'
        '<th class="n">Not checkable</th><th class="n">Requests to them met</th><th>How we stood</th></tr>'
        + "".join(rows)
        + "</table>"
        '<p class="note">"Held" counts a speaker\'s promises kept, threats carried out and statements that were '
        "true. A game gives each power only a few checkable claims: read these as observations, not rates.</p>"
    )


def render_report(data: dict) -> str:
    by_turn: dict[int, list[dict]] = {}
    for message in data["messages"]:
        by_turn.setdefault(message["turn"], []).append(message)
    phases = {p["turn"]: p for p in data["phases"]}
    turns = []
    for turn in sorted(set(by_turn) | set(phases)):
        said = "".join(render_message(m, data["our_power"]) for m in by_turn.get(turn, []))
        said = said or '<p class="empty">No press this turn.</p>'
        done = (
            render_orders(phases[turn], data["our_power"])
            if turn in phases
            else '<p class="empty">Not played: the game had ended.</p>'
        )
        turns.append(f'<section class="turn"><h3>{turn_label(turn)}</h3><div>{said}</div><div>{done}</div></section>')
    summary = data["summary"]
    belief = (
        ""
        if data["belief_logged"]
        else '<p class="note">This policy does not log whom it trusts, so "relied on" could not be worked out: '
        "claims are marked only as held or not.</p>"
    )
    title = f"Press audit: {data['our_power'].title()}, {data['policy']}"
    return (
        f'<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" '
        f'content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title><style>{STYLE}</style>'
        f"<main><h1>{html.escape(title)}</h1>"
        f'<p class="lede">Episode {html.escape(str(data["episode"]))} · score {data["score"]:.3f} · '
        f"{summary['messages']} messages seen, {summary['messages_with_claims']} with a claim</p>"
        '<p class="note">Private press: keep this page on your machine. Claims were extracted by an agent; '
        "every verdict was checked by code against the adjudicated orders shown beside it.</p>"
        f"{belief}<h2>Whose word held</h2>{render_summary(summary)}{render_legend(data['messages'])}"
        "<h2>Turn by turn: what was said, what was ordered</h2>" + "".join(turns) + "</main></html>"
    )
