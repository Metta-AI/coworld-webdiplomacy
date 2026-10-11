"""The HTML page for a press audit (`press_audit.py report`): what was said beside what was ordered.

One self-contained page, no network. It shows private press, so it stays on the user's
machine. Standard library only.
"""

from __future__ import annotations

import html

POWER_ORDER = ("ENGLAND", "FRANCE", "ITALY", "GERMANY", "AUSTRIA", "TURKEY", "RUSSIA")


def turn_label(turn: int) -> str:
    return f"{'Spring' if turn % 2 == 0 else 'Autumn'} {1901 + turn // 2}"


CHIP = {  # outcome or category -> chip class
    "kept": "ok",
    "true": "ok",
    "carried_out": "ok",
    "complied": "ok",
    "trusted_rightly": "ok",
    "we_kept_our_word": "ok",
    "doubted_rightly": "ok",
    "true_no_stance": "ok",
    "attack_announced": "muted",
    "attack_not_made": "muted",
    "broken": "err",
    "false": "err",
    "not_carried_out": "err",
    "betrayed": "err",
    "deceived": "err",
    "we_broke_our_word": "err",
    "false_no_stance": "err",
    "followed": "ok",
    "not_followed": "gold",
    "refused": "gold",
    "doubted_wrongly": "gold",
    "released": "muted",
    "not_triggered": "muted",
    "not_applicable": "muted",
    "unverifiable": "muted",
    "not_reached": "muted",
    "attempted": "ok",
    "released_by_them": "muted",
    "our_attack_announced": "muted",
    "our_attack_not_made": "muted",
    "changed_plans": "muted",
    "we_changed_plans": "muted",
    "superseded": "muted",
    "forecast_right": "muted",
    "forecast_wrong": "muted",
    "misstated": "muted",
    "we_misstated": "muted",
    "kept_to_other": "muted",
    "broken_to_other": "gold",
    "kept_but_attacked_us": "muted",
    "kept_despite_doubt": "muted",
}
WORDS = {
    "kept": "kept",
    "broken": "broken",
    "released": "released: condition not met",
    "released_by_them": "released: the other side broke the deal first",
    "our_attack_announced": "our attack on them, announced and made",
    "our_attack_not_made": "our attack on them, announced and not made",
    "changed_plans": "a unit did not stay put; no move on us",
    "we_changed_plans": "our unit did not stay put; no move on them",
    "true": "true",
    "false": "false",
    "carried_out": "carried out",
    "not_carried_out": "bluff",
    "not_triggered": "not triggered",
    "complied": "complied with",
    "followed": "they did their part",
    "not_followed": "they did not do their part",
    "refused": "refused",
    "unverifiable": "not checkable",
    "not_reached": "game ended first",
    "not_applicable": "condition not met",
    "trusted_rightly": "we relied on it, rightly",
    "betrayed": "we relied on it: betrayed",
    "deceived": "we relied on it: deceived",
    "doubted_wrongly": "we doubted it, wrongly",
    "doubted_rightly": "we doubted it, rightly",
    "we_kept_our_word": "we kept our word",
    "we_broke_our_word": "we broke our word",
    "true_no_stance": "held; we took no stance",
    "false_no_stance": "did not hold; we took no stance",
    "attack_announced": "an attack on us, announced and made",
    "attack_not_made": "an attack on us, announced and not made",
    "attempted": "ordered, but it failed",
    "superseded": "changed in the open before the orders",
    "forecast_right": "a forecast, right",
    "forecast_wrong": "a forecast, wrong",
    "misstated": "wrong about orders already public",
    "we_misstated": "we were wrong about orders already public",
    "kept_to_other": "held; said to another power",
    "broken_to_other": "did not hold; said to another power",
    "kept_but_attacked_us": "held, but they moved on us",
    "kept_despite_doubt": "held; we had not relied on it",
}
STYLE = """
:root{--bg:#fffdf4;--surface:#fffaf0;--fg:#111827;--sub:#555;--muted:#6b6560;--navy:#1a3875;--sage:#5d6d41;
--terra:#945637;--gold:#80601f;--border:#e4dac8;--strong:#d4c9b5;--soft:#f0ebe1}
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
text-transform:uppercase;letter-spacing:.04em;margin-right:4px}
.ok{background:rgba(110,128,80,.16);color:var(--sage)}.err{background:rgba(179,110,78,.16);color:var(--terra)}
.gold{background:rgba(128,96,31,.14);color:var(--gold)}.muted{background:var(--soft);color:var(--muted)}
.kind{background:#eef2f7;color:var(--navy)}
.orders{font:13px/1.55 ui-monospace,Menlo,monospace;color:var(--sub)}.orders b{color:var(--fg);font-family:inherit}
.fail{color:var(--terra)}.empty{color:var(--muted);font-style:italic}
@media(max-width:760px){.turn{grid-template-columns:minmax(0,1fr)}}
"""


def chip(value: str, cls: str | None = None) -> str:
    return f'<span class="chip {cls or CHIP.get(value, "muted")}">{html.escape(WORDS.get(value, value))}</span>'


def render_claim(claim: dict) -> str:
    chips = chip(claim["kind"], "kind") + chip(claim["outcome"])
    if claim["category"] != "none":
        chips += chip(claim["category"])
    if claim["condition"] in ("met", "unverifiable"):  # an unmet condition is already the outcome
        chips += chip(f"condition {claim['condition']}", "muted")
    evidence = "".join(f'<div class="ev">{html.escape(line)}</div>' for line in claim["evidence"])
    context = f' <span class="ev">[{html.escape(claim["context"])}]</span>' if claim.get("context") else ""
    return (
        f'<div class="claim">{chips}<div class="quote">{html.escape(claim.get("quote") or "")}{context}</div>'
        f"{evidence}</div>"
    )


def render_message(message: dict) -> str:
    to = "everyone" if message["to"] == "ALL" else message["to"].title()
    claims = "".join(render_claim(c) for c in message["claims"])
    return (
        f'<div class="msg {message["direction"]}"><div class="who">{html.escape(message["from"].title())} to '
        f"{html.escape(to)} · {html.escape(message['sent_in'])}</div>"
        f'<div class="text">{html.escape(message["text"])}</div>{claims}</div>'
    )


def render_orders(phase: dict) -> str:
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
            lines.append(f"<div><b>{power.title()}</b> {shown}</div>")
    return '<div class="orders">' + "".join(lines) + "</div>"


def render_summary(summary: dict) -> str:
    rows = []
    for power, row in sorted(summary["powers"].items()):
        share = "—" if row["held_share"] is None else f"{row['held_share']:.0%}"
        asked = "—" if not row["asked"] else f"{row['complied']} of {row['asked']}"
        cats = " ".join(f"{chip(name)}×{count}" for name, count in sorted(row["categories"].items()))
        rows.append(
            f"<tr><td>{power.title()}{' (us)' if power == summary['our_power'] else ''}</td>"
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
        said = "".join(render_message(m) for m in by_turn.get(turn, [])) or '<p class="empty">No press this turn.</p>'
        done = render_orders(phases[turn]) if turn in phases else '<p class="empty">Not played: the game had ended.</p>'
        turns.append(f'<section class="turn"><h3>{turn_label(turn)}</h3><div>{said}</div><div>{done}</div></section>')
    summary = data["summary"]
    belief = (
        ""
        if data["belief_logged"]
        else '<p class="note">This policy logs no press policy, so "relied on" could not be worked out: '
        "claims are marked as held or not, with no stance.</p>"
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
        f"{belief}<h2>Whose word held</h2>{render_summary(summary)}"
        "<h2>Turn by turn: what was said, what was ordered</h2>" + "".join(turns) + "</main></html>"
    )
