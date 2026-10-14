/* One formatted hover card for every chart, map and planner on the page.
 *
 * Content is either plain text (newlines kept) or a breakdown object:
 *   {title, rows: [{label, value, display?, color?, active?}], total?, pie?, note?}
 * A breakdown renders as a table, and with `pie: true` also as a small pie of the rows' values.
 *
 * Marks opt in by carrying `data-tip` (text) or a `tip` property (object), or through
 * `deskTip.adopt(root)`, which turns SVG <title> children (Plot's `title` channel) into tips.
 * A title that starts with TIP_PREFIX holds a JSON breakdown object.
 */
(() => {
  const TIP_PREFIX = "\u0001tip:";
  const card = document.createElement("div");
  card.className = "tip-card"; card.setAttribute("role", "tooltip"); card.hidden = true;
  const ready = () => document.body.append(card);
  if (document.body) ready(); else document.addEventListener("DOMContentLoaded", ready);

  function cell(tag, text, className) {
    const node = document.createElement(tag); node.textContent = text;
    if (className) node.className = className; return node;
  }
  function pie(rows) {
    const size = 84, radius = size / 2, total = rows.reduce((sum, r) => sum + Math.max(0, r.value), 0);
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("width", size); svg.setAttribute("height", size);
    svg.setAttribute("viewBox", `${-radius} ${-radius} ${size} ${size}`); svg.setAttribute("aria-hidden", "true");
    let angle = -Math.PI / 2;
    for (const row of rows) {
      if (!(row.value > 0) || !total) continue;
      const sweep = 2 * Math.PI * row.value / total, end = angle + sweep, r = radius - 1;
      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      const [x0, y0, x1, y1] = [r * Math.cos(angle), r * Math.sin(angle), r * Math.cos(end), r * Math.sin(end)];
      // A single full slice cannot be drawn as one arc; a circle stands in.
      path.setAttribute("d", sweep >= 2 * Math.PI - 1e-6
        ? `M ${-r} 0 A ${r} ${r} 0 1 1 ${r} 0 A ${r} ${r} 0 1 1 ${-r} 0 Z`
        : `M 0 0 L ${x0} ${y0} A ${r} ${r} 0 ${sweep > Math.PI ? 1 : 0} 1 ${x1} ${y1} Z`);
      path.setAttribute("fill", row.color || "#7d97b6");
      path.setAttribute("stroke", "var(--bg, #fffdf4)"); path.setAttribute("stroke-width", row.active ? 0 : 1.5);
      if (row.active) path.setAttribute("transform", `translate(${3 * Math.cos(angle + sweep / 2)} ${3 * Math.sin(angle + sweep / 2)})`);
      svg.append(path); angle = end;
    }
    return svg;
  }
  function render(content) {
    card.replaceChildren();
    if (typeof content === "string") {
      const [first, ...rest] = content.split("\n");
      card.append(cell("p", first, "tip-title"));
      if (rest.length) card.append(cell("p", rest.join("\n"), "tip-body"));
      return;
    }
    if (content.title) card.append(cell("p", content.title, "tip-title"));
    const body = document.createElement("div"); body.className = "tip-breakdown";
    const rows = content.rows || [];
    if (content.pie && rows.some(r => r.value > 0)) body.append(pie(rows));
    if (rows.length) {
      const total = content.total ?? rows.reduce((sum, r) => sum + (Number.isFinite(r.value) ? r.value : 0), 0);
      const table = document.createElement("table");
      for (const row of rows) {
        const tr = document.createElement("tr"); if (row.active) tr.className = "active";
        const label = document.createElement("td");
        if (row.color) { const swatch = cell("span", "", "tip-swatch"); swatch.style.background = row.color; label.append(swatch); }
        label.append(document.createTextNode(row.label));
        const share = content.pie && total > 0 && Number.isFinite(row.value) ? `${(100 * row.value / total).toFixed(0)}%` : "";
        tr.append(label, cell("td", row.display ?? String(row.value), "num"), cell("td", share, "num share"));
        table.append(tr);
      }
      if (content.totalLabel !== null) {
        const tr = document.createElement("tr"); tr.className = "total";
        tr.append(cell("td", content.totalLabel || "Total"), cell("td", content.totalDisplay ?? String(total), "num"), cell("td", ""));
        table.append(tr);
      }
      body.append(table);
    }
    card.append(body);
    if (content.note) card.append(cell("p", content.note, "tip-body"));
  }
  function place(event) {
    const gap = 14, { innerWidth: w, innerHeight: h } = window, box = card.getBoundingClientRect();
    let x = event.clientX + gap, y = event.clientY + gap;
    if (x + box.width > w - 8) x = Math.max(8, event.clientX - gap - box.width);
    if (y + box.height > h - 8) y = Math.max(8, event.clientY - gap - box.height);
    card.style.left = `${x}px`; card.style.top = `${y}px`;
  }
  function show(event, content) {
    if (content === undefined || content === null || content === "") return hide();
    render(content); card.hidden = false; place(event);
  }
  function hide() { card.hidden = true; }
  function parse(text) {
    if (!text.startsWith(TIP_PREFIX)) return text;
    try { return JSON.parse(text.slice(TIP_PREFIX.length)); } catch { return text; }
  }
  // Plot writes the `title` channel as SVG <title>, which browsers show as a plain native tooltip.
  function adopt(root) {
    root.querySelectorAll("title").forEach(title => {
      const owner = title.parentElement;
      if (owner && owner.tagName.toLowerCase() !== "svg") {
        owner.tip = parse(title.textContent); owner.classList.add("has-tip"); title.remove();
      }
    });
  }
  function tipFor(target) {
    for (let node = target; node && node !== document; node = node.parentNode) {
      if (node.tip !== undefined) return node.tip;
      if (node.dataset?.tip) return parse(node.dataset.tip);
    }
    return undefined;
  }
  document.addEventListener("pointermove", event => {
    const content = tipFor(event.target);
    if (content === undefined) { if (!card.hidden) hide(); return; }
    show(event, content);
  });
  document.addEventListener("pointerleave", hide);
  document.addEventListener("scroll", hide, { passive: true, capture: true });
  // Encode a breakdown object for Plot's string-only `title` channel.
  const encode = content => TIP_PREFIX + JSON.stringify(content);
  window.deskTip = { show, hide, adopt, encode };
})();
