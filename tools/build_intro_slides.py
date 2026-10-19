"""Build the two click-through introduction decks in docs/slides/.

    uv run --no-project --python 3.12 --with diplomacy==1.1.2 python tools/build_intro_slides.py

- docs/slides/how-to-play.html: how Diplomacy is played, told through small Austrian examples.
- docs/slides/game-of-the-week.html: why this Coworld, how to start, the optimizer, scoring.

Each file is self-contained (maps are inline SVG; only the web fonts are fetched). Every
example position is set up in the `diplomacy` package's engine and adjudicated by it, so a
"Result" map and the tick or "bounced" beside an order are the engine's verdict, not ours.
`diplomacy` is a tool-only dependency, hence `uv run --with`. The maps are drawn by that
package's renderer with our palette on top.
"""
# ruff: noqa: E501  (the page's CSS, script and slide text are long literal lines)

import html
import re
from pathlib import Path

import diplomacy
from diplomacy.engine.renderer import Renderer

OUT = Path(__file__).resolve().parents[1] / "docs" / "slides"
POWERS = ["ENGLAND", "FRANCE", "ITALY", "GERMANY", "AUSTRIA", "TURKEY", "RUSSIA"]  # upstream country ids 1..7
FULL_MAP = "150 110 1540 1160"
BALKANS = "690 700 760 560"
RESULT_WORDS = {"bounce": "bounced", "cut": "support cut", "void": "no effect", "dislodged": "dislodged",
                "disband": "disbanded", "no convoy": "no convoy"}


# --- boards and maps -------------------------------------------------------------------------

def board(phase, units, centers=None):
    """A game at `phase` with exactly these units ({power: ["A BUD", ...]}) and centre owners."""
    game = diplomacy.Game()
    game.set_current_phase(phase)
    game.clear_units()
    for power, held in units.items():
        game.set_units(power, held)
    if centers is not None:
        game.clear_centers()
        for power, owned in centers.items():
            game.set_centers(power, owned)
    return game


class MapDrawer:
    def __init__(self):
        self.count = 0
        self.power_strokes = None

    def draw(self, game, crop=FULL_MAP, orders=True, highlight_centers=False, bold=(), fill=False):
        """Inline-ready SVG of `game`, cropped to `crop`, with the current orders drawn.

        `bold` names what to pick out in strong colour: a power ("austria") or a province
        ("gal"). `fill` makes the map cover its box (a backdrop) instead of fitting inside it.
        """
        svg = Renderer(game).render(incl_orders=orders, incl_abbrev=True)
        if self.power_strokes is None:
            # The renderer strokes each order in the power's built-in colour; map those to our palette.
            self.power_strokes = {
                re.search(r"\.%s\s*\{fill:([#\w]+)" % power.lower(), svg).group(1): "var(--p%d)" % (n + 1)
                for n, power in enumerate(POWERS)}
        self.count += 1
        prefix = "m%d-" % self.count
        svg = re.sub(r"<\?xml.*?\?>|<!DOCTYPE[^>]*>|<!--.*?-->", "", svg, flags=re.S)
        svg = re.sub(r"<style.*?</style>", "", svg, flags=re.S)
        for built_in, ours in self.power_strokes.items():
            svg = svg.replace('stroke="%s"' % built_in, 'style="stroke:%s"' % ours)
        if highlight_centers:
            rings = "".join('<circle class="centre-ring" cx="%.1f" cy="%.1f" r="19"/>' % (float(x) + 10, float(y) + 10)
                            for x, y in re.findall(r'<use height="20" id="sc_\w+" width="20" x="([\d.]+)"[^>]*y="([\d.]+)"', svg))
            svg = svg.replace('<g id="OrderLayer">', "<g>%s</g><g id=\"OrderLayer\">" % rings, 1)
        svg = re.sub(r'\sid="([^"]+)"', lambda m: ' id="%s%s"' % (prefix, m.group(1)), svg)
        svg = re.sub(r"url\(#([^)]+)\)", lambda m: "url(#%s%s)" % (prefix, m.group(1)), svg)
        svg = re.sub(r'href="#([^"]+)"', lambda m: 'href="#%s%s"' % (prefix, m.group(1)), svg)
        head = re.search(r"<svg[^>]*>", svg).group(0)
        new_head = re.sub(r'\s(width|height|viewBox|preserveAspectRatio)="[^"]*"', "", head)
        new_head = new_head[:-1] + ' id="%sroot" viewBox="%s" preserveAspectRatio="xMidYMid %s" role="img">' % (
            prefix, crop, "slice" if fill else "meet")
        rules = []
        for name in bold:
            if name.upper() in POWERS:
                rules.append("#%sroot .%s{fill:var(--b%d)}" % (prefix, name, POWERS.index(name.upper()) + 1))
            else:
                rules.append("#%sroot #%s_%s{fill:#f0c94a;stroke:#80601f;stroke-width:5}" % (prefix, prefix, name))
        style = "<style>%s</style>" % "".join(rules) if rules else ""
        return svg.replace(head, new_head + style, 1).strip()


def order_words(order):
    """'A BUD S A SER - RUM' -> 'A BUD supports A SER → RUM'."""
    text = order.replace(" VIA", " by convoy")
    text = re.sub(r" S (.*)", r" supports \1", text)
    text = re.sub(r" C (.*)", r" convoys \1", text)
    text = re.sub(r" R (\w+)", r" retreats to \1", text)
    text = re.sub(r" H$", " holds", text)
    text = re.sub(r" B$", " is built", text)
    text = re.sub(r" D$", " is removed", text)
    return text.replace(" - ", " → ")


def play(game, orders):
    """Give the orders, let the engine adjudicate, and return one chip per order with its result."""
    for power, texts in orders.items():
        game.set_orders(power, texts)
    game.process()
    results = game.result_history.last_value()
    chips = []
    for power, texts in orders.items():
        for text in texts:
            unit = " ".join(text.split()[:2])
            codes = [RESULT_WORDS.get(str(code), str(code)) for code in results.get(unit, []) if str(code)]
            mark = '<em class="bad">%s</em>' % ", ".join(codes) if codes else '<em class="ok">✓</em>'
            chips.append('<li><span class="dot p%d"></span>%s %s</li>'
                         % (POWERS.index(power) + 1, html.escape(order_words(text)), mark))
    return '<ul class="orders">%s</ul>' % "".join(chips)


def panel(label, svg, extra=""):
    return ('<figure class="panel"><figcaption><b>%s</b>%s</figcaption><div class="mapwrap">%s</div></figure>'
            % (label, extra, svg))


def orders_and_result(drawer, game, orders, crop, labels=("Orders", "Result")):
    """Two panels: the board with the orders drawn, then the board the engine produced."""
    for power, texts in orders.items():
        game.set_orders(power, texts)
    before = drawer.draw(game, crop)
    chips = play(game, orders)
    return panel(labels[0], before, chips) + panel(labels[1], drawer.draw(game, crop, orders=False))


def orders_only(drawer, game, orders, crop, label):
    for power, texts in orders.items():
        game.set_orders(power, texts)
    before = drawer.draw(game, crop)
    return panel(label, before, play(game, orders))


def chat(messages):
    rows = []
    for sender, audience, text in messages:
        n = POWERS.index(sender) + 1
        if audience == "everyone":
            to = '<span class="chip chip-public">Public</span> to everyone'
        else:
            to = ('<span class="chip chip-private">Private</span> to <b class="p%d">%s</b>'
                  % (POWERS.index(audience) + 1, audience.title()))
        rows.append('<li class="msg"><span class="avatar p%d">%s</span><div><div class="msg-head">'
                    '<b class="p%d">%s</b> %s</div><p>%s</p></div></li>'
                    % (n, sender[0], n, sender.title(), to, html.escape(text)))
    return '<aside class="press"><h3>Press</h3><ol class="chat">%s</ol></aside>' % "".join(rows)


def legend():
    """The seven powers in their map colours, with what each starts with."""
    game = diplomacy.Game()
    rows = "".join('<li><span class="dot p%d"></span><b>%s</b><span>%s</span></li>'
                   % (n, power.title(), " · ".join(game.get_units(power)))
                   for n, power in enumerate(POWERS, 1))
    return '<aside class="legend"><h3>The seven powers</h3><ul>%s</ul></aside>' % rows


# --- deck 1: how to play ---------------------------------------------------------------------

def how_to_play(drawer):
    slides = []

    def add(title, bullets, stage):
        slides.append({"title": title, "bullets": bullets, "stage": stage})

    start = diplomacy.Game()
    add("Europe, 1901", [
        "Seven powers: England, France, Germany, Italy, Austria, Russia, Turkey.",
        "Each starts with three units (Russia four). <b>A</b> is an army, <b>F</b> is a fleet.",
        "No dice. Everyone's orders are revealed and resolved at the same moment.",
    ], legend() + panel("Spring 1901 · starting position", drawer.draw(start, orders=False)))

    add("The objective: supply centres", [
        "34 provinces are <b>supply centres</b> (ringed). Each one you own feeds one unit.",
        "Own <b>18 of the 34</b> and you win outright.",
        "Most games end before that; then your score comes from how many centres you hold.",
    ], legend() + panel("The 34 supply centres · tinted by owner, 12 start neutral",
             drawer.draw(start, orders=False, highlight_centers=True)))

    add("A turn: talk, then order", [
        "First comes <b>press</b>: private or public messages. Promise, plan, bluff.",
        "Then every power writes one order for each of its units, in secret.",
        "Nothing binds anyone to what they said. <b class=\"p5\">Austria</b> and <b class=\"p7\">Russia</b> both promise to leave <b class=\"gal\">Galicia</b> alone…",
    ], chat([
        ("AUSTRIA", "ITALY", "Tyrolia and Venice stay empty this year? I am going south-east."),
        ("ITALY", "AUSTRIA", "Agreed. No army in Tyrolia. I open west."),
        ("RUSSIA", "AUSTRIA", "I am not moving to Galicia. Are you?"),
        ("AUSTRIA", "RUSSIA", "No. Galicia stays empty."),
        ("TURKEY", "everyone", "Peace in the Balkans this spring."),
    ]) + panel("Spring 1901 · before orders · Austria, Russia and Galicia (GAL) picked out",
               drawer.draw(diplomacy.Game(), BALKANS, orders=False, bold=("austria", "russia", "gal"))))

    add("Move, hold, bounce", [
        "<b>Move</b> to a neighbouring province, or <b>hold</b>. Every unit has strength 1.",
        "A move into an empty province works: Budapest takes Serbia.",
        "Equal strength means a <b>bounce</b>: both went for Galicia, so nobody gets in. So much for promises.",
    ], orders_and_result(drawer, diplomacy.Game(), {
        "AUSTRIA": ["A BUD - SER", "A VIE - GAL", "F TRI H"],
        "RUSSIA": ["A WAR - GAL"],
    }, BALKANS))

    attack = {"AUSTRIA": ["A SER", "A BUD", "A GAL"], "RUSSIA": ["A RUM", "F BLA"]}
    game = board("F1902M", attack)
    add("Support: how attacks win", [
        "A unit can give up its own move to <b>support</b> a neighbour: each support adds 1.",
        "Serbia attacks Rumania with Budapest's support: 2 against 1.",
        "The stronger side wins. The Russian army is <b>dislodged</b>.",
    ], orders_and_result(drawer, game, {
        "AUSTRIA": ["A SER - RUM", "A BUD S A SER - RUM", "A GAL H"],
        "RUSSIA": ["A RUM H"],
    }, BALKANS))

    add("Retreats", [
        "A dislodged unit must <b>retreat</b> to a free neighbouring province, or be disbanded.",
        "It cannot go where its attacker came from, into an occupied province, or where a bounce just happened.",
        "No legal retreat means the unit is destroyed.",
    ], orders_and_result(drawer, game, {"RUSSIA": ["A RUM R UKR"]}, BALKANS, ("Retreat order", "Result")))

    defence = {"AUSTRIA": ["A SER"], "ITALY": ["A ALB"], "TURKEY": ["A BUL", "A GRE"]}
    turkish_attack = ["A BUL - SER", "A GRE S A BUL - SER"]
    add("Allies, and cutting support", [
        "You can support <b>another power's</b> unit. That is what alliances are made of.",
        "Left: Italy supports Serbia to hold. 2 against 2, so the Turkish attack fails.",
        "Right: Italy attacks the supporting army instead. A unit that is attacked has its support <b>cut</b>.",
    ], orders_only(drawer, board("S1902M", defence), {
        "TURKEY": turkish_attack, "AUSTRIA": ["A SER H"], "ITALY": ["A ALB S A SER"],
    }, BALKANS, "Support an ally's hold") + orders_only(drawer, board("S1902M", defence), {
        "TURKEY": turkish_attack, "AUSTRIA": ["A SER H"], "ITALY": ["A ALB - GRE"],
    }, BALKANS, "Or cut the support"))

    add("Fleets and convoys", [
        "Armies move on land. Fleets move on sea and along coasts, and can support into either.",
        "A fleet at sea can <b>convoy</b> an army across it: Trieste lands in Apulia.",
        "Dislodge the convoying fleet and the army stays home.",
    ], orders_and_result(drawer, board("S1902M", {
        "AUSTRIA": ["A TRI", "F ADR", "F GRE"], "ITALY": ["A VEN", "A ROM", "F NAP"],
    }), {
        "AUSTRIA": ["A TRI - APU VIA", "F ADR C A TRI - APU", "F GRE - ION"],
        "ITALY": ["A VEN H", "A ROM H", "F NAP H"],
    }, "640 880 760 470"))

    autumn = board("F1901M", {
        "AUSTRIA": ["A SER", "A GAL", "F GRE"],
        "RUSSIA": ["A WAR", "A MOS", "A UKR", "F BLA"],
        "TURKEY": ["A SEV", "A BUL", "F CON"],
    })
    autumn.process()  # everyone holds: the engine hands each occupied centre to its occupier
    add("Winter: builds and removals", [
        "After each autumn, an occupied supply centre changes hands. Then units must match centres.",
        "More centres than units: <b>build</b> in your own empty home centres. Austria has 5 and builds two.",
        "Fewer: <b>remove</b> units. Russia lost Sevastopol, has 3 centres for 4 units, and removes one.",
    ], orders_and_result(drawer, autumn, {
        "AUSTRIA": ["A VIE B", "A BUD B"],
        "RUSSIA": ["A UKR D"],
        "TURKEY": ["A SMY B", "F ANK B"],
    }, "690 640 900 640", ("Winter 1901 · builds and removals", "Spring 1902")))

    home = {"AUSTRIA": ["A VIE", "A BUD", "A TRI"]}
    add("Three things that catch people out", [
        "Two units cannot <b>swap</b> places (left), but three can <b>rotate</b> (right).",
        "You can never dislodge your own unit, even by accident.",
        "An illegal order becomes a hold. The server accepts it without an error, so check what was saved.",
    ], orders_only(drawer, board("S1902M", home), {
        "AUSTRIA": ["A VIE - BUD", "A BUD - VIE", "A TRI H"],
    }, "720 780 420 330", "A swap fails") + orders_only(drawer, board("S1902M", home), {
        "AUSTRIA": ["A VIE - BUD", "A BUD - TRI", "A TRI - VIE"],
    }, "720 780 420 330", "A rotation works"))

    return slides


# --- deck 2: game of the week ----------------------------------------------------------------

def score_example():
    centres = [("Turkey", 6, 10), ("France", 2, 7), ("England", 1, 6), ("Germany", 4, 5),
               ("Russia", 7, 4), ("Italy", 3, 2), ("Austria", 5, 0)]
    total = sum(count * count for _, _, count in centres)
    rows = []
    for name, n, count in centres:
        score = count * count / total
        rows.append('<tr><td><span class="dot p%d"></span>%s</td><td class="num">%d</td><td class="num">%d</td>'
                    '<td class="share"><span class="p%d-bg" style="width:%.1f%%"></span></td><td class="num">%.3f</td></tr>'
                    % (n, name, count, count * count, n, score * 100 / 0.5, score))
    return ('<table class="score"><thead><tr><th>Power</th><th class="num">Centres</th><th class="num">Squared</th>'
            '<th>Share of %d</th><th class="num">Score</th></tr></thead><tbody>%s</tbody></table>' % (total, "".join(rows)))


def backdrop(drawer, crop, units, orders, phase="S1903M"):
    """A faded map behind a text slide: a position with its orders drawn (not adjudicated)."""
    game = board(phase, units) if units else diplomacy.Game()
    for power, texts in orders.items():
        game.set_orders(power, texts)
        if len(game.get_orders(power)) != len(texts):
            raise ValueError("the engine dropped an order for %s: %s" % (power, texts))
    return '<div class="backdrop">%s</div>' % drawer.draw(game, crop, fill=True)


def game_of_the_week(drawer):
    def text(title, body, kicker, scene, cls=""):
        return {"stage": scene + '<div class="text card %s"><p class="eyebrow">%s</p><h2>%s</h2>%s</div>'
                         % (cls, kicker, title, body)}

    def bullets(items):
        return "<ul>%s</ul>" % "".join("<li>%s</li>" % item for item in items)

    lab = Path(__file__).resolve().parents[1] / "optimizer" / "mixin"
    tool_count = sum(1 for path in (lab / "tools").iterdir() if path.suffix in (".py", ".sh"))
    skill_count = sum(1 for _ in (lab / "skills").glob("*/SKILL.md"))

    # Spring 1901 with a common opening for every power.
    openings = backdrop(drawer, FULL_MAP, None, {
        "ENGLAND": ["F LON - NTH", "F EDI - NWG", "A LVP - YOR"],
        "FRANCE": ["F BRE - MAO", "A PAR - BUR", "A MAR - SPA"],
        "GERMANY": ["F KIE - DEN", "A BER - KIE", "A MUN - RUH"],
        "ITALY": ["A VEN - TYR", "A ROM - VEN", "F NAP - ION"],
        "AUSTRIA": ["A VIE - GAL", "A BUD - SER", "F TRI - ALB"],
        "RUSSIA": ["A WAR - GAL", "A MOS - UKR", "F SEV - BLA", "F STP/SC - BOT"],
        "TURKEY": ["F ANK - BLA", "A CON - BUL", "A SMY - CON"],
    })
    # Three powers go for Belgium at once: a convoy, a supported attack and a supported attack.
    belgium = backdrop(drawer, "150 470 1140 600", {
        "ENGLAND": ["A YOR", "F NTH", "F ENG"], "FRANCE": ["A PIC", "A BUR", "F BRE"],
        "GERMANY": ["A RUH", "F HOL", "A MUN"],
    }, {
        "ENGLAND": ["A YOR - BEL VIA", "F NTH C A YOR - BEL", "F ENG S A YOR - BEL"],
        "FRANCE": ["A PIC - BEL", "A BUR S A PIC - BEL", "F BRE - MAO"],
        "GERMANY": ["A RUH - BEL", "F HOL S A RUH - BEL", "A MUN - BUR"],
    })
    # Russia and Turkey together against Austria.
    juggernaut = backdrop(drawer, "700 640 1140 600", {
        "AUSTRIA": ["A SER", "A BUD", "A VIE", "F TRI"], "RUSSIA": ["A UKR", "A RUM", "F SEV"],
        "TURKEY": ["A BUL", "A GRE", "F AEG"],
    }, {
        "AUSTRIA": ["A SER H", "A BUD S A SER", "A VIE - GAL", "F TRI - ALB"],
        "RUSSIA": ["A UKR - GAL", "A RUM S A BUL - SER", "F SEV - BLA"],
        "TURKEY": ["A BUL - SER", "A GRE S A BUL - SER", "F AEG - ION"],
    })
    # The Lepanto: Italy convoys an army from Tunis to Syria behind Turkey.
    lepanto = backdrop(drawer, "520 700 1254 660", {
        "ITALY": ["A TUN", "F ION", "F EAS", "A VEN"], "AUSTRIA": ["F GRE", "A SER", "A BUD"],
        "TURKEY": ["F SMY", "A CON", "A BUL", "F ANK"],
    }, {
        "ITALY": ["A TUN - SYR VIA", "F ION C A TUN - SYR", "F EAS C A TUN - SYR", "A VEN H"],
        "AUSTRIA": ["F GRE - AEG", "A SER - BUL", "A BUD - RUM"],
        "TURKEY": ["F SMY H", "A CON S A BUL", "A BUL H", "F ANK - BLA"],
    })
    # England and Germany take Scandinavia from Russia.
    north = backdrop(drawer, "330 60 1254 660", {
        "ENGLAND": ["F NTH", "F NWG", "A EDI"], "GERMANY": ["F DEN", "F BAL", "A KIE"],
        "RUSSIA": ["A NWY", "F SWE", "A STP", "F BOT"],
    }, {
        "ENGLAND": ["F NTH - NWY", "F NWG S F NTH - NWY", "A EDI H"],
        "GERMANY": ["F DEN - SWE", "F BAL S F DEN - SWE", "A KIE - DEN"],
        "RUSSIA": ["A NWY H", "F SWE H", "A STP S A NWY", "F BOT S F SWE"],
    })

    slides = [{"stage": openings + '<div class="text title"><p class="eyebrow">Softmax · Game of the Week</p>'
               "<h2>webDiplomacy</h2><p class=\"lede\">Negotiate. Cooperate. Compete. Betray.</p></div>"}]

    slides.append(text("Why webDiplomacy", bullets([
        "<b>Fluid social dynamics</b>",
        "<b>A well-known benchmark</b>",
        "<b>Theory of mind, simple rules</b>",
        "<b>Built for an outside community</b>",
    ]), "The case", juggernaut, "narrow right"))

    slides.append(text("The game on Softmax", bullets([
        "<b>Three-minute turns, eight-year games</b>",
        "<b>Container-based players</b>",
        "<b>Every bot knows who plays each power</b>",
        "<b>Two leagues: press and gunboat.</b> Only the press league counts for victory.",
    ]), "What you are entering", belgium, "narrow right"))

    slides.append(text("How to get started", '<ol class="steps">'
        "<li><b>Make your own optimizer</b> from the template, outside this repository."
        "<code>gh repo create my-webdip-optimizer --template Metta-AI/webdip-optimizer --private --clone</code></li>"
        "<li><b>Install the CLIs and sign in.</b>"
        "<code>uv tool install coworld &amp;&amp; uv tool install softmax-cli &amp;&amp; softmax login</code></li>"
        "<li><b>Point your coding agent at the optimizer</b> and have it open"
        "<code>docs/getting-started.md</code></li>"
        "<li><b>Say “open the IDE”</b> for replays, results and experiments in the browser.</li>"
        "</ol><p class=\"foot\">Or hand your agent the coworld-webdiplomacy README: it does all four. "
        "Needs Git, gh, uv and Docker.</p>", "Four steps", lepanto))

    slides.append(text("What the optimizer gives your agent", '<div class="cols">'
        "<section><h3>Run experiments</h3><ul>"
        "<li><code>ship.py</code> builds, uploads and logs a version in one step</li>"
        "<li><code>run_ab.py</code> runs a paired A/B on hosted games, start to finish</li>"
        "<li><code>sizing.py</code> says how many games a result needs</li></ul></section>"
        "<section><h3>Read the diplomacy</h3><ul>"
        "<li><code>press_audit.py</code> checks what was said against what was ordered: who betrayed us, and when we broke our word</li>"
        "<li><code>centre_losses.py</code> lists every centre we lost, who took it, and whether we had called them an ally</li>"
        "<li><code>opponent_profile.py</code> measures how each opponent really plays</li></ul></section>"
        "<section><h3>See it</h3><ul>"
        "<li><b>A starter policy</b>: a search core plus an LLM press layer</li>"
        "<li><b>The IDE</b>: replays with the press audit on the board, a matchup dashboard, experiment records</li>"
        "<li><b>%d skills</b> that walk the agent through surveys, A/B tests and diagnosis</li></ul></section>"
        "</div>" % skill_count,
        "Installed with the template · %d tools, %d skills, one index" % (tool_count, skill_count), north))

    slides.append(text("Scoring and rating", '<div class="split"><div>' + bullets([
        "<b>Solo win</b> (18 centres): the winner scores 1, everyone else 0.",
        "<b>Otherwise</b>: your centres squared, divided by everyone's centres squared. An even share is 1/7 = 0.143.",
        "<b>Rating is plain OpenSkill.</b> Each game ranks its entrants by score. Only the order counts, not the gap.",
        "Your MMR is μ − 3σ: it starts near zero and rises as your games come in.",
        "<b>The final winner</b> is chosen from the top seven policies by MMR, in a round-robin tournament.",
    ]) + "</div>" + score_example() + "</div>", "One game, one score", openings.replace("backdrop", "backdrop faint", 1)))

    return slides


# --- page ------------------------------------------------------------------------------------

CSS = """
:root{--bg:#fffdf4;--surface:#fffaf0;--surface-alt:#f8f6ef;--fg:#111827;--fg-subtle:#555555;--fg-muted:#6b6560;
--ink-navy:#1a3875;--ink-sage:#5d6d41;--ink-terracotta:#945637;--ink-gold:#80601f;--accent:#5573a0;
--border:#e4dac8;--border-strong:#d4c9b5;--border-subtle:#f0ebe1;
--p1:#6d5a9c;--p2:#3f6f9f;--p3:#5d7f3e;--p4:#5f5953;--p5:#a3533a;--p6:#a8862a;--p7:#7d8794;
--t1:#ddd5ec;--t2:#d3e0ee;--t3:#dbe6cf;--t4:#dedad5;--t5:#efd6cc;--t6:#efe3c2;--t7:#e3e6ea;
--b1:#a797cf;--b2:#86aed6;--b3:#a3c283;--b4:#a9a199;--b5:#dd9580;--b6:#dcc06a;--b7:#98a2b4;
--serif:'Merriweather',Georgia,serif;--sans:'Merriweather Sans','Helvetica Neue',sans-serif;--mono:ui-monospace,'SF Mono',Menlo,monospace}
*{box-sizing:border-box}html,body{height:100%;margin:0}
body{background:var(--bg);color:var(--fg);font-family:var(--sans);font-size:15px;line-height:1.5;display:flex;flex-direction:column;overflow:hidden}
header.bar{display:flex;align-items:baseline;gap:16px;padding:12px 24px 10px;border-bottom:2px solid var(--border-strong)}
header.bar h1{font-family:var(--serif);font-size:18px;margin:0}
.eyebrow{font-size:11px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--fg-subtle);margin:0}
.spacer{flex:1}.counter{font-family:var(--mono);font-size:12px;color:var(--fg-muted)}
button{font:inherit;font-weight:600;font-size:13px;border-radius:3px;padding:5px 12px;cursor:pointer;background:var(--surface);color:var(--fg);border:1px solid var(--border-strong)}
button:hover{background:var(--surface-alt)}button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
button.primary{background:#0e2758;color:#fffdf4;border-color:#0a1c42}button.primary:hover{background:#1a3875}
main{flex:1;min-height:0;position:relative}
.slide{position:absolute;inset:0;display:none;flex-direction:column;min-height:0}.slide.on{display:flex}
.stage{flex:1;min-height:0;display:flex;gap:20px;padding:14px 24px 10px;position:relative}
/* the caption sits at the same place and height on every slide */
.caption{height:188px;flex:none;border-top:1px solid var(--border);background:var(--surface);padding:14px 24px 0;display:grid;grid-template-columns:minmax(220px,300px) 1fr;gap:28px;overflow:hidden}
.caption h2{font-family:var(--serif);font-size:25px;line-height:1.2;margin:2px 0 0;color:var(--ink-navy)}
.caption ul{margin:0;padding-left:20px;font-size:17px;line-height:1.45;max-width:86ch}.caption li{margin:0 0 6px}
.panel{flex:1;min-width:0;min-height:0;margin:0;display:flex;flex-direction:column}
.panel figcaption{display:flex;flex-wrap:wrap;align-items:baseline;gap:2px 14px;padding-bottom:6px;height:74px;align-content:flex-start;overflow:hidden}
.panel figcaption b{font-family:var(--serif);font-size:15px;flex-basis:100%}
.mapwrap{flex:1;min-height:0;background:#c3dae6;border-radius:4px;overflow:hidden}
.mapwrap svg{display:block;width:100%;height:100%}
.orders{list-style:none;display:flex;flex-wrap:wrap;gap:2px 14px;margin:0;padding:0;font-family:var(--mono);font-size:12.5px;color:var(--fg-subtle)}
.orders em{font-style:normal;font-weight:700}.orders .ok{color:var(--ink-sage)}.orders .bad{color:var(--ink-terracotta)}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px}
.press{flex:0 0 min(380px,34%);display:flex;flex-direction:column;min-height:0}
.press h3{font-family:var(--serif);font-size:15px;margin:0;padding:0 0 6px;height:74px}
.chat{list-style:none;margin:0;padding:0;overflow-y:auto}
.msg{display:grid;grid-template-columns:30px 1fr;gap:10px;padding:7px 0;border-bottom:1px solid var(--border-subtle)}
.avatar{width:30px;height:30px;border-radius:50%;display:grid;place-items:center;color:#fffdf4;font-weight:700;font-size:13px}
.msg-head{font-size:12px;color:var(--fg-subtle)}.msg p{margin:3px 0 0;font-size:14px}
.chip{display:inline-block;font-size:9.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;border-radius:999px;padding:1px 7px}
.chip-private{background:rgba(128,96,31,.14);color:var(--ink-gold)}.chip-public{background:rgba(85,115,160,.16);color:var(--ink-navy)}
.legend{flex:0 0 250px}.legend h3{font-family:var(--serif);font-size:15px;margin:0;padding:0 0 6px;height:74px}
.legend ul{list-style:none;margin:0;padding:0}.legend li{padding:9px 0;border-bottom:1px solid var(--border-subtle)}
.legend li span:last-child{display:block;font-family:var(--mono);font-size:12px;color:var(--fg-muted);margin-left:15px}
/* text slides */
.text{margin:auto;width:min(1080px,100%);position:relative}
.text h2{font-family:var(--serif);font-size:40px;line-height:1.15;margin:6px 0 22px;color:var(--ink-navy)}
.text ul,.text ol{margin:0;padding-left:24px;font-size:20px;line-height:1.5}.text li{margin:0 0 14px}
.text code{font-family:var(--mono);font-size:.82em;background:var(--surface-alt);padding:1px 5px;border-radius:3px}
.steps code{display:block;margin-top:5px;padding:6px 10px;overflow-wrap:anywhere}
.foot{color:var(--fg-muted);font-size:15px;margin:18px 0 0 24px}
.cols{display:grid;grid-template-columns:repeat(3,1fr);gap:36px}.cols h3{font-family:var(--serif);font-size:17px;margin:0 0 10px}
.cols ul{font-size:16px;padding-left:18px}.cols li{margin-bottom:10px}
.split{display:grid;grid-template-columns:1fr minmax(360px,440px);gap:44px;align-items:start}.split ul{font-size:18px}
table.score{border-collapse:collapse;font-size:14px;width:100%}
.score th{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--fg-subtle);text-align:left;border-bottom:2px solid var(--border-strong);padding:6px}
.score td{padding:7px 6px;border-bottom:1px solid var(--border-subtle);white-space:nowrap}
.num{text-align:right!important;font-family:var(--mono);font-feature-settings:"tnum" 1}
.share{width:38%}.share span{display:block;height:10px;border-radius:2px;min-width:1px}
.title{text-align:center}.title h2{font-size:84px;margin:10px 0 14px;color:var(--fg)}
.lede{font-family:var(--serif);font-size:30px;color:var(--ink-navy);margin:0 0 14px}
.backdrop{position:absolute;inset:0;opacity:.62;pointer-events:none}.backdrop svg{width:100%;height:100%}
.backdrop.faint{opacity:.3}
.card.narrow{width:min(560px,100%)}.card.right{margin:auto 4% auto auto}
.card{background:rgba(255,253,244,.9);border:1px solid var(--border-strong);border-radius:4px;padding:34px 44px 30px;box-shadow:0 10px 40px rgba(17,24,39,.18)}
.title{background:radial-gradient(closest-side,rgba(255,253,244,.94) 55%,rgba(255,253,244,0));padding:70px 90px}
/* map palette over the diplomacy renderer's classes */
.water{fill:#c3dae6;stroke:#5a5650;stroke-width:1}.nopower{fill:#f5eedf;stroke:#5a5650;stroke-width:1}
.neutral{fill:#ebe4d4;stroke:#5a5650;stroke-width:1}.impassable{fill:#5f5953;stroke:#3a3633}
.currentnotetext,.currentphasetext,.currentnoterect{display:none}
.supportorder{stroke-width:6;fill:none;stroke-dasharray:5,5}.convoyorder{stroke-dasharray:15,5;stroke-width:6;fill:none}
.shadowdash{stroke-width:10;fill:none;stroke:#111827;opacity:.35}.varwidthorder{fill:none}.varwidthshadow{fill:none;stroke:#111827}
.labeltext18,.labeltext24{font-family:var(--sans);font-weight:700;font-size:17px;letter-spacing:.04em;fill:#3a3633;text-anchor:middle;
paint-order:stroke;stroke:#fffdf4;stroke-width:3px;stroke-linejoin:round}
.labeltext24{font-size:19px;fill:#4d5f74}
.gal{background:#f0c94a;padding:0 4px;border-radius:2px}
.centre-ring{fill:none;stroke:#80601f;stroke-width:6}
@media (max-width:900px){.caption{grid-template-columns:1fr;gap:4px;height:230px}.caption h2{font-size:19px}.caption ul{font-size:14px}
.stage{flex-direction:column;padding:10px 16px}.press{flex:0 0 40%}.cols,.split{grid-template-columns:1fr;gap:16px}
.text h2{font-size:28px}.text ul,.text ol{font-size:16px}.title h2{font-size:48px}.lede{font-size:21px}}
""" + "".join(
    ".p%d{color:var(--p%d)}.avatar.p%d,.dot.p%d,.p%d-bg{background:var(--p%d);color:#fffdf4}.%s{fill:var(--t%d);stroke:#5a5650;stroke-width:1}"
    ".unit%s{fill:var(--p%d);fill-opacity:.95}" % (n, n, n, n, n, n, power.lower(), n, power.lower(), n)
    for n, power in enumerate(POWERS, 1))

JS = """
const slides=[...document.querySelectorAll('.slide')];let i=0;
function show(n){i=Math.max(0,Math.min(slides.length-1,n));slides.forEach((s,k)=>s.classList.toggle('on',k===i));
document.getElementById('count').textContent=`${i+1} / ${slides.length}`;history.replaceState(null,'','#'+(i+1));}
document.getElementById('prev').onclick=()=>show(i-1);document.getElementById('next').onclick=()=>show(i+1);
document.querySelector('main').onclick=e=>{if(!e.target.closest('a,button,code'))show(i+1)};
document.addEventListener('keydown',e=>{if(['ArrowRight',' ','PageDown'].includes(e.key)){e.preventDefault();show(i+1)}
if(['ArrowLeft','PageUp'].includes(e.key)){e.preventDefault();show(i-1)}if(e.key==='Home')show(0);if(e.key==='End')show(slides.length-1)});
window.addEventListener('hashchange',()=>{const n=(parseInt(location.hash.slice(1))||1)-1;if(n!==i)show(n)});
show((parseInt(location.hash.slice(1))||1)-1);
"""


def page(eyebrow, title, slides):
    blocks = []
    for slide in slides:
        caption = ""
        if "title" in slide:
            caption = ('<div class="caption"><h2>%s</h2><ul>%s</ul></div>'
                       % (slide["title"], "".join("<li>%s</li>" % b for b in slide["bullets"])))
        blocks.append('<section class="slide"><div class="stage">%s</div>%s</section>' % (slide["stage"], caption))
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link href="https://fonts.googleapis.com/css2?family=Merriweather:wght@400;700&family=Merriweather+Sans:wght@400;600;700&display=swap" rel="stylesheet">
<style>{CSS}</style></head><body>
<header class="bar"><span class="eyebrow">{html.escape(eyebrow)}</span><h1>{html.escape(title)}</h1>
<span class="spacer"></span><span class="counter" id="count"></span>
<button id="prev" aria-label="Previous slide">← Prev</button><button id="next" class="primary" aria-label="Next slide">Next →</button></header>
<main>{"".join(blocks)}</main>
<script>{JS}</script></body></html>
"""


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    drawer = MapDrawer()
    decks = [
        ("how-to-play.html", "webDiplomacy", "How to play Diplomacy", how_to_play(drawer)),
        ("game-of-the-week.html", "Softmax Coworld", "webDiplomacy: Game of the Week", game_of_the_week(drawer)),
    ]
    for name, eyebrow, title, slides in decks:
        path = OUT / name
        path.write_text(page(eyebrow, title, slides))
        print(f"{path} ({len(slides)} slides, {path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
