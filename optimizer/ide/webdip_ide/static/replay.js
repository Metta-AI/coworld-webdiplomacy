// The replay viewer (templates/replays_view.html).
//
// One fetch of GET /api/replays/<episode>?seat=S gives everything: phases (units, owners,
// adjudicated orders), province coordinates, press, our policy's decision lines, the press
// audit and the notes. Everything else is drawing. The board shown for a phase is the
// position at its start with that phase's orders on top, so "what was ordered from here,
// and did it work" is one picture.
//
// Sections: helpers · state · map · orders · timeline · press and audit · decision ·
//           notes · talking to the agent · moving through the game · loading
(function () {
  "use strict";

  var root = document.getElementById("replay");
  if (!root) return;
  var EPISODE = root.dataset.episode;
  var SVG = "http://www.w3.org/2000/svg";
  var POWER_ORDER = ["England", "France", "Italy", "Germany", "Austria", "Turkey", "Russia"];
  var NOTE_MARKS = { blunder: "bad", "bad-trust": "bad", "missed-alliance": "warn", good: "ok" };
  var AUDIT_POLL_MS = 15000;

  // ---------- helpers ----------

  function $(id) { return document.getElementById(id); }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function svg(tag, attrs, title) {
    var node = document.createElementNS(SVG, tag);
    for (var key in attrs) node.setAttribute(key, attrs[key]);
    if (title) {
      var label = document.createElementNS(SVG, "title");
      label.textContent = title;
      node.appendChild(label);
    }
    return node;
  }

  function clear(node) { node.replaceChildren(); return node; }

  function powerColor(name) {
    var value = getComputedStyle(document.documentElement).getPropertyValue("--power-" + String(name).toLowerCase());
    return value.trim() || "#6b6560";
  }

  function dot(name) {
    var node = el("span", "dot");
    node.style.background = powerColor(name);
    return node;
  }

  function title(text) { return text.charAt(0) + text.slice(1).toLowerCase(); }  // "TURKEY" -> "Turkey"

  function fmt(score) { return Number(score).toFixed(3); }

  // ---------- state ----------

  var view = null;          // the API payload
  var current = 0;          // phase index
  var seat = root.dataset.seat === "" ? null : Number(root.dataset.seat);
  var playing = null;       // interval id while playing
  var pressShow = "all";
  var colors = {};          // country id -> colour
  var names = {};           // country id -> power name
  var auditTimer = null;

  function phase() { return view.phases[current]; }
  function terr(id) { return view.territories[id]; }
  function abbr(id) { var t = terr(id); return t ? t.abbr : "?"; }
  function hasMap() {
    return Object.keys(view.territories).some(function (id) { return view.territories[id].x !== null; });
  }
  function seatRow() { return view.seats.find(function (s) { return s.slot === view.seat; }) || null; }
  function isUs(name) { return view.our_power && String(name).toUpperCase() === view.our_power; }

  // ---------- map ----------

  function point(id) {
    var t = terr(id);
    return t && t.x !== null ? { x: t.x, y: t.y } : null;
  }

  // The part of the segment a-b that starts `fromGap` after a and ends `toGap` before b.
  function trimmed(a, b, fromGap, toGap) {
    var dx = b.x - a.x, dy = b.y - a.y, length = Math.hypot(dx, dy) || 1;
    return {
      x1: a.x + dx * fromGap / length, y1: a.y + dy * fromGap / length,
      x2: b.x - dx * toGap / length, y2: b.y - dy * toGap / length,
    };
  }

  function along(a, b, share) { return { x: a.x + (b.x - a.x) * share, y: a.y + (b.y - a.y) * share }; }

  function cross(at, size, className, label) {
    var d = "M" + (at.x - size) + " " + (at.y - size) + " L" + (at.x + size) + " " + (at.y + size) +
            " M" + (at.x - size) + " " + (at.y + size) + " L" + (at.x + size) + " " + (at.y - size);
    return svg("path", { d: d, class: className }, label);
  }

  function buildDefs() {
    var defs = clear($("map-defs"));
    Object.keys(colors).forEach(function (country) {
      var marker = svg("marker", {
        id: "head-" + country, viewBox: "0 0 8 8", refX: "6.4", refY: "4", markerWidth: "4.6", markerHeight: "4.6",
        orient: "auto-start-reverse",
      });
      marker.appendChild(svg("path", { d: "M0.5 0.8 L7.5 4 L0.5 7.2 Z", fill: colors[country] }));
      defs.appendChild(marker);
    });
  }

  function orderText(order) {
    var unit = order.t + " " + abbr(order.at);
    switch (order.type) {
      case "Hold": return unit + " holds";
      case "Move": return unit + " → " + abbr(order.to) + (order.convoy ? " by convoy" : "");
      case "Support hold": return unit + " supports " + abbr(order.to);
      case "Support move": return unit + " supports " + abbr(order.from) + " → " + abbr(order.to);
      case "Convoy": return unit + " convoys " + abbr(order.from) + " → " + abbr(order.to);
      case "Retreat": return unit + " retreats → " + abbr(order.to);
      case "Disband": return unit + " disbands";
      case "Destroy": return unit + " is removed";
      case "Build Army": return "builds A " + abbr(order.at);
      case "Build Fleet": return "builds F " + abbr(order.at);
      default: return unit + " " + order.type.toLowerCase();
    }
  }

  // Did the order do what it said? A hold has no result of its own.
  function orderResult(order, phaseName) {
    if (order.dis) return "dislodged";
    if (order.type === "Hold") return "";
    if (phaseName === "Builds" || phaseName === "Retreats") return order.ok ? "" : "failed";
    return order.ok ? "" : "failed";
  }

  function unitShape(unit, at, extraClass) {
    var color = colors[unit.c] || "#6b6560";
    var group = svg("g", { class: "unit" + (extraClass ? " " + extraClass : "") });
    if (unit.t === "F") {
      group.appendChild(svg("rect", { x: at.x - 8, y: at.y - 5.5, width: 16, height: 11, rx: 5.5, fill: color }));
    } else {
      group.appendChild(svg("rect", { x: at.x - 6.5, y: at.y - 6.5, width: 13, height: 13, rx: 2, fill: color }));
    }
    var letter = svg("text", { x: at.x, y: at.y + 0.4 });
    letter.textContent = unit.t;
    group.appendChild(letter);
    return group;
  }

  function drawOrder(layer, marks, order, index, ph) {
    var from = point(order.at);
    if (!from) return;
    var color = colors[order.c] || "#6b6560";
    var failed = orderResult(order, ph.phase) === "failed";
    var label = names[order.c] + ": " + orderText(order) + (failed ? " (failed)" : order.dis ? " (dislodged)" : "");
    var group = svg("g", { class: "order" + (failed ? " failed" : ""), "data-order": index });
    var to = order.to ? point(order.to) : null;

    if ((order.type === "Move" || order.type === "Retreat") && to) {
      var line = trimmed(from, to, 8, 9);
      group.appendChild(svg("line", { x1: line.x1, y1: line.y1, x2: line.x2, y2: line.y2, class: "casing" }));
      group.appendChild(svg("line", {
        x1: line.x1, y1: line.y1, x2: line.x2, y2: line.y2, stroke: color,
        class: "move" + (order.type === "Retreat" ? " retreat" : ""), "marker-end": "url(#head-" + order.c + ")",
      }, label));
      if (failed) marks.appendChild(cross(along(from, to, 0.62), 3, "fail-cross", label));
    } else if ((order.type === "Support move" || order.type === "Convoy") && to && order.from && point(order.from)) {
      // Points at the move it helps: 60% of the way along it.
      var target = along(point(order.from), to, 0.6);
      var helper = trimmed(from, target, 8, 2);
      group.appendChild(svg("line", { x1: helper.x1, y1: helper.y1, x2: helper.x2, y2: helper.y2, class: "casing thin" }));
      group.appendChild(svg("line", {
        x1: helper.x1, y1: helper.y1, x2: helper.x2, y2: helper.y2, stroke: color,
        class: order.type === "Convoy" ? "convoy" : "support",
      }, label));
      if (order.type === "Convoy") {
        group.appendChild(svg("rect", { x: target.x - 2.4, y: target.y - 2.4, width: 4.8, height: 4.8, fill: color, class: "end" }));
      } else {
        group.appendChild(svg("circle", { cx: target.x, cy: target.y, r: 2.6, fill: color, class: "end" }));
      }
      if (failed) marks.appendChild(cross(along(from, target, 0.5), 2.6, "fail-cross", label));
    } else if (order.type === "Support hold" && to) {
      var hold = trimmed(from, to, 8, 10);
      group.appendChild(svg("line", { x1: hold.x1, y1: hold.y1, x2: hold.x2, y2: hold.y2, class: "casing thin" }));
      group.appendChild(svg("line", { x1: hold.x1, y1: hold.y1, x2: hold.x2, y2: hold.y2, stroke: color, class: "support" }, label));
      group.appendChild(svg("circle", { cx: to.x, cy: to.y, r: 10, stroke: color, class: "hold-ring" }));
      if (failed) marks.appendChild(cross(along(from, to, 0.5), 2.6, "fail-cross", label));
    } else if (order.type === "Build Army" || order.type === "Build Fleet") {
      var built = unitShape({ c: order.c, t: order.type === "Build Fleet" ? "F" : "A" }, from, "built" + (failed ? " not-built" : ""));
      built.appendChild(svg("title", {}));
      built.lastChild.textContent = label;
      marks.appendChild(built);
      var plus = svg("text", { x: from.x + 9, y: from.y - 6, class: "build-plus", fill: color });
      plus.textContent = "+";
      marks.appendChild(plus);
    } else if (order.type === "Destroy" || order.type === "Disband") {
      marks.appendChild(cross(order.type === "Disband" ? { x: from.x + 7, y: from.y - 7 } : from, 6, "removed", label));
    }
    if (group.childNodes.length) layer.appendChild(group);
  }

  function drawMap() {
    var ph = phase();
    var owners = clear($("layer-owners")), ordersLayer = clear($("layer-orders"));
    var units = clear($("layer-units")), marks = clear($("layer-marks")), hits = clear($("layer-hits"));
    root.classList.toggle("no-map", !hasMap());
    if (!hasMap()) return;

    // Ownership: a ring in the owner's colour on every supply centre.
    Object.keys(view.territories).forEach(function (id) {
      var t = terr(id), at = point(id);
      if (!at || t.parent !== Number(id)) return;
      var owner = ph.owners[id];
      if (t.supply) {
        owners.appendChild(svg("circle", {
          cx: at.x, cy: at.y, r: 9.5, class: "centre" + (owner ? "" : " neutral"),
          fill: owner ? colors[owner] : "none", stroke: owner ? colors[owner] : "#6b6560",
        }));
      }
    });

    ph.orders.forEach(function (order, index) { drawOrder(ordersLayer, marks, order, index, ph); });

    var dislodged = {};
    ph.orders.forEach(function (order) { if (order.dis) dislodged[order.at] = true; });
    // Retreating units are drawn last and to one side, so the unit that took the province does not hide them.
    ph.units.slice().sort(function (a, b) { return Number(a.r) - Number(b.r); }).forEach(function (unit) {
      var at = point(unit.at);
      if (!at) return;
      if (unit.r) at = { x: at.x + 7, y: at.y - 7 };
      var label = names[unit.c] + " " + (unit.t === "F" ? "fleet" : "army") + " in " + terr(unit.at).name +
        (unit.r ? " (dislodged, must retreat)" : dislodged[unit.at] ? " (dislodged this phase)" : "");
      var shape = unitShape(unit, at, unit.r ? "retreating" : "");
      shape.appendChild(svg("title", {}));
      shape.lastChild.textContent = label;
      units.appendChild(shape);
      if (dislodged[unit.at] && !unit.r) marks.appendChild(svg("circle", { cx: at.x, cy: at.y, r: 10.5, class: "dislodged" }, label));
    });

    // One click target per province: fills in the note form.
    var unitAt = {};
    ph.units.forEach(function (unit) { unitAt[unit.at] = unit; });
    Object.keys(view.territories).forEach(function (id) {
      var at = point(id), t = terr(id);
      if (!at) return;
      var unit = unitAt[id];
      var target = svg("circle", { cx: at.x, cy: at.y, r: 10, class: "hit", tabindex: "-1" },
        t.name + (unit ? ": " + names[unit.c] + " " + (unit.t === "F" ? "fleet" : "army") : "") +
        (ph.owners[t.parent] ? " · owned by " + names[ph.owners[t.parent]] : ""));
      target.addEventListener("click", function () { pinNote(t, unit ? names[unit.c] : ""); });
      hits.appendChild(target);
    });
  }

  function mapNote() {
    var ph = phase(), note = "";
    if (ph.stale_board) {
      note = "The record of the last phase shows who owned what before the final autumn. The centre counts in the chart and the table are the final ones.";
    } else if (ph.phase === "Diplomacy") {
      note = "Units where they stood before this phase's orders were carried out.";
    } else if (ph.phase === "Retreats") {
      note = "After the moves: dislodged units stand to one side and retreat or disband.";
    } else if (ph.phase === "Builds") {
      note = "After the autumn: units outlined with a + were built, crossed-out units were removed.";
    }
    $("map-note").textContent = note;
  }

  // ---------- orders ----------

  function drawOrders() {
    var ph = phase(), box = clear($("orders"));
    $("orders-phase").textContent = "· " + ph.label;
    var previous = current > 0 ? view.phases[current - 1].sc : null;
    var byCountry = {};
    ph.orders.forEach(function (order, index) { (byCountry[order.c] = byCountry[order.c] || []).push([order, index]); });
    var seats = {};
    view.seats.forEach(function (s) { seats[s.country] = s; });

    POWER_ORDER.forEach(function (name) {
      var country = Object.keys(names).find(function (c) { return names[c] === name; });
      if (!country) return;
      var block = el("div", "power-block" + (isUs(name) ? " us" : ""));
      var head = el("div", "power-head");
      head.appendChild(dot(name));
      head.appendChild(el("span", "power-name", name));
      var count = ph.sc[country] || 0;
      var centres = el("span", "num power-sc", count + " SC");
      if (previous) {
        var change = count - (previous[country] || 0);
        if (change) centres.appendChild(el("span", change > 0 ? "good" : "bad", " " + (change > 0 ? "+" : "−") + Math.abs(change)));
      }
      centres.title = "Supply centres owned in this phase" + (previous ? ", and the change since the phase before" : "");
      head.appendChild(centres);
      block.appendChild(head);
      var s = seats[country];
      if (s) {
        block.appendChild(el("div", "power-policy muted", s.policy + (isUs(name) ? " · followed" : "") +
          " · final " + fmt(s.score)));
      }
      var list = el("ul", "order-list");
      (byCountry[country] || []).forEach(function (pair) {
        var order = pair[0], result = orderResult(order, ph.phase);
        var item = el("li", result === "failed" ? "failed" : result === "dislodged" ? "dislodged" : "");
        item.appendChild(el("span", "mono", orderText(order)));
        if (result) item.appendChild(el("span", "result", result));
        item.addEventListener("mouseenter", function () { highlightOrder(pair[1], true); });
        item.addEventListener("mouseleave", function () { highlightOrder(pair[1], false); });
        list.appendChild(item);
      });
      if (!list.childNodes.length) {
        list.appendChild(el("li", "muted none", count || ph.units.some(function (u) { return String(u.c) === country; })
          ? "no orders in this phase" : "eliminated"));
      }
      block.appendChild(list);
      box.appendChild(block);
    });
  }

  function highlightOrder(index, on) {
    var node = document.querySelector('#layer-orders [data-order="' + index + '"]');
    $("layer-orders").classList.toggle("dim", on && !!node);
    if (node) node.classList.toggle("lit", on);
  }

  // ---------- timeline ----------

  var TL = { left: 46, right: 12, top: 8, chart: 120, rows: ["Board", "Press", "Notes"], row: 15 };

  function timelineX(width, index) {
    var n = view.phases.length;
    return TL.left + (n > 1 ? index * (width - TL.left - TL.right) / (n - 1) : 0);
  }

  function markersByRow() {
    var rows = { Board: [], Press: [], Notes: [] };
    view.events.forEach(function (event) {
      if (event.pi === null || event.pi === undefined) return;
      var board = event.kind === "eliminated" || event.kind === "swing";
      rows[board ? "Board" : "Press"].push({
        pi: event.pi, text: event.text, color: board ? powerColor(event.power) : null,
        shape: event.kind === "eliminated" ? "cross" : board ? "bar" : "diamond",
        tone: board ? "" : event.kind === "doubted_wrongly" ? "warn" : event.kind === "we_broke_our_word" ? "hollow" : "bad",
      });
    });
    view.annotations.forEach(function (note) {
      if (note.phase === null || note.phase === undefined) return;
      rows.Notes.push({
        pi: note.phase, text: "[" + note.tag + "] " + note.text, shape: note.author === "agent" ? "square" : "circle",
        tone: NOTE_MARKS[note.tag] || "", note: note.id,
      });
    });
    return rows;
  }

  function drawTimeline() {
    var box = $("timeline");
    var width = Math.max(480, box.clientWidth || 900);
    var height = TL.top + TL.chart + 16 + TL.rows.length * TL.row + 4;
    var chart = svg("svg", { viewBox: "0 0 " + width + " " + height, width: width, height: height, class: "timeline-svg" });
    // The scale fits the game: most games never come near 18, and a chart scaled to 18 would be flat.
    var max = 8;
    view.phases.forEach(function (ph) {
      Object.keys(ph.sc).forEach(function (c) { max = Math.max(max, ph.sc[c]); });
    });
    max = Math.min(34, max + 2 - (max % 2));
    var gridCounts = [];
    for (var g = 0; g <= max; g += max > 14 ? 6 : 4) gridCounts.push(g);
    if (max >= 18 && gridCounts.indexOf(18) < 0) gridCounts.push(18);
    function y(count) { return TL.top + TL.chart - count * TL.chart / max; }
    function x(index) { return timelineX(width, index); }

    // Grid: centre counts on the left, a rule at 18 (a solo), years along the bottom.
    gridCounts.forEach(function (count) {
      chart.appendChild(svg("line", { x1: TL.left, x2: width - TL.right, y1: y(count), y2: y(count), class: count === 18 ? "grid solo" : "grid" }));
      var label = svg("text", { x: TL.left - 6, y: y(count) + 3, class: "axis", "text-anchor": "end" });
      label.textContent = count;
      chart.appendChild(label);
    });
    view.phases.forEach(function (ph, index) {
      var movement = ph.phase === "Diplomacy";
      chart.appendChild(svg("line", {
        x1: x(index), x2: x(index), y1: TL.top + TL.chart, y2: TL.top + TL.chart + (movement ? 5 : 3), class: "tick",
      }));
      if (movement && ph.turn % 2 === 0) {
        chart.appendChild(svg("line", { x1: x(index), x2: x(index), y1: TL.top, y2: TL.top + TL.chart, class: "grid year" }));
        var year = svg("text", { x: x(index) + 2, y: TL.top + TL.chart + 14, class: "axis" });
        year.textContent = 1901 + Math.floor(ph.turn / 2);
        chart.appendChild(year);
      }
    });

    // One stepped line per power: ownership only changes when a phase is adjudicated.
    Object.keys(names).forEach(function (country) {
      var d = "";
      view.phases.forEach(function (ph, index) {
        var count = ph.sc[country] || 0;
        d += index === 0 ? "M" + x(0) + " " + y(count) : " H" + x(index) + " V" + y(count);
      });
      var us = isUs(names[country]);
      chart.appendChild(svg("path", { d: d, stroke: colors[country], class: "sc-line" + (us ? " us" : "") },
        names[country] + (us ? " (followed)" : "")));
    });

    // Marker rows.
    var rows = markersByRow();
    TL.rows.forEach(function (name, rowIndex) {
      var rowY = TL.top + TL.chart + 16 + rowIndex * TL.row + TL.row / 2 + 2;
      var label = svg("text", { x: TL.left - 6, y: rowY + 3, class: "axis row-label", "text-anchor": "end" });
      label.textContent = name;
      chart.appendChild(label);
      chart.appendChild(svg("line", { x1: TL.left, x2: width - TL.right, y1: rowY, y2: rowY, class: "row-rule" }));
      var stacked = {};
      rows[name].forEach(function (marker) {
        var offset = (stacked[marker.pi] = (stacked[marker.pi] || 0) + 1) - 1;
        var at = { x: x(marker.pi) + Math.min(offset, 3) * 3.5, y: rowY };
        var node;
        if (marker.shape === "cross") node = cross(at, 3.5, "marker cross", marker.text);
        else if (marker.shape === "bar") node = svg("rect", { x: at.x - 2, y: at.y - 4.5, width: 4, height: 9, class: "marker" }, marker.text);
        else if (marker.shape === "diamond") node = svg("path", { d: "M" + at.x + " " + (at.y - 5) + " l4.5 5 l-4.5 5 l-4.5 -5 Z", class: "marker" }, marker.text);
        else if (marker.shape === "square") node = svg("rect", { x: at.x - 3.5, y: at.y - 3.5, width: 7, height: 7, class: "marker agent" }, marker.text);
        else node = svg("circle", { cx: at.x, cy: at.y, r: 4, class: "marker" }, marker.text);
        if (marker.tone) node.classList.add(marker.tone);
        if (marker.color) node.style[marker.shape === "cross" ? "stroke" : "fill"] = marker.color;
        node.addEventListener("pointerdown", function (event) { event.stopPropagation(); });
        node.addEventListener("click", function () { go(marker.pi); if (marker.note) flashNote(marker.note); });
        chart.appendChild(node);
      });
    });

    chart.appendChild(svg("line", { id: "cursor", x1: 0, x2: 0, y1: TL.top - 4, y2: height - 2, class: "cursor" }));

    function scrub(event) {
      var box = chart.getBoundingClientRect();
      var px = (event.clientX - box.left) * width / box.width;
      var n = view.phases.length;
      go(Math.round((px - TL.left) * (n - 1) / (width - TL.left - TL.right)));
    }
    chart.addEventListener("pointerdown", function (event) {
      stop();
      chart.setPointerCapture(event.pointerId);
      scrub(event);
      chart.onpointermove = scrub;
    });
    chart.addEventListener("pointerup", function () { chart.onpointermove = null; });
    chart.addEventListener("pointercancel", function () { chart.onpointermove = null; });

    clear(box).appendChild(chart);
    box.dataset.width = width;
    moveCursor();
  }

  function moveCursor() {
    var cursor = $("cursor");
    if (!cursor) return;
    var at = timelineX(Number($("timeline").dataset.width), current);
    cursor.setAttribute("x1", at);
    cursor.setAttribute("x2", at);
  }

  // ---------- press and audit ----------

  function chip(code) {
    var words = view.verdicts.words[code] || String(code).replace(/_/g, " ");
    var tone = { ok: "ok", err: "err", gold: "warn", muted: "" }[view.verdicts.chips[code] || "muted"];
    return el("span", "tag " + tone, words);
  }

  function claimNode(claim, message) {
    var node = el("div", "claim");
    var head = el("div", "claim-head");
    head.appendChild(el("span", "claim-kind", claim.kind));
    if (claim.quote) head.appendChild(el("q", "claim-quote", claim.quote));
    node.appendChild(head);
    var verdict = el("div", "claim-verdict");
    verdict.appendChild(chip(claim.outcome));
    if (claim.category && claim.category !== "none") verdict.appendChild(chip(claim.category));
    if (claim.kind === "request" && claim.asked) verdict.appendChild(el("span", "muted small", "asked of " + title(claim.asked)));
    if (claim.window && (claim.window[0] !== message.turn || claim.window[1] !== message.turn)) {
      verdict.appendChild(el("span", "muted small", "covers " + turnLabel(claim.window[0]) +
        (claim.window[1] !== claim.window[0] ? " to " + turnLabel(claim.window[1]) : "")));
    }
    if (claim.settled !== null && claim.settled !== undefined && claim.settled !== current) {
      var jump = el("a", "small", "see " + view.phases[claim.settled].label);
      jump.href = "#";
      jump.addEventListener("click", function (event) { event.preventDefault(); go(claim.settled); });
      verdict.appendChild(jump);
    }
    node.appendChild(verdict);
    (claim.evidence || []).forEach(function (line) { node.appendChild(el("div", "claim-evidence mono", line)); });
    return node;
  }

  function turnLabel(turn) { return (turn % 2 === 0 ? "Spring " : "Autumn ") + (1901 + Math.floor(turn / 2)); }

  function messageNode(message) {
    var node = el("div", "message" + (message.public ? " public" : "") + (message.direction === "out" ? " out" : ""));
    node.id = "msg-" + message.id;
    var head = el("div", "message-head small");
    head.appendChild(dot(title(message.from)));
    head.appendChild(el("strong", "", title(message.from)));
    head.appendChild(document.createTextNode(" to "));
    if (message.public) head.appendChild(el("span", "", "everyone"));
    else { head.appendChild(dot(title(message.to))); head.appendChild(el("strong", "", title(message.to))); }
    head.appendChild(el("span", "muted", " · " + (message.public ? "public" : "private") + " · sent in " +
      message.sent_in.replace("Diplomacy", "Movement")));
    node.appendChild(head);
    node.appendChild(el("p", "message-text", message.text));
    message.claims.forEach(function (claim) { node.appendChild(claimNode(claim, message)); });
    return node;
  }

  function drawPress() {
    var ph = phase(), box = clear($("press"));
    var movement = ph.phase === "Diplomacy";
    $("press-phase").textContent = movement ? "about " + turnLabel(ph.turn) : "";
    var here = view.messages.filter(function (m) { return m.pi === current; });
    var shown = here.filter(function (m) {
      return pressShow === "all" || (pressShow === "private" && !m.public) || (pressShow === "public" && m.public) ||
        (pressShow === "claims" && m.claims.length);
    });
    if (!view.messages.length) {
      box.appendChild(el("p", "empty", view.episode.press === false
        ? "Gunboat: this game has no press."
        : view.seat === null
          ? "No public press was recorded. Private press shows when a seat with a log is followed."
          : "No press was recorded for this seat."));
      return;
    }
    if (!movement) {
      box.appendChild(el("p", "empty", "Press is shown with the movement phase it is about. Press sent during retreats and builds is listed under the next movement phase."));
      return;
    }
    if (!shown.length) {
      box.appendChild(el("p", "empty", here.length ? "No message here matches this filter (" + here.length + " in this phase)." : "No press about this turn."));
      return;
    }
    shown.forEach(function (message) { box.appendChild(messageNode(message)); });
  }

  function auditRequested() {
    try { return Number(localStorage.getItem("ide.auditAsked." + EPISODE + "." + view.seat)) || 0; } catch (e) { return 0; }
  }

  function drawAuditState() {
    var box = clear($("audit-state"));
    var s = seatRow();
    $("trust-section").hidden = !(view.audit && view.audit.powers && Object.keys(view.audit.powers).length);
    if (view.audit && view.audit.error) {
      box.appendChild(el("p", "notice err", "The press audit file could not be read: " + view.audit.error));
    } else if (view.audit && view.audit.joined) {
      var a = view.audit;
      box.appendChild(el("p", "muted", "Press audit for " + title(a.our_power) + ": " + a.messages_with_claims + " of " + a.messages +
        " messages make a checkable claim. Each claim below shows what was said, the verdict, and the orders that settled it." +
        (a.belief_logged ? "" : " Our policy logged no stance on other powers, so claims cannot be marked relied on or doubted.")));
    } else if (view.audit) {
      var other = view.seats.find(function (x) { return x.slot === view.audit.slot; });
      var p = el("p", "notice");
      p.appendChild(document.createTextNode("This game's press audit is for " + (other ? other.power + " (" + other.policy + ")" : "another seat") + ". "));
      if (other) {
        var link = el("a", "", "Follow that seat");
        link.href = "?seat=" + other.slot + "&phase=" + current;
        p.appendChild(link);
        p.appendChild(document.createTextNode(" to see claims and verdicts on its press."));
      }
      box.appendChild(p);
    } else if (view.episode.press !== false && s && s.has_log && view.messages.some(function (m) { return !m.public; })) {
      var row = el("p", "audit-ask");
      var asked = auditRequested();
      var button = el("button", "small", asked ? "Ask again" : "Ask the agent to audit this game");
      button.type = "button";
      button.addEventListener("click", askForAudit);
      row.appendChild(button);
      row.appendChild(el("span", "muted", asked
        ? " Asked at " + new Date(asked).toLocaleTimeString("en-US", { timeZone: "America/Los_Angeles", hour: "numeric", minute: "2-digit" }) +
          " PT. An audit takes the agent about ten minutes; this page shows it when it is done."
        : " No press audit yet. The agent reads every message, lists its promises and threats, and checks them against the orders (about ten minutes)."));
      box.appendChild(row);
    }
  }

  function drawTrust() {
    var box = clear($("trust"));
    if (!view.audit || !view.audit.powers) return;
    var powers = view.audit.powers, our = view.audit.our_power;
    var table = el("table", "trust-table");
    var head = el("tr");
    [["Power", ""], ["Word held", "num"], ["Lied to us", "num"], ["Doubted wrongly", "num"], ["Did as asked", "num"]]
      .forEach(function (h) { head.appendChild(el("th", h[1], h[0])); });
    table.appendChild(el("thead")).appendChild(head);
    var body = table.appendChild(el("tbody"));
    var flagged = [];
    POWER_ORDER.map(function (n) { return n.toUpperCase(); }).forEach(function (power) {
      var entry = powers[power];
      if (!entry) return;
      var row = el("tr", power === our ? "us" : "");
      var name = el("td");
      name.appendChild(dot(title(power)));
      name.appendChild(document.createTextNode(title(power) + (power === our ? " (us)" : "")));
      row.appendChild(name);
      var judged = entry.held + entry.did_not_hold;
      row.appendChild(el("td", "num", judged ? entry.held + " of " + judged : "—"));
      var cats = entry.categories || {};
      if (power === our) {
        var cell = el("td", "num", "we broke it " + (cats.we_broke_our_word || 0) + " times");
        cell.colSpan = 2;
        row.appendChild(cell);
      } else {
        var lies = (cats.betrayed || 0) + (cats.deceived || 0);
        row.appendChild(el("td", "num" + (lies ? " bad" : ""), lies ? lies + " in " + entry.betrayal_events + " event" + (entry.betrayal_events === 1 ? "" : "s") : "0"));
        row.appendChild(el("td", "num", String(cats.doubted_wrongly || 0)));
      }
      row.appendChild(el("td", "num", entry.asked ? entry.complied + " of " + entry.asked : "—"));
      body.appendChild(row);
      (entry.flagged || []).forEach(function (item) { flagged.push({ power: power, item: item }); });
    });
    box.appendChild(table);
    box.appendChild(el("p", "small muted", "Counts are claims in this one game: a handful per power, not a rate. “Word held” counts promises, threats and statements that could be checked."));

    if (!flagged.length) {
      box.appendChild(el("p", "empty", "Nothing flagged: no claim we relied on was broken, and none we doubted was kept."));
      return;
    }
    flagged.sort(function (a, b) { return (a.item.pi || 0) - (b.item.pi || 0); });
    [
      ["Where we were betrayed or deceived", ["betrayed", "deceived"], "We relied on these and they did not hold."],
      ["Where we doubted wrongly", ["doubted_wrongly"], "We did not rely on these and they were kept: perhaps a missed alliance."],
      ["Where we broke our own word", ["we_broke_our_word"], "What our policy said and then did not do."],
    ].forEach(function (group) {
      var items = flagged.filter(function (f) { return group[1].indexOf(f.item.category) >= 0; });
      var head = el("p", "flagged-head", group[0] + " ");
      head.appendChild(el("span", "num", "· " + items.length));
      head.title = group[2];
      box.appendChild(head);
      if (!items.length) { box.appendChild(el("p", "empty small", "None.")); return; }
      var list = el("ul", "flagged");
      items.forEach(function (f) {
        var li = el("li");
        var link = el("a", "", f.item.pi !== null && view.phases[f.item.pi] ? view.phases[f.item.pi].label : turnLabel(f.item.turn));
        link.href = "#";
        link.addEventListener("click", function (event) {
          event.preventDefault();
          setPressShow("all");
          var message = view.messages.find(function (m) { return m.id === f.item.message; });
          go(message && message.pi !== null ? message.pi : f.item.pi);
          var node = $("msg-" + f.item.message);
          if (node) { node.scrollIntoView({ block: "center", behavior: "smooth" }); flash(node); }
        });
        li.appendChild(link);
        li.appendChild(document.createTextNode(" "));
        li.appendChild(dot(title(f.power)));
        li.appendChild(document.createTextNode(title(f.power) + ": "));
        li.appendChild(el("q", "", f.item.quote));
        list.appendChild(li);
      });
      box.appendChild(list);
    });
  }

  function setPressShow(value) {
    pressShow = value;
    document.querySelectorAll("#press-filter button").forEach(function (button) {
      button.setAttribute("aria-pressed", String(button.dataset.show === value));
    });
    drawPress();
  }

  // ---------- decision ----------

  function factRow(list, label, value) {
    list.appendChild(el("dt", "", label));
    var dd = el("dd");
    if (value instanceof Node) dd.appendChild(value); else dd.textContent = value;
    list.appendChild(dd);
  }

  function drawDecision() {
    var has = Object.keys(view.decisions).length > 0;
    $("decision-section").hidden = !has;
    if (!has) return;
    var decision = view.decisions[current], body = clear($("decision-body"));
    if (!decision) {
      $("decision-brief").textContent = "· no decision line for this phase";
      body.appendChild(el("p", "empty", "Our seat's log has no decision line for this phase."));
      return;
    }
    var policy = decision.press_policy || {};
    var stances = policy.stances || {}, trust = policy.trust || {};
    var brief = [];
    if (decision.rejected) brief.push(decision.rejected + " order" + (decision.rejected === 1 ? "" : "s") + " dropped by the server");
    Object.keys(stances).forEach(function (p) { brief.push(title(p) + " " + stances[p]); });
    $("decision-brief").textContent = brief.length ? "· " + brief.join(", ") : "";

    var facts = el("dl", "facts");
    var powers = Object.keys(Object.assign({}, stances, trust));
    if (powers.length) {
      var line = el("span");
      powers.forEach(function (p, i) {
        if (i) line.appendChild(document.createTextNode(" · "));
        line.appendChild(dot(title(p)));
        line.appendChild(document.createTextNode(title(p) + ": " + (stances[p] || "no stance") +
          (trust[p] !== undefined ? ", trust " + trust[p] : "")));
      });
      factRow(facts, "Stances", line);
    }
    [["expected_orders", "Orders we expected of others"], ["require_orders", "Orders we committed to"]].forEach(function (pair) {
      if ((policy[pair[0]] || []).length) factRow(facts, pair[1], el("span", "mono", policy[pair[0]].join("  ·  ")));
    });
    if (policy.risk !== undefined) factRow(facts, "Risk setting", String(policy.risk));
    factRow(facts, "Orders dropped by the server", decision.rejected ? el("span", "bad", String(decision.rejected)) : "0");
    if (decision.difference) factRow(facts, "Changed from the search's choice", el("span", "mono", JSON.stringify(decision.difference)));
    if (decision.compute_ms !== undefined) factRow(facts, "Time to decide", (decision.compute_ms / 1000).toFixed(1) + " s");
    if (decision.llm_cost_usd !== undefined) factRow(facts, "LLM cost this phase", "$" + Number(decision.llm_cost_usd).toFixed(4));
    body.appendChild(facts);

    var rest = {};
    Object.keys(decision).forEach(function (key) {
      if (["press_policy", "rejected", "difference", "compute_ms", "llm_cost_usd"].indexOf(key) < 0) rest[key] = decision[key];
    });
    if (Object.keys(rest).length) {
      var more = el("details", "raw");
      more.appendChild(el("summary", "small muted", "Everything else on the log line"));
      more.appendChild(el("pre", "small", JSON.stringify(rest, null, 1)));
      body.appendChild(more);
    }
  }

  // ---------- notes ----------

  function noteLine(note) {
    var where = [];
    if (note.phase !== null && view.phases[note.phase]) where.push(view.phases[note.phase].label + " (phase " + note.phase + ")");
    if (note.power) where.push(note.power);
    if (note.territory) where.push(note.territory);
    return "[" + note.tag + "] " + where.join(", ") + ": " + note.text;
  }

  function drawNotes() {
    var box = clear($("notes"));
    var notes = view.annotations.slice().sort(function (a, b) { return (a.phase === null ? -1 : a.phase) - (b.phase === null ? -1 : b.phase); });
    $("notes-count").textContent = notes.length ? "· " + notes.length : "";
    $("send-all").hidden = notes.length < 2;
    if (!notes.length) {
      box.appendChild(el("p", "empty", "No notes yet. Step to the phase where something went wrong and add one below; then send it to the agent."));
      return;
    }
    notes.forEach(function (note) {
      var node = el("div", "note" + (note.author === "agent" ? " by-agent" : "") + (note.phase === current ? " here" : ""));
      node.id = "note-" + note.id;
      var head = el("div", "note-head small");
      var tone = NOTE_MARKS[note.tag];
      head.appendChild(el("span", "tag" + (tone === "bad" ? " err" : tone === "warn" ? " warn" : tone === "ok" ? " ok" : ""), note.tag.replace("-", " ")));
      if (note.phase !== null && view.phases[note.phase]) {
        var jump = el("a", "", view.phases[note.phase].label);
        jump.href = "#";
        jump.addEventListener("click", function (event) { event.preventDefault(); go(note.phase); });
        head.appendChild(jump);
      } else {
        head.appendChild(el("span", "muted", "whole game"));
      }
      if (note.power) { var p = el("span"); p.appendChild(dot(note.power)); p.appendChild(document.createTextNode(note.power)); head.appendChild(p); }
      if (note.territory) head.appendChild(el("span", "mono", note.territory));
      if (note.author === "agent") head.appendChild(el("span", "tag info", "from the agent"));
      node.appendChild(head);
      node.appendChild(el("p", "note-text", note.text));
      var actions = el("div", "note-actions");
      var send = el("button", "small plain", "Send to agent");
      send.type = "button";
      send.addEventListener("click", function () { sendNotes([note], send); });
      var remove = el("button", "small plain", "Delete");
      remove.type = "button";
      remove.addEventListener("click", function () { deleteNote(note); });
      actions.appendChild(send);
      actions.appendChild(remove);
      node.appendChild(actions);
      box.appendChild(node);
    });
  }

  function flash(node) {
    node.classList.remove("flash");
    void node.offsetWidth;  // restart the animation
    node.classList.add("flash");
  }

  function flashNote(id) { var node = $("note-" + id); if (node) flash(node); }

  function pinNote(territory, power) {
    $("note-territory").value = territory.abbr;
    if (power) $("note-power").value = power;
    $("note-hint").textContent = "Pinned to " + territory.name + (power ? " (" + power + ")" : "") + ".";
    $("note-text").focus({ preventScroll: true });
  }

  function request(method, path, body) {
    return fetch(path, {
      method: method,
      headers: body ? { "content-type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    }).then(function (response) {
      if (!response.ok) return response.json().then(function (data) { throw new Error(data.detail || response.statusText); });
      return response.json();
    });
  }

  function addNote(event) {
    event.preventDefault();
    var text = $("note-text").value.trim();
    if (!text) { $("note-hint").textContent = "Write the note first."; $("note-text").focus(); return; }
    request("POST", "/api/replays/" + encodeURIComponent(EPISODE) + "/annotations", {
      text: text, tag: $("note-tag").value, phase: current,
      power: $("note-power").value || null, territory: $("note-territory").value.trim().toUpperCase() || null,
    }).then(function (note) {
      view.annotations.push(note);
      $("note-text").value = "";
      $("note-territory").value = "";
      $("note-power").value = "";
      $("note-hint").textContent = "Added. Send it to the agent from the list above, or keep going.";
      drawNotes();
      drawTimeline();
      flashNote(note.id);
    }).catch(function (error) { $("note-hint").textContent = "Could not save the note: " + error.message; });
  }

  function deleteNote(note) {
    request("DELETE", "/api/replays/" + encodeURIComponent(EPISODE) + "/annotations/" + note.id).then(function () {
      view.annotations = view.annotations.filter(function (other) { return other.id !== note.id; });
      drawNotes();
      drawTimeline();
    }).catch(function (error) { $("note-hint").textContent = "Could not delete the note: " + error.message; });
  }

  // ---------- talking to the agent ----------

  function gameLine() {
    var s = seatRow();
    return view.episode.variant + " episode " + EPISODE +
      (s ? " (we are " + s.power + ", " + s.policy + ", score " + fmt(s.score) + ", " + s.final_centers + " centres at the end)" : "");
  }

  function link(phaseIndex) {
    return "/replays/" + EPISODE + "?phase=" + phaseIndex + (view.seat !== null ? "&seat=" + view.seat : "");
  }

  function toAgent(text, context) {
    if (window.ide && window.ide.sendToAgent) return Promise.resolve(window.ide.sendToAgent(text, context));
    return request("POST", "/api/chat", { text: text, context: context });
  }

  function sendNotes(notes, button) {
    var one = notes.length === 1;
    var text = (one ? "A note on " : notes.length + " notes on ") + gameLine() + ":\n" +
      notes.map(function (note) { return "- " + noteLine(note) + " " + link(note.phase === null ? current : note.phase); }).join("\n") +
      "\nPlease look at " + (one ? "this" : "these") + " in the replay and say what the policy should change.";
    var first = notes[0].phase === null ? current : notes[0].phase;
    toAgent(text, {
      episode: EPISODE, phase: one ? first : current, seat: view.seat, annotations: notes.map(function (n) { return n.id; }),
      label: (one ? "note" : notes.length + " notes") + " · " + shortId(),
    }).then(function () {
      if (button) { button.textContent = "Sent"; setTimeout(function () { button.textContent = one ? "Send to agent" : "Send all to agent"; }, 2500); }
    }).catch(function (error) { $("note-hint").textContent = "Could not send: " + error.message; });
  }

  function askForAudit() {
    var s = seatRow();
    toAgent("Please run a press audit of " + gameLine() + ": the press-audit skill, for seat " + view.seat +
      (s ? " (" + s.power + ", " + s.policy + ")" : "") + ", written to .runtime/press/" + EPISODE +
      "/. I am watching the replay at " + link(current) + " and it will show the audit when audit.json appears.",
      { episode: EPISODE, request: "press-audit", seat: view.seat, phase: current, label: "press audit · " + shortId() })
      .then(function () {
        try { localStorage.setItem("ide.auditAsked." + EPISODE + "." + view.seat, String(Date.now())); } catch (e) { /* private mode */ }
        drawAuditState();
      });
  }

  function shortId() { return EPISODE.replace(/^ereq_/, "").slice(0, 8); }

  function setContext() {
    if (!(window.ide && window.ide.setContext)) return;
    window.ide.setContext({
      episode: EPISODE, phase: current, seat: view.seat,
      label: shortId() + " · " + phase().label,
    });
  }

  // ---------- moving through the game ----------

  function go(index) {
    if (index === null || index === undefined || !view || !view.phases.length) return;
    index = Math.max(0, Math.min(view.phases.length - 1, index));
    if (index === current && go.drawn) return;
    current = index;
    go.drawn = true;
    var ph = phase();
    $("phase-title").textContent = ph.label;
    $("phase-count").textContent = "phase " + current + " of " + (view.phases.length - 1);
    $("note-phase").textContent = ph.label;
    drawMap();
    mapNote();
    drawOrders();
    drawPress();
    drawDecision();
    moveCursor();
    document.querySelectorAll("#notes .note").forEach(function (node) { node.classList.remove("here"); });
    view.annotations.forEach(function (note) { if (note.phase === current) { var n = $("note-" + note.id); if (n) n.classList.add("here"); } });
    var url = new URL(location.href);
    url.searchParams.set("phase", current);
    if (view.seat !== null) url.searchParams.set("seat", view.seat);
    history.replaceState(null, "", url);
    setContext();
  }

  function stepMovement(direction) {
    for (var i = current + direction; i >= 0 && i < view.phases.length; i += direction) {
      if (view.phases[i].phase === "Diplomacy") return go(i);
    }
    go(direction > 0 ? view.phases.length - 1 : 0);
  }

  function stop() {
    if (playing) clearInterval(playing);
    playing = null;
    $("play").textContent = "Play";
    $("play").setAttribute("aria-pressed", "false");
  }

  function play() {
    if (playing) return stop();
    if (current >= view.phases.length - 1) go(0);
    $("play").textContent = "Pause";
    $("play").setAttribute("aria-pressed", "true");
    playing = setInterval(function () {
      if (current >= view.phases.length - 1) return stop();
      go(current + 1);
    }, Number($("speed").value));
  }

  function onKey(event) {
    if (!view || !view.phases.length || event.metaKey || event.ctrlKey || event.altKey) return;
    var tag = (event.target.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea" || tag === "select" || event.target.isContentEditable) return;
    if (event.key === "ArrowLeft") { stop(); event.shiftKey ? stepMovement(-1) : go(current - 1); }
    else if (event.key === "ArrowRight") { stop(); event.shiftKey ? stepMovement(1) : go(current + 1); }
    else if (event.key === "Home") { stop(); go(0); }
    else if (event.key === "End") { stop(); go(view.phases.length - 1); }
    else if (event.key === " " && tag !== "button" && tag !== "summary" && tag !== "a") play();
    else return;
    event.preventDefault();
  }

  // ---------- loading ----------

  function showProblems() {
    var box = clear($("problems"));
    view.problems.forEach(function (text) { box.appendChild(el("p", "notice err", text)); });
    var s = seatRow();
    if (s && (s.taint || []).length) {
      box.appendChild(el("p", "notice err", "The followed seat is tainted (" + s.taint.join(", ").replace(/_/g, " ") +
        "): its result says little about the policy."));
    }
  }

  function drawAll(startAt) {
    names = view.powers;
    colors = {};
    Object.keys(names).forEach(function (country) { colors[country] = powerColor(names[country]); });
    buildDefs();
    showProblems();

    var power = $("note-power");
    while (power.options.length > 1) power.remove(1);
    POWER_ORDER.forEach(function (name) { power.appendChild(new Option(name, name)); });
    var list = clear($("territory-list"));
    Object.keys(view.territories).forEach(function (id) {
      var t = terr(id);
      if (t.parent === Number(id)) list.appendChild(new Option(t.name, t.abbr));
    });

    drawAuditState();
    drawTrust();
    drawNotes();
    if (!view.phases.length) {
      $("phase-title").textContent = "No phases to show";
      $("orders").replaceChildren(el("p", "empty", "The replay has no adjudicated phases."));
      $("press").replaceChildren(el("p", "empty", "No press to show."));
      return;
    }
    drawTimeline();
    go.drawn = false;
    go(startAt);
  }

  function load(startAt) {
    var query = seat === null ? "" : "?seat=" + seat;
    return request("GET", "/api/replays/" + encodeURIComponent(EPISODE) + query).then(function (data) {
      view = data;
      drawAll(startAt === null || startAt === undefined ? 0 : startAt);
      watchForAudit();
    }).catch(function (error) {
      $("phase-title").textContent = "The replay could not be loaded";
      $("problems").replaceChildren(el("p", "notice err", error.message));
    });
  }

  // An audit is written by the agent minutes after it is asked for: reload when the file changes.
  function watchForAudit() {
    if (auditTimer) clearInterval(auditTimer);
    if (view.episode.press === false) return;
    auditTimer = setInterval(function () {
      if (document.hidden) return;
      request("GET", "/api/replays/" + encodeURIComponent(EPISODE) + "/audit-status").then(function (status) {
        if (status.stamp !== view.audit_stamp) load(current);
      }).catch(function () { /* the server is restarting: try again next time */ });
    }, AUDIT_POLL_MS);
  }

  $("prev").addEventListener("click", function () { stop(); go(current - 1); });
  $("next").addEventListener("click", function () { stop(); go(current + 1); });
  $("play").addEventListener("click", play);
  $("speed").addEventListener("change", function () { if (playing) { stop(); play(); } });
  $("note-form").addEventListener("submit", addNote);
  $("send-all").addEventListener("click", function () { sendNotes(view.annotations, $("send-all")); });
  $("seat-select").addEventListener("change", function () {
    var url = new URL(location.href);
    if (this.value === "") url.searchParams.delete("seat"); else url.searchParams.set("seat", this.value);
    url.searchParams.set("phase", current);
    location.href = url;
  });
  document.querySelectorAll("#press-filter button").forEach(function (button) {
    button.addEventListener("click", function () { setPressShow(button.dataset.show); });
  });
  document.addEventListener("keydown", onKey);
  var resizeTimer = null;
  window.addEventListener("resize", function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () { if (view && view.phases.length) drawTimeline(); }, 150);
  });

  load(root.dataset.phase === "" ? null : Number(root.dataset.phase));
})();
