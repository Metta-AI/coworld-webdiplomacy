/* Tournament planner widget: controls, worker runs and the result views.
 *
 * Data comes from /tournament-data (cache only). The statistics run in
 * /static/tournament-worker.js; see that file for the model and format definitions.
 * Settings live in this module, so they survive the 60 s fragment refresh and a data refetch.
 */
(() => {
  const MODEL_COLORS = {A: "#2a78d6", B: "#eb6834"};  // first two of the validated `series` order in charts.js
  const MODEL_NAMES = {A: "Model A · player + power", B: "Model B · head-to-head"};
  const PRECISION = {quick: [40, 100, "Quick · 40 refits × 100 tournaments"],
                     standard: [100, 200, "Standard · 100 refits × 200 tournaments"],
                     thorough: [200, 300, "Thorough · 200 refits × 300 tournaments"]};
  const SEED = 20261014;
  const settings = {format: "rotation", cycles: 5, reshuffle: true, copies: 3, games: 200, toFixation: true,
                    precision: "standard", older: false, selected: null, league: null};

  function h(tag, attributes = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attributes)) {
      if (value === false || value === null || value === undefined) continue;
      if (key === "class") node.className = value;
      else if (key === "text") node.textContent = value;
      else if (key === "tip") node.tip = value;
      else node.setAttribute(key, value === true ? "" : value);
    }
    node.append(...children.flat().filter(c => c !== null && c !== undefined && c !== false));
    return node;
  }
  const pct = v => v === null || v === undefined ? "unknown" : v >= 0.995 && v < 1 ? ">99%"
    : v > 0 && v < 0.005 ? "<1%" : `${Math.round(100 * v)}%`;
  const num = (v, digits = 2) => v === null || v === undefined ? "unknown" : v.toFixed(digits);
  const money = v => v === null || v === undefined ? "unknown" : `$${v.toFixed(v < 10 ? 2 : 0)}`;
  const count = v => v === null ? "never" : v > 5000 ? "more than 5,000" : v.toLocaleString("en-US");
  const hours = minutes => minutes < 90 ? `${Math.round(minutes)} min` : `${(minutes / 60).toFixed(1)} h`;
  function clean(plot) { plot.querySelectorAll("style").forEach(style => style.remove()); return plot; }

  /* ---------- one planner per widget node ---------- */
  function mountAll() {
    document.querySelectorAll('[data-widget="tournament"]').forEach(node => {
      if (!node.planner) node.planner = createPlanner(node);
      else node.planner.resize();
    });
  }

  function createPlanner(node) {
    const state = {data: null, worker: null, runId: 0, timer: null, results: null, width: 0, src: node.dataset.src};
    node.replaceChildren(h("p", {class: "note", text: "Loading cached league games…"}));
    fetch(state.src, {cache: "no-store"})
      .then(response => { if (!response.ok) throw new Error(`HTTP ${response.status}`); return response.json(); })
      .then(data => {
        state.data = data;
        const league = data.league_id;
        const ids = new Set(data.players.map(p => p.player_id));
        if (settings.league !== league || !settings.selected || ![...settings.selected].every(id => ids.has(id)))
          settings.selected = new Set(data.players.filter(p => p.default).map(p => p.player_id));
        settings.league = league;
        build(); schedule(0);
      })
      .catch(error => node.replaceChildren(h("p", {class: "note bad", text: `Planner data unavailable: ${error.message}`})));

    let controls, status, bar, output;
    function build() {
      controls = h("form", {class: "tp-controls", "aria-label": "Tournament settings"});
      status = h("p", {class: "note tp-status", role: "status"});
      bar = h("progress", {class: "tp-progress", max: 1, value: 0});
      output = h("div", {class: "tp-output"});
      node.replaceChildren(controls, h("div", {class: "tp-run"}, bar, status), output);
      renderControls();
      controls.addEventListener("input", onChange);
      controls.addEventListener("change", onChange);
      controls.addEventListener("submit", event => event.preventDefault());
    }

    function onChange(event) {
      const target = event.target;
      if (target.name === "format") settings.format = target.value;
      else if (target.name === "cycles") settings.cycles = clamp(target.valueAsNumber, 1, 50, settings.cycles);
      else if (target.name === "reshuffle") settings.reshuffle = target.checked;
      else if (target.name === "copies") settings.copies = clamp(target.valueAsNumber, 1, 20, settings.copies);
      else if (target.name === "games") settings.games = clamp(target.valueAsNumber, 10, 2000, settings.games);
      else if (target.name === "fixation") settings.toFixation = target.checked;
      else if (target.name === "precision") settings.precision = target.value;
      else if (target.name === "older") settings.older = target.checked;
      else if (target.name === "player") {
        if (target.checked) settings.selected.add(target.value); else settings.selected.delete(target.value);
      } else return;
      if (event.type === "change" || target.type !== "number") renderControls();
      schedule(target.type === "number" ? 600 : 300);
    }
    function clamp(value, lo, hi, fallback) { return Number.isFinite(value) ? Math.min(hi, Math.max(lo, Math.round(value))) : fallback; }

    function renderControls() {
      const focused = document.activeElement && controls.contains(document.activeElement) ? document.activeElement.name + ":" + (document.activeElement.value || "") : null;
      const rotation = settings.format === "rotation";
      const radio = (value, label, hint) => h("label", {class: "tp-choice"},
        h("input", {type: "radio", name: "format", value, checked: settings.format === value}),
        h("span", {}, h("b", {text: label}), h("span", {class: "note", text: hint})));
      const format = h("fieldset", {class: "tp-format"}, h("legend", {text: "Format"}),
        radio("rotation", "Full-table rotation", "All 7 play every game; a cycle is 7 games in which each player plays each power once. Highest total score wins."),
        radio("evolution", "Evolutionary", "Start with copies of each player; each game seats 7 individuals. The top scorer's player gains a copy, the bottom scorer's loses one. Largest share wins."));
      const size = rotation
        ? h("fieldset", {}, h("legend", {text: "Size"}),
            h("label", {}, "Cycles ", h("input", {type: "number", name: "cycles", min: 1, max: 50, value: settings.cycles}),
              h("span", {class: "note", text: ` = ${7 * settings.cycles} games`})),
            h("label", {class: "tp-check"}, h("input", {type: "checkbox", name: "reshuffle", checked: settings.reshuffle}),
              " Reshuffle who sits next to whom each cycle"))
        : h("fieldset", {}, h("legend", {text: "Size"}),
            h("label", {}, "Copies per player ", h("input", {type: "number", name: "copies", min: 1, max: 20, value: settings.copies})),
            h("label", {class: "tp-check"}, h("input", {type: "checkbox", name: "fixation", checked: settings.toFixation}),
              " Run until one player is left"),
            settings.toFixation ? null : h("label", {}, "Games ", h("input", {type: "number", name: "games", min: 10, max: 2000, value: settings.games})));
      const precision = h("fieldset", {}, h("legend", {text: "Precision"}),
        h("select", {name: "precision", "aria-label": "Simulation precision"},
          Object.entries(PRECISION).map(([key, [, , label]]) => h("option", {value: key, selected: settings.precision === key, text: label}))),
        h("label", {class: "tp-check"}, h("input", {type: "checkbox", name: "older", checked: settings.older}),
          " Also learn from older policy versions"));
      const selectedCount = settings.selected.size;
      const players = h("fieldset", {class: "tp-players"},
        h("legend", {text: `Players · ${selectedCount} selected${rotation ? " (exactly 7 for a full table)" : ""}`}),
        h("div", {class: "tp-player-list"}, state.data.players.map(p => h("label", {class: "tp-player",
          tip: {title: p.player, rows: [
            {label: "Competing policy", value: 0, display: p.label},
            {label: "MMR", value: p.mmr ?? 0, display: p.mmr === null ? "unrated" : p.mmr.toFixed(2)},
            {label: "Scored games, this policy", value: p.games, display: String(p.games)},
            {label: "Scored games, any version", value: p.games_any_version, display: String(p.games_any_version)},
            {label: "LLM per seat-game", value: 0, display: seatCostLabel(p)}], totalLabel: null}},
          h("input", {type: "checkbox", name: "player", value: p.player_id, checked: settings.selected.has(p.player_id)}),
          h("span", {class: "tp-name", text: p.player}),
          h("span", {class: "note", text: `${p.mmr === null ? "unrated" : "MMR " + p.mmr.toFixed(1)} · ${p.games} games`})))));
      controls.replaceChildren(format, size, players, precision);
      if (focused) {
        const [name, value] = focused.split(":");
        const again = [...controls.elements].find(e => e.name === name && (e.type !== "checkbox" && e.type !== "radio" || e.value === value));
        again?.focus({preventScroll: true});
      }
    }
    function seatCostLabel(p) {
      const cost = championCost(p);
      return cost.usd === null ? "unknown (no covered seats)" : `${money(cost.usd)} over ${cost.seats} covered seats`;
    }
    function championCost(p) {
      const known = p.champion_ids.map(id => state.data.costs.seat_usd[id]).filter(Boolean);
      if (!known.length) return {usd: null, seats: 0};
      const seats = known.reduce((a, c) => a + c.seats, 0);
      return {usd: known.reduce((a, c) => a + c.usd * c.seats, 0) / seats, seats};
    }

    function chosenPlayers() { return state.data.players.filter(p => settings.selected.has(p.player_id)); }
    function problem() {
      const n = settings.selected.size;
      if (settings.format === "rotation" && n !== 7) return `Select exactly 7 players for a full table (${n} selected).`;
      if (settings.format === "evolution" && n < 2) return "Select at least 2 players.";
      if (settings.format === "evolution" && n * settings.copies < 7)
        return `The population needs at least 7 individuals to fill a table (${n} players × ${settings.copies} copies).`;
      if (!state.data.games.length) return "No scored league games are cached for this selection.";
      return null;
    }

    function schedule(delay) {
      clearTimeout(state.timer);
      state.timer = setTimeout(run, delay);
    }
    function run() {
      const issue = problem();
      if (issue) { state.worker?.terminate(); state.worker = null; bar.hidden = true; status.textContent = issue; output.replaceChildren(); return; }
      // A worker cannot be interrupted mid-run; replacing it cancels the stale run.
      state.worker?.terminate();
      state.worker = new Worker("/static/tournament-worker.js");
      const id = ++state.runId, [replicates, sims] = PRECISION[settings.precision];
      const players = chosenPlayers();
      const request = {format: settings.format, cycles: settings.cycles, reshuffle: settings.reshuffle,
                       copies: settings.copies, games: settings.games, toFixation: settings.toFixation,
                       replicates, sims, seed: SEED};
      const snapshot = {...request, players, older: settings.older};
      bar.hidden = false; bar.value = 0; status.textContent = "Fitting both models and simulating…";
      output.classList.add("tp-busy");
      state.worker.onmessage = event => {
        const message = event.data;
        if (message.id !== id) return;
        if (message.type === "progress") {
          bar.value = message.done / message.total;
          status.textContent = `Fitting and simulating: ${Math.round(100 * message.done / message.total)}% (${message.done} of ${message.total} refits)`;
          return;
        }
        state.worker.terminate(); state.worker = null;
        bar.hidden = true; output.classList.remove("tp-busy");
        state.results = {...message, settings: snapshot};
        status.textContent = `${replicates} refits × ${sims} simulated tournaments per model, on ${message.games} league games.`;
        render();
      };
      state.worker.onerror = event => { status.textContent = `Simulation failed: ${event.message}`; bar.hidden = true; };
      state.worker.postMessage({id, games: state.data.games, settings: request,
        chosen: players.map(p => ({player_id: p.player_id, policy_ids: settings.older ? p.policy_ids : p.champion_ids}))});
    }

    /* ---------- results ---------- */
    function render() {
      const {results, settings: used} = state.results, players = used.players, rotation = used.format === "rotation";
      state.width = output.clientWidth;
      const a = results.A, b = results.B;
      const favourite = r => r.players.reduce((best, p, i) => p.pWin > r.players[best].pWin ? i : best, 0);
      const fa = favourite(a), fb = favourite(b);
      const unit = rotation ? `${used.cycles}-cycle (${7 * used.cycles}-game) rotation`
        : used.toFixation ? `evolutionary run to one survivor (${used.copies} copies each)`
        : `${used.games}-game evolutionary run (${used.copies} copies each)`;
      const reading = h("p", {class: "reading tp-reading"},
        "In a simulated ", h("b", {text: unit}), ", model A picks ", h("b", {text: players[fa].player}),
        ` (wins ${pct(a.players[fa].pWin)}, plausible range ${pct(a.players[fa].pLow)}–${pct(a.players[fa].pHigh)}); model B picks `,
        h("b", {text: players[fb].player}),
        ` (wins ${pct(b.players[fb].pWin)}, range ${pct(b.players[fb].pLow)}–${pct(b.players[fb].pHigh)}).`);
      output.replaceChildren(reading, disagreement(a, b, players),
        h("div", {class: "tp-grid"},
          section("Who wins, and how sure", winChart(a, b, players), winNote(rotation)),
          section(rotation ? "Winning margin, 1st minus 2nd" : "Winning margin, leader's share minus runner-up's",
                  marginCharts(a, b, rotation), marginNote(a, b, rotation))),
        section("Expected result per player", standingsTable(a, b, players, rotation, used), null),
        h("div", {class: "tp-grid"},
          section(rotation ? "How many games are enough" : "How long until it is settled", curveChart(a, b, used, rotation),
                  curveNote(a, rotation)),
          section(rotation ? "Games needed to separate neighbours" : "Games until one player is left",
                  rotation ? needsTables(a, b, players) : fixationTable(a, b), rotation ? needsNote() : fixationNote(used))),
        section("Cost and time", costLines(used, a, b), null),
        fitDetails(a, b, used));
      output.querySelectorAll(".tp-chart").forEach(chart => deskTip.adopt(chart));
    }
    function section(title, body, note) {
      return h("section", {class: "tp-section"}, h("h4", {text: title}), body, note ? h("p", {class: "note", text: note}) : null);
    }
    function disagreement(a, b, players) {
      const rank = r => { const order = r.order; return Object.fromEntries(order.map((e, i) => [e, i + 1])); };
      const ra = rank(a), rb = rank(b);
      const notes = players.map((p, i) => {
        const gap = Math.abs(a.players[i].pWin - b.players[i].pWin), shift = Math.abs(ra[i] - rb[i]);
        if (gap >= 0.1) return `${p.player}: ${pct(a.players[i].pWin)} (A) against ${pct(b.players[i].pWin)} (B)`;
        if (shift >= 2) return `${p.player} ranks ${ra[i]} by A and ${rb[i]} by B`;
        return null;
      }).filter(Boolean);
      return h("p", {class: "note tp-disagree"}, h("b", {text: notes.length ? "Where the models disagree: " : "The models agree: "}),
        notes.length ? notes.join("; ") + ". " : "no win chance differs by 10 points or more and no strength rank moves by 2 or more. ",
        "A scores each seat directly (score share, adjusted for power); B only looks at finishing order, so it gives a narrow win the same credit as a solo.");
    }
    function winNote(rotation) {
      return "Dot: chance to win the tournament. Bar: 90% of refits on resampled league games fall here — how unsure the league data leave us about each player's strength (includes a little simulation noise)." +
        (rotation ? " Ties on total are split at random." : "");
    }
    function marginNote(a, b, rotation) {
      const fmt = v => rotation ? `${num(v)} points` : pct(v);
      return `Median margin: ${fmt(a.margin.median)} (A), ${fmt(b.margin.median)} (B). 90% of simulated tournaments fall between ${fmt(a.margin.low)} and ${fmt(a.margin.high)} (A), ${fmt(b.margin.low)} and ${fmt(b.margin.high)} (B).` +
        (rotation ? " Every game hands out 1 point in total." : "");
    }
    function curveNote(a, rotation) {
      return rotation
        ? `Statistical power, in one line: the chance the tournament gives a real answer. Solid: the strongest player (by each refit's own strengths) finishes first. Dashed: the winner's lead is clear — bigger than two equally strong players would reach 1 time in 20 (about ${num(1.645 * Math.sqrt(2 * 7) * a.sigma)} points per √cycle; seat-score noise σ = ${num(a.sigma, 3)}).`
        : "Solid: the strongest player (by each refit's own strengths) holds the largest share at that point. Dashed: the population has already narrowed to one player.";
    }
    function needsNote() {
      return "Neighbours in each model's strength order (point estimate). Assumes the estimated strengths are right, so it shows tournament luck only; a normal approximation from 3,000 simulated cycles, rounded up to whole cycles (7 games). \"Never\": the model sees no edge.";
    }
    function fixationNote(used) {
      return used.toFixation ? "Each simulated run continues until one player holds every place."
        : `Runs continue past ${used.games} games to measure the time to one survivor (up to ${Math.max(used.games, 3000).toLocaleString("en-US")} games).`;
    }

    function winChart(a, b, players) {
      const rows = [];
      players.forEach((p, i) => ["A", "B"].forEach(kind => {
        const r = (kind === "A" ? a : b).players[i];
        rows.push({player: p.player, model: kind, ...r, tip: deskTip.encode({title: `${p.player} · ${MODEL_NAMES[kind]}`, totalLabel: null, rows: [
          {label: "Chance to win (median refit)", value: r.pWin, display: pct(r.pWin), color: MODEL_COLORS[kind]},
          {label: "90% range across refits", value: 0, display: `${pct(r.pLow)} – ${pct(r.pHigh)}`},
          {label: "Fit on all games, no resampling", value: r.point, display: pct(r.point)}]})});
      }));
      // Rows by expected total across both models, so players with no realistic chance still read in order.
      const order = players.map((p, i) => [p.player, a.players[i].pWin + b.players[i].pWin + (a.players[i].total + b.players[i].total) / 1e6])
        .sort((x, y) => y[1] - x[1]).map(x => x[0]);
      const width = Math.max(260, output.clientWidth > 900 ? (output.clientWidth - 30) / 2 : output.clientWidth);
      const plot = Plot.plot({width, height: 34 * players.length + 46, marginLeft: 110, className: "desk-plot",
        x: {domain: [0, 1], label: "Chance to win the tournament", tickFormat: d => `${Math.round(d * 100)}%`, grid: true},
        y: {domain: order, label: null},
        // Plot's dy is a constant, so each model gets its own pair of marks, nudged apart.
        marks: [Plot.ruleX([0]), ...["A", "B"].flatMap(kind => {
          const own = rows.filter(d => d.model === kind), dy = kind === "A" ? -5 : 5;
          return [Plot.ruleY(own, {y: "player", x1: "pLow", x2: "pHigh", dy, stroke: MODEL_COLORS[kind], strokeWidth: 2}),
                  Plot.dot(own, {y: "player", x: "pWin", dy, fill: MODEL_COLORS[kind], r: 4.5,
                                 stroke: "#fffdf4", strokeWidth: 1.5, title: "tip"})];
        })]});
      return chartBox(clean(plot), true);
    }
    function marginCharts(a, b, rotation) {
      const full = output.clientWidth;
      const width = Math.max(220, full > 900 ? (full - 60) / 4 : full > 600 ? (full - 20) / 2 : full);
      const box = h("div", {class: "tp-multiples"});
      for (const [kind, r] of [["A", a], ["B", b]]) {
        const bins = r.margin.values.map(v => ({...v, tip: deskTip.encode({title: MODEL_NAMES[kind], totalLabel: null, rows: [
          {label: rotation ? "Margin, points" : "Margin, share", value: 0, display: `${num(v.x0)} – ${num(v.x1)}`},
          {label: "Share of simulated tournaments", value: v.share, display: pct(v.share), color: MODEL_COLORS[kind]}]})}));
        const plot = Plot.plot({width, height: 170, marginLeft: 40, className: "desk-plot",
          x: {label: rotation ? "Points ahead" : "Share ahead", tickFormat: rotation ? null : d => `${Math.round(d * 100)}%`},
          y: {label: "Tournaments", tickFormat: d => `${Math.round(d * 100)}%`, grid: true},
          marks: [Plot.rectY(bins, {x1: "x0", x2: "x1", y: "share", fill: MODEL_COLORS[kind], insetLeft: 1, insetRight: 1, title: "tip"}),
                  Plot.ruleY([0])]});
        box.append(h("figure", {class: "tp-figure"}, h("figcaption", {class: "note", text: MODEL_NAMES[kind]}), chartBox(clean(plot), false)));
      }
      box.prepend(legend());
      return box;
    }
    function curveChart(a, b, used, rotation) {
      const rows = [];
      for (const [kind, r] of [["A", a], ["B", b]]) for (const point of r.curve) {
        const second = rotation ? point.clear : point.fixed;
        for (const [metric, value] of [["strongest", point.strongest], ["second", second]]) {
          if (value === null) continue;
          rows.push({x: point.x, value, model: kind, metric, series: `${kind}:${metric}`,
            tip: deskTip.encode({title: `${point.x} games${point.cycles ? ` (${point.cycles} cycles)` : ""} · ${MODEL_NAMES[kind]}`, totalLabel: null, rows: [
              {label: rotation ? "Strongest finishes first" : "Strongest holds the largest share", value: point.strongest, display: pct(point.strongest), color: MODEL_COLORS[kind], active: metric === "strongest"},
              {label: rotation ? "First with a clear lead" : "Down to one player", value: second, display: pct(second), active: metric === "second"}]})});
        }
      }
      const chosen = rotation ? 7 * used.cycles : used.toFixation ? null : used.games;
      const width = Math.max(260, output.clientWidth > 900 ? (output.clientWidth - 30) / 2 : output.clientWidth);
      const plot = Plot.plot({width, height: 230, marginLeft: 44, className: "desk-plot",
        x: {label: "Games played", grid: false}, y: {domain: [0, 1], label: "Probability", tickFormat: d => `${Math.round(d * 100)}%`, grid: true},
        marks: [
          ...[0.8, 0.9, 0.95].map(q => Plot.ruleY([q], {stroke: "#d4c9b5", strokeDasharray: "2,3"})),
          chosen ? Plot.ruleX([chosen], {stroke: "#1a3875", strokeWidth: 1}) : null,
          chosen ? Plot.text([chosen], {x: d => d, frameAnchor: "top", text: () => "your plan", dy: -2, dx: 4, textAnchor: "start", fill: "#1a3875"}) : null,
          // strokeDasharray is a constant in Plot, so each model/metric line is its own mark.
          ...["A", "B"].flatMap(kind => ["strongest", "second"].map(metric => Plot.line(
            rows.filter(d => d.model === kind && d.metric === metric),
            {x: "x", y: "value", stroke: MODEL_COLORS[kind], strokeWidth: 2, strokeDasharray: metric === "second" ? "5,4" : null}))),
          ...["A", "B"].map(kind => Plot.dot(rows.filter(d => d.model === kind),
            {x: "x", y: "value", fill: MODEL_COLORS[kind], r: 3, title: "tip"}))].filter(Boolean)});
      const box = h("div", {});
      box.append(legend(rotation ? ["Strongest finishes first", "First with a clear lead"] : ["Strongest leads", "Down to one player"]),
                 chartBox(clean(plot), true));
      return box;
    }
    function legend(lines) {
      const items = [];
      for (const kind of ["A", "B"]) items.push(h("span", {}, swatch(MODEL_COLORS[kind], false), ` ${MODEL_NAMES[kind]}`));
      if (lines) lines.forEach((label, i) => items.push(h("span", {}, swatch("#555555", i === 1), ` ${label}`)));
      return h("p", {class: "chart-legend tp-legend"}, items);
    }
    function swatch(color, dashed) {
      const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.setAttribute("width", "18"); svg.setAttribute("height", "10"); svg.setAttribute("aria-hidden", "true");
      const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
      for (const [k, v] of Object.entries({x1: 1, x2: 17, y1: 5, y2: 5, stroke: color, "stroke-width": 3})) line.setAttribute(k, v);
      if (dashed) line.setAttribute("stroke-dasharray", "4,3");
      svg.append(line); return svg;
    }
    function chartBox(plot, wide) { return h("div", {class: `tp-chart${wide ? " tp-wide" : ""}`}, plot); }

    function standingsTable(a, b, players, rotation, used) {
      const head = rotation
        ? ["Player", "League data", "Per game (A)", "Rank A / B", "Win chance A", "Win chance B", "Final total A, 90% of tournaments", "Final total B, 90% of tournaments"]
        : ["Player", "League data", "Per game (A)", "Rank A / B", "Win chance A", "Win chance B", "Final share A, 90% of runs", "Final share B, 90% of runs"];
      const rank = r => Object.fromEntries(r.order.map((e, i) => [e, i + 1]));
      const ra = rank(a), rb = rank(b);
      const total = (r, i) => rotation ? `${num(r.players[i].total)} (${num(r.players[i].totalLow)}–${num(r.players[i].totalHigh)})`
        : `${pct(r.players[i].total)} (${pct(r.players[i].totalLow)}–${pct(r.players[i].totalHigh)})`;
      const rows = players.map((p, i) => h("tr", {},
        h("td", {}, h("b", {text: p.player}), h("br"), h("span", {class: "note", text: p.label})),
        h("td", {class: "num", text: `${used.older ? p.games_any_version : p.games} games`}),
        h("td", {class: "num", text: num(a.strength[i], 3)}),
        h("td", {class: "num", text: `${ra[i]} / ${rb[i]}`}),
        h("td", {class: "num", text: `${pct(a.players[i].pWin)} (${pct(a.players[i].pLow)}–${pct(a.players[i].pHigh)})`}),
        h("td", {class: "num", text: `${pct(b.players[i].pWin)} (${pct(b.players[i].pLow)}–${pct(b.players[i].pHigh)})`}),
        h("td", {class: "num", text: total(a, i)}), h("td", {class: "num", text: total(b, i)})));
      const note = rotation
        ? `Per game (A): expected score share at an average power; par is ${num(1 / 7, 3)}. A ${used.cycles}-cycle rotation hands out ${7 * used.cycles} points, so par total is ${num(used.cycles)}. Total ranges are luck inside one tournament, with strength uncertainty mixed in.`
        : "Per game (A): expected score share at an average power; par is 0.143. Final share: the player's share of the population at the end.";
      return h("div", {}, h("div", {class: "table-scroll"}, h("table", {class: "data"},
        h("thead", {}, h("tr", {}, head.map(c => h("th", {text: c})))), h("tbody", {}, rows))),
        h("p", {class: "note", text: note}));
    }
    function needsTables(a, b, players) {
      const box = h("div", {class: "tp-needs"});
      for (const [kind, r] of [["A", a], ["B", b]]) {
        const rows = r.pairs.map(pair => h("tr", {},
          h("td", {text: `${players[pair.better].player} over ${players[pair.worse].player}`}),
          h("td", {class: "num", text: num(pair.perCycle)}),
          ...[0.8, 0.9, 0.95].map(q => h("td", {class: "num", text: count(pair.need[q])}))));
        box.append(h("div", {class: "table-scroll"}, h("table", {class: "data"},
          h("caption", {class: "note"}, swatch(MODEL_COLORS[kind], false), ` ${MODEL_NAMES[kind]}`),
          h("thead", {}, h("tr", {}, ["Pair", "Edge per cycle, points", "80%", "90%", "95%"].map(c => h("th", {text: c})))),
          h("tbody", {}, rows))));
      }
      return box;
    }
    function fixationTable(a, b) {
      const rows = [["A", a], ["B", b]].map(([kind, r]) => h("tr", {},
        h("td", {}, swatch(MODEL_COLORS[kind], false), ` ${MODEL_NAMES[kind]}`),
        h("td", {class: "num", text: r.fixation.mean === null ? "not reached" : Math.round(r.fixation.mean).toLocaleString("en-US")}),
        h("td", {class: "num", text: r.fixation.low === null ? "—" : `${Math.round(r.fixation.low)}–${Math.round(r.fixation.high)}`}),
        h("td", {class: "num", text: `${r.fixation.fixed}/${r.fixation.runs}`})));
      return h("div", {class: "table-scroll"}, h("table", {class: "data"},
        h("thead", {}, h("tr", {}, ["Model", "Mean games", "90% of runs", "Runs that finished"].map(c => h("th", {text: c})))),
        h("tbody", {}, rows)));
    }

    function costLines(used, a, b) {
      const costs = state.data.costs, rotation = used.format === "rotation";
      const known = used.players.map(p => ({p, cost: championCost(p)}));
      const missing = known.filter(k => k.cost.usd === null).map(k => k.p.player);
      const seatSum = known.reduce((s, k) => s + (k.cost.usd ?? 0), 0);
      const games = rotation ? 7 * used.cycles
        : used.toFixation ? Math.round(((a.fixation.mean ?? 0) + (b.fixation.mean ?? 0)) / 2) : used.games;
      // Rotation: all 7 sit every game. Evolution: 7 seats from the population, equal shares at the start.
      const llmPerGame = rotation ? seatSum : 7 * seatSum / used.players.length;
      const compute = costs.compute_usd === null ? null : costs.compute_usd * games;
      const llm = llmPerGame * games;
      const lines = [];
      lines.push(h("p", {}, h("b", {text: `${games.toLocaleString("en-US")} games`}),
        rotation ? "" : used.toFixation ? " (mean time to one survivor, averaged across the two models)" : "",
        `: about ${money(compute === null ? null : compute + llm)} in total — compute ${money(compute)} (${money(costs.compute_usd)}/game over ${costs.compute_games} covered league games) plus LLM ${money(llm)} (${money(llmPerGame)}/game` +
        (missing.length ? `; unknown for ${missing.join(", ")}, counted as $0` : "") + ")."));
      const median = costs.median_minutes;
      if (median === null) lines.push(h("p", {text: "Wall-clock: unknown — no completed league games with play timestamps."}));
      else if (rotation) lines.push(h("p", {text: `Wall-clock: about ${hours(Math.ceil(games / costs.in_flight) * median)} with at most ${costs.in_flight} games in flight (${Math.ceil(games / costs.in_flight)} waves × median game ${Math.round(median)} min over ${costs.duration_games} games). The rotation's games are independent, so they can all run in parallel.`}));
      else lines.push(h("p", {text: `Wall-clock: about ${hours(games * median)} if games run one after another (each game changes the population the next one draws from), at a median ${Math.round(median)} min per game. Playing ${costs.in_flight} tables at a time from the same population would cut this to about ${hours(Math.ceil(games / costs.in_flight) * median)}, a small change to the process that this simulation does not model.`}));
      lines.push(h("p", {class: "note", text: "LLM spend is provider-billed USD per seat-game for each player's competing policy, from games created in the last seven days with covered seats; compute is the detail API's per-game figure. Launch overhead and failed-game retries are not included."}));
      return h("div", {class: "tp-cost"}, lines);
    }
    function fitDetails(a, b, used) {
      const fit = state.data.fit, powers = state.data.powers;
      const effects = (r, fmt) => powers.map((name, i) => `${name} ${fmt(r.effects[i])}`).join(", ");
      return h("details", {class: "tp-details"}, h("summary", {text: "How these numbers were made"}),
        h("p", {class: "note", text: `${fit.history}: ${fit.games} scored league games from ${fit.first} to ${fit.last}; ${fit.excluded} excluded for tainted results or score conflicts; ${fit.without_powers} without results facts are used with unknown powers. Every game's seven scores sum to 1 (largest deviation ${fit.score_sum_error === null ? "unknown" : fit.score_sum_error.toExponential(1)}).`}),
        h("p", {class: "note", text: `Each selected player is represented by ${used.older ? "every policy version they have played (older versions add data but may be weaker or stronger than today's)" : "their competing policy version only"}. Every other policy version, and every filler seat, is its own opponent in the fit, so the field's mixed strength is not averaged away.`}),
        h("p", {class: "note", text: `Model A fits score = player strength + power effect + noise by least squares (power effects sum to zero), and simulates a seat by adding a residual drawn from that player's own past games, clamping at 0 and rescaling the table to 1. Power effects, points per game: ${effects(a, v => (v >= 0 ? "+" : "") + v.toFixed(3))}.`}),
        h("p", {class: "note", text: `Model B fits Plackett–Luce finishing orders with worth = player worth × power worth (MM algorithm, Hunter 2004; ties broken at random in each refit; one virtual win and loss against a worth-1 reference keeps rarely seen players finite). It simulates an order, then hands out the sorted scores of a randomly drawn real game. Power worths: ${effects(b, v => v.toFixed(2))}.`}),
        h("p", {class: "note", text: "Uncertainty: each refit resamples league games with replacement and fits again; the ranges are the middle 90% of refits. Limits: league games are mixed fields, not this final seven; policies may play differently against each other or adapt; evolutionary clones are hypothetical, since no league game ever seated two copies of one policy."}));
    }

    function resize() {
      if (state.results && Math.abs(output.clientWidth - state.width) > 40) render();
    }
    return {resize};
  }

  window.deskWidgets = window.deskWidgets || {};
  window.deskWidgets.tournament = mountAll;
  let resizeTimer;
  window.addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(mountAll, 200); });
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mountAll); else mountAll();
})();
