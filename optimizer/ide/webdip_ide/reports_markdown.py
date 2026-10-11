"""A small, safe Markdown renderer for the lab's reports, and their front matter.

The reports are written by the agent in a fixed shape (the opponent-profile and
matchup-writeup skills give the template), so this covers what that shape uses and no
more: headings, paragraphs, bullet and numbered lists (nested by indentation), pipe
tables, fenced code, block quotes, rules, and inline code, bold, italic and links.

Safety: every piece of text is HTML-escaped before any tag is added, raw HTML in the
source is shown as text, and a link is only made for an in-app path (`/replays/...`),
an `http(s)` address or a `#fragment`. Anything else stays plain text. A bare IDE path
such as `/replays/<episode id>?phase=7` is linked even without `[text](...)`, so the
evidence lines of a report are clickable.

Not supported (shown as plain text): images, raw HTML, reference links, nested block
quotes, setext headings. If reports outgrow this, replace it with `markdown-it-py`
(raw HTML off) rather than growing it.
"""

from __future__ import annotations

import html
import re

IDE_PATH = r"/(?:replays|reports|dashboard|experiments)(?:[/?#][\w\-./?=&%#;:+~]*)?"
_LINK = re.compile(r"\[([^\[\]\n]+)\]\(([^)\s\x00]{1,2000})\)")  # no \x00: a code span is never part of an address
_KEPT = re.compile(r"\x00(\d+)\x00")
MAX_LIST_DEPTH = 12  # deeper items are shown at this depth
# A longer paragraph, cell or list item is shown as plain text, so the time the patterns above
# take on hostile text (thousands of unclosed `**`) stays small: about 0.1 s at this length.
MAX_INLINE = 20_000
_BARE_IDE_PATH = re.compile(r"(?<![\w/.\-;=])" + IDE_PATH)
_BOLD = re.compile(r"\*\*(?=\S)(.{1,2000}?)(?<=\S)\*\*")
_ITALIC = re.compile(r"(?<![\w*])\*(?=[^\s*])([^*\n]+?)(?<=[^\s*])\*(?![\w*])")
_UNDERSCORE_ITALIC = re.compile(r"(?<![\w_])_(?=[^\s_])([^_\n]+?)(?<=[^\s_])_(?![\w_])")
_CODE_SPAN = re.compile(r"(`+)(.+?)\1")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_BULLET = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
_TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
_RULE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
_FENCE = re.compile(r"^\s*(```+|~~~+)(.*)$")


def split_front_matter(text: str) -> tuple[dict[str, str], str]:
    """(`key: value` lines between the leading `---` fences, the rest of the document)."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    for end, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            break
    else:
        return {}, text
    meta = {}
    for line in lines[1:end]:
        key, colon, value = line.partition(":")
        if colon and key.strip():
            meta[key.strip().lower()] = value.strip().strip("\"'")
    return meta, "\n".join(lines[end + 1 :])


def safe_href(target: str) -> str | None:
    """The link target if it is one we allow, else None. `target` is raw (unescaped) text."""
    if target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    if target.startswith(("http://", "https://", "#")):
        return target
    return None


def _anchor(target: str, label_html: str, css_class: str = "") -> str:
    external = target.startswith("http")
    extra = ' target="_blank" rel="noopener noreferrer"' if external else ""
    extra += f' class="{css_class}"' if css_class else ""
    return f'<a href="{html.escape(target, quote=True)}"{extra}>{label_html}</a>'


def render_inline(text: str) -> str:
    """One run of text: escaped, then code spans, links, bold and italic."""
    if len(text) > MAX_INLINE:
        return html.escape(text.replace("\x00", ""), quote=False)
    kept: list[str] = []  # finished HTML pieces, swapped back in at the end
    out = _inline(text.replace("\x00", ""), kept)
    # A link's piece holds the marks of the pieces inside its label (always earlier ones), so
    # one pass per piece is the most it can take to swap them all.
    for _ in kept:
        if "\x00" not in out:
            break
        out = _KEPT.sub(lambda m: kept[int(m.group(1))], out)
    return out


def _inline(text: str, kept: list[str]) -> str:
    """`render_inline` for text with no `\x00` of its own; finished pieces go to `kept` behind marks."""

    def keep(piece: str) -> str:
        kept.append(piece)
        return f"\x00{len(kept) - 1}\x00"

    def code(match: re.Match) -> str:
        return keep(f"<code>{html.escape(match.group(2).strip())}</code>")

    def link(match: re.Match) -> str:
        target = safe_href(match.group(2))
        if target is None:
            return match.group(0)
        return keep(_anchor(target, _inline(match.group(1), kept)))

    text = _CODE_SPAN.sub(code, text)
    text = _LINK.sub(link, text)
    text = _BARE_IDE_PATH.sub(lambda m: keep(_anchor(m.group(0), html.escape(m.group(0)), "path")), text)
    out = html.escape(text, quote=False)
    out = out.replace("&lt;br&gt;", "<br>").replace("&lt;br /&gt;", "<br>").replace("&lt;br/&gt;", "<br>")
    out = _BOLD.sub(r"<strong>\1</strong>", out)
    out = _ITALIC.sub(r"<em>\1</em>", out)
    return _UNDERSCORE_ITALIC.sub(r"<em>\1</em>", out)


def _cells(line: str) -> list[str]:
    """Split one table row on unescaped pipes; code spans may hold pipes."""
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]
    cells, current, in_code = [], "", False
    for i, char in enumerate(line):
        if char == "`":
            in_code = not in_code
        if char == "|" and not in_code and (i == 0 or line[i - 1] != "\\"):
            cells.append(current)
            current = ""
        else:
            current += char
    cells.append(current)
    return [cell.strip().replace("\\|", "|") for cell in cells]


_NUMBER = re.compile(r"^[+\-−]?[\d.,]+%?(\s*[±/]\s*[\d.,]+%?)?(\s*SE)?\*?$")


def _table(header: str, rule: str, rows: list[str]) -> str:
    head = _cells(header)
    aligned_right = [cell.strip().endswith(":") and not cell.strip().startswith(":") for cell in _cells(rule)]
    body = [_cells(row) for row in rows]
    numeric = []
    for column in range(len(head)):
        values = [row[column] for row in body if column < len(row) and row[column] not in ("", "-")]
        declared = column < len(aligned_right) and aligned_right[column]
        numeric.append(declared or (bool(values) and all(_NUMBER.match(v) for v in values)))

    def row_html(cells: list[str], tag: str) -> str:
        out = []
        for column in range(len(head)):
            cell = cells[column] if column < len(cells) else ""
            cls = ' class="num"' if numeric[column] else ""
            out.append(f"<{tag}{cls}>{render_inline(cell)}</{tag}>")
        return "<tr>" + "".join(out) + "</tr>"

    return (
        '<div class="table-scroll"><table><thead>'
        + row_html(head, "th")
        + "</thead><tbody>"
        + "".join(row_html(row, "td") for row in body)
        + "</tbody></table></div>"
    )


def _list(lines: list[str]) -> str:
    """A run of list lines (already known to start with a marker) to nested <ul>/<ol>."""
    items: list[tuple[int, bool, list[str]]] = []  # (indent, ordered, text lines)
    for line in lines:
        match = _BULLET.match(line)
        if match:
            items.append((len(match.group(1).expandtabs(4)), match.group(2)[0].isdigit(), [match.group(3)]))
        elif items:
            items[-1][2].append(line.strip())
    # `build` calls itself once per level: cap the levels, so no document can exhaust the stack.
    levels = sorted({indent for indent, _, _ in items})[:MAX_LIST_DEPTH]
    items = [(min(indent, levels[-1]), ordered, text) for indent, ordered, text in items]

    def build(start: int, indent: int) -> tuple[str, int]:
        tag = "ol" if items[start][1] else "ul"
        out, i = [f"<{tag}>"], start
        while i < len(items) and items[i][0] >= indent:
            if items[i][0] > indent:
                nested, i = build(i, items[i][0])
                out[-1] = out[-1].removesuffix("</li>") + nested + "</li>"
                continue
            out.append(f"<li>{render_inline(' '.join(items[i][2]))}</li>")
            i += 1
        out.append(f"</{tag}>")
        return "".join(out), i

    html_out, i = "", 0
    while i < len(items):
        piece, i = build(i, items[i][0])
        html_out += piece
    return html_out


def render(text: str, drop_first_h1: bool = False) -> str:
    """Markdown to HTML. `drop_first_h1` leaves out a leading `# title` (the page shows the title)."""
    lines = text.replace("\x00", "").replace("\r\n", "\n").split("\n")
    out: list[str] = []
    seen_block = False
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        fence = _FENCE.match(line)
        if fence:
            marker = fence.group(1)
            body = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith(marker):
                body.append(lines[i])
                i += 1
            i += 1
            out.append(f"<pre><code>{html.escape(chr(10).join(body))}</code></pre>")
            seen_block = True
            continue
        heading = _HEADING.match(line)
        if heading:
            level = len(heading.group(1))
            if not (drop_first_h1 and level == 1 and not seen_block):
                out.append(f"<h{min(level, 4)}>{render_inline(heading.group(2))}</h{min(level, 4)}>")
            seen_block = True
            i += 1
            continue
        seen_block = True
        if "|" in line and i + 1 < len(lines) and _TABLE_RULE.match(lines[i + 1]) and "-" in lines[i + 1]:
            rows = []
            j = i + 2
            while j < len(lines) and lines[j].strip() and "|" in lines[j]:
                rows.append(lines[j])
                j += 1
            out.append(_table(line, lines[i + 1], rows))
            i = j
            continue
        if _RULE.match(line):
            out.append("<hr>")
            i += 1
            continue
        if line.lstrip().startswith(">"):
            quoted = []
            while i < len(lines) and lines[i].lstrip().startswith(">"):
                quoted.append(lines[i].lstrip()[1:].strip())
                i += 1
            out.append(f"<blockquote><p>{render_inline(' '.join(quoted))}</p></blockquote>")
            continue
        if _BULLET.match(line):
            block = []
            while i < len(lines) and lines[i].strip():
                if not _BULLET.match(lines[i]) and not lines[i].startswith((" ", "\t")):
                    break
                block.append(lines[i])
                i += 1
            out.append(_list(block))
            continue
        paragraph = []
        while i < len(lines) and lines[i].strip():
            if paragraph and (
                _HEADING.match(lines[i]) or _FENCE.match(lines[i]) or _BULLET.match(lines[i])
                or lines[i].lstrip().startswith(">")
            ):
                break
            paragraph.append(lines[i].strip())
            i += 1
        out.append(f"<p>{render_inline(' '.join(paragraph))}</p>")
    return "\n".join(out)


def first_heading(text: str) -> str | None:
    """The text of the first `# heading` in a document, for a report without a title."""
    for line in text.splitlines():
        match = _HEADING.match(line)
        if match and len(match.group(1)) == 1:
            return match.group(2)
    return None
