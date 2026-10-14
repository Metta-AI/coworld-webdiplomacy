/* The board: the optimizer IDE's Map tab on the desk. Numbers come from /board-map (board_map.py),
 * every phase at once, so the slider never asks the server; choosing a player refetches.
 *
 * The board image: map/classic-key.png paints every province one flat colour and
 * map/classic-points.json gives a point inside each. buildRegions fills outward from each point to
 * learn which pixel belongs to which province (as the IDE does); paint then colours pixels per view.
 *
 * refresh.js keeps a mounted widget while its data-src is unchanged and calls deskWidgets.boardMap
 * after every swap. A changed data-src arrives as a new, empty node: the view, phase and player live
 * in `ui` (module state), so the new node mounts with the user's choices.
 */
(() => {
  const W = 1300, H = 1000, DILATE_PASSES = 3, SEED_SEARCH = 14;
  const ui = {view: "contest", phase: "all", player: ""};
  const responses = new Map();  // url -> Promise of report
  let board = null;             // {regions, borders, keySea, keyPixels, centroids}, built once
  let assets = null;            // Promise of {points, image}

  const VIEWS = {
    contest: {title: "Contested provinces",
      phase: "How often a province was fought over in this phase: units of two or more powers moving in, or one moving in while another power's unit stays. Unopposed moves and one power's own bounces do not count.",
      all: "Share of all movement phases in which the province was fought over. Darker is fought over more often."},
    win: {title: "Win",
      phase: "Share of games in which each power had the most supply centres at the start of this phase; tied leaders split the win.",
      all: "Share of games each power won: the solo, else the top final score. Tied leaders split the win (two tied are ½ each)."},
    score: {title: "Mean score by power",
      phase: "Each power's mean score if the game had ended at the start of this phase: centres² over the sum of squares.",
      all: "Each power's mean final score. An even share is 1/7 = 0.143."},
    held: {title: "Who holds it",
      phase: "Each province in the colour of the power that held it most often at the start of this phase (a supply centre's owner, else the power whose unit stood there). Paler means less often.",
      all: "Each province in the colour of the power that held it most often over every phase. Paler means more contested ownership. Point at a province for the full split."},
  };

  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  };
  const cssVar = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const hexRgb = hex => { hex = hex.replace("#", ""); return [0, 2, 4].map(i => parseInt(hex.slice(i, i + 2), 16)); };
  const mix = (a, b, t) => a.map((v, i) => v + (b[i] - v) * t);
  const pct = x => `${(100 * x).toFixed(x < 0.1 && x > 0 ? 1 : 0)}%`;
  const fmt = x => x === null || x === undefined ? "–" : Number(x).toFixed(3);
  const powerHex = (report, id) => cssVar(`--power-${report.powers[id].toLowerCase()}`) || "#6b6560";

  // ---------- the board's provinces (once per page) ----------

  function loadAssets() {
    assets ||= Promise.all([
      fetch("/static/map/classic-points.json").then(r => r.json()).then(d => d.points),
      new Promise((resolve, reject) => {
        const image = new Image(); image.onload = () => resolve(image); image.onerror = reject;
        image.src = "/static/map/classic-key.png";
      }),
    ]).then(([points, image]) => ({points, image}));
    return assets;
  }

  function buildRegions({points, image}, provinces) {
    const canvas = document.createElement("canvas"); canvas.width = W; canvas.height = H;
    const ctx = canvas.getContext("2d", {willReadFrequently: true});
    ctx.drawImage(image, 0, 0);
    const px = ctx.getImageData(0, 0, W, H).data;
    // The key draws borders near-black and centre dots near-white; provinces use neither.
    const isLine = i => px[i * 4] < 5 && px[i * 4 + 1] < 5 && px[i * 4 + 2] < 5;
    const isDot = i => px[i * 4] > 235 && px[i * 4 + 1] > 235 && px[i * 4 + 2] > 235;
    const same = (a, b) => px[a * 4] === px[b * 4] && px[a * 4 + 1] === px[b * 4 + 1] && px[a * 4 + 2] === px[b * 4 + 2];
    const regions = new Int16Array(W * H).fill(-1);
    let keySea = null;
    const seedNear = (x, y) => {
      for (let r = 0; r <= SEED_SEARCH; r++) for (let dy = -r; dy <= r; dy++) for (let dx = -r; dx <= r; dx++) {
        if (Math.max(Math.abs(dx), Math.abs(dy)) !== r) continue;
        const sx = x + dx, sy = y + dy;
        if (sx < 0 || sy < 0 || sx >= W || sy >= H) continue;
        const i = sy * W + sx;
        if (!isLine(i) && !isDot(i)) return i;
      }
      return -1;
    };
    // Grow every province from its point at once, one ring at a time, through its own key colour, so
    // provinces sharing a colour (the seas) meet halfway rather than the first taking both.
    const queue = new Int32Array(W * H);
    let head = 0, tail = 0;
    for (const [id, info] of Object.entries(provinces)) {
      const at = points[info.name], start = at ? seedNear(at[0], at[1]) : -1;
      if (start < 0 || regions[start] !== -1) continue;
      if (!keySea && info.name === "North Sea") keySea = [px[start * 4], px[start * 4 + 1], px[start * 4 + 2]];
      regions[start] = Number(id); queue[tail++] = start;
    }
    while (head < tail) {
      const i = queue[head++], x = i % W;
      for (const j of [x > 0 ? i - 1 : -1, x < W - 1 ? i + 1 : -1, i - W, i + W]) {
        if (j >= 0 && j < W * H && regions[j] === -1 && same(i, j)) { regions[j] = regions[i]; queue[tail++] = j; }
      }
    }
    // Border lines and centre dots belong to no province in the key: give each to a neighbour.
    for (let pass = 0; pass < DILATE_PASSES; pass++) {
      const before = regions.slice();
      for (let i = 0; i < W * H; i++) {
        if (before[i] !== -1 || !(isLine(i) || isDot(i))) continue;
        const x = i % W;
        let n = x > 0 ? before[i - 1] : -1;
        if (n === -1 && x < W - 1) n = before[i + 1];
        if (n === -1 && i >= W) n = before[i - W];
        if (n === -1 && i < W * (H - 1)) n = before[i + W];
        if (n !== -1) regions[i] = n;
      }
    }
    const borders = new Uint8Array(W * H), sums = {}, sea = new Uint8Array(W * H);
    for (let j = 0; j < W * H; j++) {
      const here = regions[j], x = j % W;
      if ((x < W - 1 && regions[j + 1] !== here) || (j < W * (H - 1) && regions[j + W] !== here)) borders[j] = 1;
      if (keySea && px[j * 4] === keySea[0] && px[j * 4 + 1] === keySea[1] && px[j * 4 + 2] === keySea[2]) sea[j] = 1;
      if (here !== -1) { const s = sums[here] ||= {x: 0, y: 0, n: 0}; s.x += x; s.y += (j - x) / W; s.n += 1; }
    }
    const centroids = {};
    for (const [id, s] of Object.entries(sums)) centroids[id] = {x: s.x / s.n, y: s.y / s.n};
    return {regions, borders, sea, centroids};
  }

  // ---------- numbers for the current view and phase ----------

  const blocksOf = report => report.phases.concat([report.all]);
  function phaseIndex(report) {
    const blocks = blocksOf(report), i = blocks.findIndex(b => b.key === ui.phase);
    return i < 0 ? blocks.length - 1 : i;
  }
  const current = report => blocksOf(report)[phaseIndex(report)];
  // The darkest contest colour is the highest rate in any phase, so moving the slider compares like with like.
  function contestTop(report) {
    let top = 0;
    for (const b of blocksOf(report)) for (const [k, n] of Object.values(b.contest)) if (n) top = Math.max(top, k / n);
    return top || 1;
  }
  function leader(b, p) {
    const counts = b.held[p] || {};
    let best = null;
    for (const c of Object.keys(counts)) if (!best || counts[c] > counts[best]) best = c;
    return best ? {country: best, share: counts[best] / b.n} : null;
  }
  // The value painted for a power in the score and win views, and whether it has enough games.
  function powerValue(report, b, country) {
    const stat = ui.view === "win" ? b.win[country] : b.score[country];
    if (!stat) return null;
    return {value: ui.view === "win" ? stat.rate : stat.mean, n: stat.n, few: stat.n < report.minimum, stat};
  }

  // ---------- painting ----------

  function paint(state) {
    const {report, canvas} = state, ctx = canvas.getContext("2d"), image = ctx.createImageData(W, H), out = image.data;
    const land = hexRgb(cssVar("--map-land")), sea = hexRgb(cssVar("--map-sea")), off = hexRgb(cssVar("--border-subtle"));
    const ink = hexRgb(cssVar("--fg-muted")), navy = hexRgb(cssVar("--ink-navy"));
    const b = current(report), colours = {}, top = contestTop(report);
    const homeValues = {};
    if (ui.view === "score" || ui.view === "win") {
      const values = Object.keys(report.powers).map(c => powerValue(report, b, c)).filter(v => v && !v.few);
      const high = Math.max(0, ...values.map(v => v.value)) || 1;
      for (const c of Object.keys(report.powers)) {
        const v = powerValue(report, b, c);
        homeValues[c] = v && !v.few ? 0.12 + 0.6 * v.value / high : 0.06;
      }
    }
    for (const [p, info] of Object.entries(report.provinces)) {
      const c = board.centroids[p], base = c && board.sea[Math.round(c.y) * W + Math.round(c.x)] ? sea : land;
      if (ui.view === "contest") {
        const k = b.contest[p];
        colours[p] = mix(base, navy, k && k[1] ? 0.06 + 0.84 * (k[0] / k[1]) / top : 0);
      } else if (ui.view === "held") {
        const lead = leader(b, p);
        colours[p] = lead ? mix(base, hexRgb(powerHex(report, lead.country)), 0.15 + 0.75 * lead.share) : base;
      } else {
        colours[p] = info.home ? mix(base, hexRgb(powerHex(report, info.home)), homeValues[info.home]) : base;
      }
    }
    for (let i = 0; i < W * H; i++) {
      const r = board.regions[i], o = i * 4;
      let c = r === -1 ? (board.sea[i] ? sea : off) : colours[r] || land;
      if (board.borders[i]) c = mix(c, ink, 0.55);
      out[o] = c[0]; out[o + 1] = c[1]; out[o + 2] = c[2]; out[o + 3] = 255;
    }
    ctx.putImageData(image, 0, 0);
    labels(state, b);
  }

  function homeCentre(report, country) {
    let x = 0, y = 0, n = 0;
    for (const [p, info] of Object.entries(report.provinces)) {
      const c = board.centroids[p];
      if (String(info.home) === String(country) && info.supply && c) { x += c.x; y += c.y; n += 1; }
    }
    return n ? {x: x / n, y: y / n} : null;
  }

  // Score and win views: each power's number over its home centres. Under five games reads "few".
  function labels(state, b) {
    const {report, layer} = state;
    layer.replaceChildren();
    if (ui.view !== "score" && ui.view !== "win") return;
    for (const c of Object.keys(report.powers)) {
      const at = homeCentre(report, c), v = powerValue(report, b, c);
      if (!at || !v) continue;
      const label = el("div", `bm-power${v.few ? " few" : ""}`);
      label.style.left = `${100 * at.x / W}%`; label.style.top = `${100 * at.y / H}%`;
      label.append(el("span", "bm-power-name", report.powers[c]),
        el("span", "bm-power-value", `${ui.view === "win" ? pct(v.value) : fmt(v.value)} · ${v.n} g${v.few ? " · few" : ""}`));
      layer.append(label);
    }
  }

  // ---------- the side column ----------

  function table(head, rows) {
    const t = el("table", "data bm-table"), tr = el("tr");
    head.forEach(([text, num]) => tr.append(el("th", num ? "num" : "", text)));
    t.append(el("thead"), el("tbody")); t.tHead.append(tr);
    for (const {cells, className} of rows) {
      const row = el("tr", className || "");
      cells.forEach(([value, num]) => {
        const td = el("td", num ? "num" : "");
        if (value instanceof Node) td.append(value); else td.textContent = value;
        row.append(td);
      });
      t.tBodies[0].append(row);
    }
    return t;
  }
  function powerCell(report, c) {
    const span = el("span", "bm-who"), dot = el("span", "bm-dot");
    dot.style.background = powerHex(report, c);
    span.append(dot, document.createTextNode(report.powers[c]));
    return span;
  }

  function side(state) {
    const {report, parts} = state, b = current(report), view = VIEWS[ui.view];
    const who = report.player ? report.players.find(p => p.id === report.player) : null;
    parts.eyebrow.textContent = b.key === "all" ? "All phases" : b.label;
    parts.title.textContent = view.title;
    const perPower = ui.view === "score" || ui.view === "win";
    parts.about.textContent = (b.key === "all" ? view.all : view.phase) + (!who ? "" : perPower
      ? ` Only the powers ${who.name} played, in their games. Fewer than ${report.minimum} games reads "few".`
      : ` Only ${who.name}'s games.`);
    parts.legend.replaceChildren();
    let body;
    if (ui.view === "score" || ui.view === "win") {
      const win = ui.view === "win";
      const rows = Object.keys(report.powers).map(c => ({c, v: powerValue(report, b, c)})).filter(r => r.v)
        .sort((x, y) => (x.v.few - y.v.few) || y.v.value - x.v.value)
        .map(({c, v}) => ({className: v.few ? "dimrow" : "", cells: [[powerCell(report, c)],
          [win ? pct(v.value) : fmt(v.value), true],
          [win ? (b.key === "all" ? String(v.stat.solos) : "–") : fmt(v.stat.se), true],
          [`${v.n}${v.few ? " · few" : ""}`, true]]}));
      body = table([["Power"], [win ? "Win rate" : (b.key === "all" ? "Final score" : "If it ended here"), true],
        [win ? "Solos" : "± SE", true], ["Games", true]], rows);
    } else if (ui.view === "contest") {
      // Stepped swatches of the same mix paint() uses, from never fought over to the top rate.
      const top = contestTop(report), ramp = el("div", "bm-ramp"), steps = el("span", "bm-ramp-steps");
      const land = hexRgb(cssVar("--map-land")), navy = hexRgb(cssVar("--ink-navy"));
      for (let i = 0; i <= 5; i++) {
        const swatch = el("span"), c = mix(land, navy, i ? 0.06 + 0.84 * i / 5 : 0);
        swatch.style.background = `rgb(${c.map(Math.round).join(",")})`; steps.append(swatch);
      }
      ramp.append(el("span", "", "0%"), steps, el("span", "", pct(top)));
      parts.legend.append(ramp);
      const rows = Object.entries(b.contest).filter(([, k]) => k[0]).sort((x, y) => y[1][0] / y[1][1] - x[1][0] / x[1][1])
        .slice(0, 12).map(([p, [k, n]]) => ({cells: [[report.provinces[p].name], [pct(k / n), true], [`${k} of ${n}`, true]]}));
      body = table([["Most fought over"], ["Rate", true], [b.key === "all" ? "Game-phases" : "Games", true]], rows);
    } else {
      const key = el("div", "bm-key");
      Object.keys(report.powers).forEach(c => key.append(powerCell(report, c)));
      parts.legend.append(key);
      const rows = Object.keys(b.held).filter(p => report.provinces[p]?.supply).map(p => ({p, lead: leader(b, p)}))
        .filter(r => r.lead).sort((x, y) => x.lead.share - y.lead.share).slice(0, 12)
        .map(r => ({cells: [[report.provinces[r.p].name], [powerCell(report, r.lead.country)], [pct(r.lead.share), true]]}));
      body = table([["Least settled centres"], ["Most often"], ["Share", true]], rows);
    }
    parts.body.replaceChildren(body);
  }

  // ---------- pointing at a province (shared hover card, tooltip.js) ----------

  function tipFor(report, p) {
    const b = current(report), info = report.provinces[p];
    if (!info) return undefined;
    const name = info.name + (info.supply ? " · supply centre" : "");
    const unit = b.key === "all" ? "game-phases" : "games";
    if (ui.view === "contest") {
      const [k, n] = b.contest[p] || [0, b.n];
      return `${name}\n${pct(n ? k / n : 0)} fought over (${k} of ${n} ${unit})`;
    }
    if (ui.view === "held") {
      const counts = b.held[p] || {}, rows = Object.keys(counts).sort((x, y) => counts[y] - counts[x])
        .map(c => ({label: report.powers[c], value: counts[c], display: String(counts[c]), color: powerHex(report, c)}));
      const nobody = b.n - rows.reduce((sum, r) => sum + r.value, 0);
      if (nobody > 0) rows.push({label: "Nobody", value: nobody, display: String(nobody), color: cssVar("--border-strong")});
      return {title: name, rows, pie: true, totalLabel: b.key === "all" ? "Game-phases" : "Games", totalDisplay: String(b.n)};
    }
    if (!info.home) return `${name}\nNo home power`;
    const c = String(info.home), score = b.score[c], win = b.win[c];
    if (!score) return `${name}\n${report.powers[c]}: no games in this selection`;
    const rows = [
      {label: b.key === "all" ? "Mean final score" : "Score if it ended here", value: score.mean, display: `${fmt(score.mean)} ± ${fmt(score.se)}`},
      {label: b.key === "all" ? "Win rate" : "Leading on centres", value: win.rate, display: `${pct(win.rate)} (${win.wins.toFixed(1)})`},
      ...(b.key === "all" ? [{label: "Solos", value: win.solos, display: String(win.solos)}] : []),
      {label: "Games", value: score.n, display: String(score.n)},
    ];
    return {title: `${report.powers[c]} · ${info.name}`, rows, totalLabel: null,
      note: score.n < report.minimum ? `Fewer than ${report.minimum} games.` : undefined};
  }

  // ---------- one widget ----------

  function build(node) {
    node.replaceChildren();
    node.classList.add("board-map");
    const views = el("div", "seg"); views.setAttribute("role", "group"); views.setAttribute("aria-label", "Board view");
    for (const [key, view] of Object.entries(VIEWS)) {
      const button = el("button", "", view.title); button.type = "button"; button.dataset.view = key;
      views.append(button);
    }
    const playerLabel = el("label", "seglabel", "Player"), player = el("select");
    player.id = `board-map-player-${document.querySelectorAll(".board-map").length}`; playerLabel.htmlFor = player.id;
    const controls = el("div", "bm-controls");
    controls.append(views, el("span", "bm-player", ""));
    controls.lastChild.append(playerLabel, player);
    const figure = el("figure", "bm-board"), canvas = el("canvas");
    canvas.width = W; canvas.height = H; canvas.setAttribute("role", "img"); canvas.setAttribute("aria-label", "Map of Europe");
    const names = el("img", "bm-names"); names.src = "/static/map/classic-names.png"; names.alt = "";
    const layer = el("div", "bm-labels");
    figure.append(canvas, names, layer);
    const slider = el("input"); slider.type = "range"; slider.min = "0"; slider.step = "1";
    slider.id = `${player.id}-phase`; slider.setAttribute("aria-label", "Phase");
    const sliderLabel = el("label", "seglabel", "Phase"); sliderLabel.htmlFor = slider.id;
    const time = el("div", "bm-time"), phaseName = el("output", "bm-phase"), phaseCount = el("span", "note");
    // Ticks sit in the slider's own box so they line up with its positions.
    const ticks = el("div", "bm-ticks"), track = el("div", "bm-track"); ticks.setAttribute("aria-hidden", "true");
    track.append(slider, ticks);
    time.append(sliderLabel, track, phaseName, phaseCount);
    const column = el("div", "bm-col"); column.append(figure, time);
    const parts = {eyebrow: el("p", "eyebrow"), title: el("h4"), about: el("p", "note"), legend: el("div"), body: el("div")};
    const sideColumn = el("div", "bm-side"); sideColumn.append(...Object.values(parts));
    const body = el("div", "bm-body"); body.append(column, sideColumn); body.hidden = true;
    const status = el("p", "note bm-status", "Loading the board…");
    node.append(controls, body, status);
    const state = node.boardMap = {src: null, report: null, canvas, layer, parts, slider, phaseName, phaseCount,
      ticks, player, views, body, status};

    views.addEventListener("click", event => {
      const button = event.target.closest("button[data-view]");
      if (!button) return;
      ui.view = button.dataset.view; redraw(state);
    });
    slider.addEventListener("input", () => { ui.phase = blocksOf(state.report)[Number(slider.value)].key; redraw(state); });
    player.addEventListener("change", () => { ui.player = player.value; load(node); });
    canvas.addEventListener("pointermove", event => {
      if (!state.report || !board) return;
      const rect = canvas.getBoundingClientRect();
      const x = Math.floor((event.clientX - rect.left) / rect.width * W), y = Math.floor((event.clientY - rect.top) / rect.height * H);
      const p = x >= 0 && y >= 0 && x < W && y < H ? board.regions[y * W + x] : -1;
      // tooltip.js shows the `tip` of the element under the pointer on the same pointermove.
      canvas.tip = p === -1 ? undefined : tipFor(state.report, String(p));
    });
    canvas.addEventListener("pointerleave", () => { canvas.tip = undefined; window.deskTip?.hide(); });
  }

  function fillPlayers(state) {
    const {report, player} = state, all = el("option", "", "All players"); all.value = "";
    player.replaceChildren(all, ...report.players.map(p => {
      const option = el("option", "", `${p.name} · ${p.games} games`); option.value = p.id; return option;
    }));
    player.value = report.player;
  }

  function setupSlider(state) {
    const blocks = blocksOf(state.report);
    state.slider.max = String(blocks.length - 1);
    state.ticks.replaceChildren();
    blocks.forEach((b, i) => {
      if (b.key !== "all" && !(b.key[0] === "S" && (i === 0 || Number(b.key.slice(1)) % 2 === 1))) return;
      const tick = el("span", "", b.key === "all" ? "All" : b.key.slice(1));
      tick.style.left = `${100 * i / Math.max(1, blocks.length - 1)}%`;
      state.ticks.append(tick);
    });
  }

  function redraw(state) {
    const {report} = state, b = current(report);
    state.slider.value = String(phaseIndex(report));
    state.phaseName.textContent = b.key === "all" ? "All phases" : b.label;
    state.phaseCount.textContent = b.key === "all" ? `${b.games} games · ${b.n} game-phases` : `${b.n} games reached it`;
    state.views.querySelectorAll("button").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.view === ui.view)));
    state.body.dataset.view = ui.view;
    paint(state); side(state);
  }

  function url(node) {
    return ui.player ? `${node.dataset.src}&player=${encodeURIComponent(ui.player)}` : node.dataset.src;
  }
  function fetchReport(address) {
    if (!responses.has(address)) {
      responses.set(address, fetch(address, {cache: "no-store"}).then(response => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      }));
      responses.get(address).catch(() => responses.delete(address));
    }
    return responses.get(address);
  }

  function load(node) {
    const state = node.boardMap, address = url(node);
    state.src = node.dataset.src;
    Promise.all([fetchReport(address), loadAssets()]).then(([report, loaded]) => {
      if (url(node) !== address) return;  // a newer choice is loading
      // A player who left this selection falls back to all players.
      if (report.player && !report.players.some(p => p.id === report.player)) { ui.player = ""; load(node); return; }
      state.report = report;
      fillPlayers(state);
      const who = report.players.find(p => p.id === report.player);
      state.status.textContent = `${report.games} scored games${who ? ` with ${who.name}` : ""}`
        + (report.pending ? ` · ${report.pending} more await a parsed replay` : "") + ".";
      if (!report.games) { state.body.hidden = true; return; }
      board ||= buildRegions(loaded, report.provinces);
      state.body.hidden = false;
      setupSlider(state); redraw(state);
    }).catch(error => { state.status.textContent = `The board could not be loaded (${error.message}); cached page data is unaffected.`; });
  }

  function mountAll() {
    document.querySelectorAll('[data-widget="board-map"]').forEach(node => {
      if (!node.boardMap) build(node);
      if (node.boardMap.src !== node.dataset.src) {
        // New page data (more games, or another selection): drop cached player reports for the old URL.
        if (node.boardMap.src) [...responses.keys()].filter(k => k.startsWith(node.boardMap.src)).forEach(k => responses.delete(k));
        load(node);
      }
    });
  }

  window.deskWidgets = window.deskWidgets || {};
  window.deskWidgets.boardMap = mountAll;
  mountAll();
})();
