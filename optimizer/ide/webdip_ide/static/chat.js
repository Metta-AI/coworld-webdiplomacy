// The agent panel on every page: chat with the running agent, the agent's cards, presence.
//
// For other pages:
//   window.ide.sendToAgent(text, context)  post a user message; returns a Promise of the stored message.
//                                          `context` is a small object such as
//                                          {episode, phase, annotations: [ids], label}. Opens the panel.
//   window.ide.setContext(context | null)  what the next message typed in the panel will carry
//                                          (shown as a chip above the input; the user can remove it).
//   window.ide.getContext()
//   window.ide.renderMarkdown(text)        safe HTML string for a small Markdown subset
//   window.ide.cardElement(card)           DOM node for one agent card
//   window.ide.onUpdate(fn)                fn({status, presence, messages, cards}) after every poll
//   window.ide.openPanel()
//
// No dependencies, no build step. The page polls the JSON API every two seconds.
(function () {
  "use strict";

  var POLL_MS = 2000;
  var state = { status: null, presence: "Checking for an agent…", messages: [], cards: [], delivered: 0 };
  var context = null;
  var listeners = [];
  var seenCards = 0;
  var $ = function (id) { return document.getElementById(id); };

  // --- small helpers ---

  function escapeHtml(text) {
    return String(text).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function ago(seconds) {
    if (seconds < 5) return "just now";
    if (seconds < 90) return Math.round(seconds) + " s ago";
    if (seconds < 5400) return Math.round(seconds / 60) + " min ago";
    if (seconds < 172800) return Math.round(seconds / 3600) + " h ago";
    return Math.round(seconds / 86400) + " days ago";
  }

  var clockFormat = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/Los_Angeles", hour: "numeric", minute: "2-digit", timeZoneName: "short",
  });
  var dayFormat = new Intl.DateTimeFormat("en-US", { timeZone: "America/Los_Angeles", month: "short", day: "numeric" });
  function when(ts) {
    var date = new Date(ts * 1000);
    var sameDay = dayFormat.format(date) === dayFormat.format(new Date());
    return (sameDay ? "" : dayFormat.format(date) + ", ") + clockFormat.format(date);
  }

  // Links may only go to an IDE page or a web address: never javascript: or data:.
  function safeHref(href) {
    href = String(href || "").trim();
    if (/^\/(?!\/)/.test(href) || /^https?:\/\//i.test(href)) return href;
    return null;
  }

  // --- Markdown: escape everything first, then add a small set of tags ---

  function inline(text) {
    var code = [];
    var out = escapeHtml(text).replace(/`([^`]+)`/g, function (_, body) {
      code.push("<code>" + body + "</code>");
      return "\u0000" + (code.length - 1) + "\u0000";
    });
    out = out.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, function (whole, label, href) {
      var safe = safeHref(href.replace(/&amp;/g, "&"));
      if (!safe) return whole;
      var external = /^https?:/i.test(safe);
      return '<a href="' + escapeHtml(safe) + '"' + (external ? ' target="_blank" rel="noopener"' : "") + ">" + label + "</a>";
    });
    out = out.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    out = out.replace(/(^|[^\w*])\*([^*\s][^*]*)\*(?!\w)/g, "$1<em>$2</em>");
    out = out.replace(/(^|[^\w_])_([^_\s][^_]*)_(?!\w)/g, "$1<em>$2</em>");
    return out.replace(/\u0000(\d+)\u0000/g, function (_, index) { return code[Number(index)]; });
  }

  function tableRow(line) {
    return line.trim().replace(/^\||\|$/g, "").split("|").map(function (cell) { return cell.trim(); });
  }

  function renderMarkdown(source) {
    var lines = String(source || "").replace(/\r\n?/g, "\n").split("\n");
    var html = [];
    var i = 0;
    while (i < lines.length) {
      var line = lines[i];
      if (/^\s*$/.test(line)) { i += 1; continue; }
      if (/^```/.test(line)) {
        var block = [];
        i += 1;
        while (i < lines.length && !/^```/.test(lines[i])) { block.push(lines[i]); i += 1; }
        i += 1;
        html.push("<pre><code>" + escapeHtml(block.join("\n")) + "</code></pre>");
        continue;
      }
      var heading = /^(#{1,4})\s+(.*)$/.exec(line);
      if (heading) {
        var level = Math.min(heading[1].length + 2, 4);  // card headings never outrank the card title
        html.push("<h" + level + ">" + inline(heading[2]) + "</h" + level + ">");
        i += 1;
        continue;
      }
      if (/^\s*([-*_])\s*\1\s*\1[\s\-*_]*$/.test(line)) { html.push("<hr>"); i += 1; continue; }
      if (/^\s*\|.*\|\s*$/.test(line) && i + 1 < lines.length && /^\s*\|[\s:|-]+\|\s*$/.test(lines[i + 1])) {
        var head = tableRow(line);
        var rows = [];
        i += 2;
        while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) { rows.push(tableRow(lines[i])); i += 1; }
        html.push("<table><thead><tr>" + head.map(function (c) { return "<th>" + inline(c) + "</th>"; }).join("") +
          "</tr></thead><tbody>" + rows.map(function (row) {
            return "<tr>" + row.map(function (c) { return "<td>" + inline(c) + "</td>"; }).join("") + "</tr>";
          }).join("") + "</tbody></table>");
        continue;
      }
      var bullet = /^\s*[-*+]\s+/;
      var numbered = /^\s*\d+[.)]\s+/;
      if (bullet.test(line) || numbered.test(line)) {
        var marker = bullet.test(line) ? bullet : numbered;
        var items = [];
        while (i < lines.length && (marker.test(lines[i]) || (/^\s{2,}\S/.test(lines[i]) && items.length))) {
          if (marker.test(lines[i])) items.push(lines[i].replace(marker, ""));
          else items[items.length - 1] += " " + lines[i].trim();
          i += 1;
        }
        var tag = marker === bullet ? "ul" : "ol";
        html.push("<" + tag + ">" + items.map(function (item) { return "<li>" + inline(item) + "</li>"; }).join("") + "</" + tag + ">");
        continue;
      }
      if (/^\s*>\s?/.test(line)) {
        var quote = [];
        while (i < lines.length && /^\s*>\s?/.test(lines[i])) { quote.push(lines[i].replace(/^\s*>\s?/, "")); i += 1; }
        html.push("<blockquote>" + inline(quote.join(" ")) + "</blockquote>");
        continue;
      }
      var paragraph = [];
      while (i < lines.length && !/^\s*$/.test(lines[i]) && !/^(```|#{1,4}\s|\s*[-*+]\s+|\s*\d+[.)]\s+|\s*>)/.test(lines[i])) {
        paragraph.push(lines[i]);
        i += 1;
      }
      html.push("<p>" + inline(paragraph.join("\n")).replace(/\n/g, "<br>") + "</p>");
    }
    return html.join("\n");
  }

  // --- context: what the next message carries ---

  function contextLabel(ctx) {
    if (!ctx) return "";
    if (ctx.label) return String(ctx.label);
    var parts = [];
    if (ctx.episode) parts.push(String(ctx.episode));
    if (ctx.phase !== undefined && ctx.phase !== null) parts.push("phase " + ctx.phase);
    if (ctx.annotations && ctx.annotations.length) {
      parts.push(ctx.annotations.length + " annotation" + (ctx.annotations.length === 1 ? "" : "s"));
    }
    if (!parts.length) {
      Object.keys(ctx).slice(0, 3).forEach(function (key) { parts.push(key + " " + ctx[key]); });
    }
    return parts.join(" · ");
  }

  function contextHref(ctx) {
    if (ctx && ctx.link && safeHref(ctx.link)) return safeHref(ctx.link);
    if (ctx && ctx.episode) {
      var href = "/replays/" + encodeURIComponent(ctx.episode);
      return ctx.phase !== undefined && ctx.phase !== null ? href + "?phase=" + encodeURIComponent(ctx.phase) : href;
    }
    return null;
  }

  function setContext(ctx) {
    context = ctx && Object.keys(ctx).length ? ctx : null;
    var chip = $("agent-context");
    if (!chip) return;
    chip.hidden = !context;
    $("agent-context-label").textContent = context ? "Attached: " + contextLabel(context) : "";
  }

  // --- rendering ---

  function messageElement(message) {
    var node = el("div", "msg " + (message.sender === "agent" ? "agent" : "user"));
    node.dataset.seq = message.seq;
    var who = el("div", "who", message.sender === "agent" ? "Agent" : "You");
    who.appendChild(el("time", "", when(message.ts)));
    node.appendChild(who);
    var body = el("div", "body md");
    body.innerHTML = renderMarkdown(message.text);
    node.appendChild(body);
    if (message.context) {
      var chip = el("div", "ctx");
      var href = contextHref(message.context);
      var label = el(href ? "a" : "span", "", contextLabel(message.context));
      if (href) label.href = href;
      chip.appendChild(label);
      node.appendChild(chip);
    }
    if (message.sender === "user") node.appendChild(el("div", "state"));
    return node;
  }

  function cardElement(card) {
    var node = el("article", "agent-card");
    var meta = el("div", "meta");
    meta.appendChild(el("span", "tag " + ({ result: "ok", idea: "info", replay: "warn" }[card.kind] || ""), card.kind));
    meta.appendChild(el("time", "", when(card.ts)));
    node.appendChild(meta);
    node.appendChild(el("h4", "", card.title));
    if (card.body) {
      var body = el("div", "md");
      body.innerHTML = renderMarkdown(card.body);
      node.appendChild(body);
    }
    var href = safeHref(card.link);
    if (href) {
      var open = el("a", "open", href.charAt(0) === "/" ? "Open " + href.split("?")[0] + " →" : "Open link →");
      open.href = href;
      if (href.charAt(0) !== "/") { open.target = "_blank"; open.rel = "noopener"; }
      node.appendChild(open);
    }
    return node;
  }

  function presenceText(status) {
    if (!status) return "Checking for an agent…";
    var seen = status.seen_age === null ? "" : "last seen " + ago(status.seen_age);
    if (status.state === "listening") return "Agent is listening" + (seen ? " · " + seen : "") + ". Messages reach it in a few seconds.";
    if (status.state === "working") return "Agent is working · " + seen + ". It reads new messages at its next step.";
    if (status.state === "idle") return "Agent " + seen + " and not listening. Messages wait until it next runs; type anything in its terminal to wake it.";
    return "No agent attached. Start Claude Code in the optimizer root and say “open the IDE”.";
  }

  // Under each of the user's messages that the agent has not been handed yet, say why it is waiting.
  function updateDeliveryStates() {
    var status = state.status;
    var nodes = document.querySelectorAll("#agent-chat .msg.user");
    var lastDelivered = null;
    nodes.forEach(function (node) {
      var line = node.querySelector(".state");
      var seq = Number(node.dataset.seq);
      line.className = "state";
      line.textContent = "";
      if (seq <= state.delivered) { lastDelivered = node; return; }
      line.classList.add("waiting");
      if (!status || status.state === "listening") line.textContent = "Sending to the agent…";
      else if (status.state === "working") line.textContent = "Waiting: the agent is busy and will read this at its next step.";
      else if (status.state === "idle") line.textContent = "Waiting: the agent is idle and not listening.";
      else line.textContent = "Waiting: no agent is attached.";
    });
    var last = nodes[nodes.length - 1];
    if (lastDelivered && lastDelivered === last && !last.nextElementSibling) {
      last.querySelector(".state").textContent = "Delivered to the agent.";
    }
  }

  function render(status) {
    state.presence = presenceText(status);
    var presence = $("agent-presence");
    if (presence) {
      var kind = !status ? "off" : { listening: "ok pulse", working: "ok", idle: "warn", none: "off" }[status.state];
      presence.replaceChildren(el("span", "dot " + kind), document.createTextNode(state.presence));
      $("agent-toggle-dot").className = "dot " + kind;
    }
    updateDeliveryStates();
    listeners.forEach(function (fn) {
      try { fn(state); } catch (error) { console.error(error); }
    });
  }

  function appendMessages(messages) {
    var box = $("agent-chat");
    if (!box || !messages.length) return;
    var pinned = box.scrollHeight - box.scrollTop - box.clientHeight < 60;
    $("agent-chat-empty").hidden = true;
    messages.forEach(function (message) {
      if (box.querySelector('[data-seq="' + message.seq + '"]')) return;
      state.messages.push(message);
      box.appendChild(messageElement(message));
    });
    if (pinned) box.scrollTop = box.scrollHeight;
  }

  function appendCards(cards) {
    var box = $("agent-cards");
    if (!box || !cards.length) return;
    $("agent-cards-empty").hidden = true;
    cards.forEach(function (card) {
      state.cards.push(card);
      box.insertBefore(cardElement(card), box.firstChild);  // newest first
    });
    updateCardCount();
  }

  function updateCardCount() {
    var count = $("agent-cards-count");
    var unseen = state.cards.length - seenCards;
    count.textContent = state.cards.length ? String(state.cards.length) + (unseen > 0 ? " · " + unseen + " new" : "") : "";
    count.classList.toggle("new", unseen > 0);
  }

  function markCardsSeen() {
    seenCards = state.cards.length;
    try { localStorage.setItem("ide.cardsSeen", String(seenCards)); } catch (error) { /* private mode */ }
    updateCardCount();
  }

  // --- talking to the server ---

  function getJson(url) {
    return fetch(url, { headers: { accept: "application/json" } }).then(function (response) {
      if (!response.ok) throw new Error(url + " " + response.status);
      return response.json();
    });
  }

  var polling = false;
  function poll() {
    if (polling) return Promise.resolve();
    polling = true;
    var lastMessage = state.messages.length ? state.messages[state.messages.length - 1].seq : 0;
    var lastCard = state.cards.length ? state.cards[state.cards.length - 1].seq : 0;
    return Promise.all([
      getJson("/api/chat?after=" + lastMessage),
      getJson("/api/cards?after=" + lastCard),
      getJson("/api/agent/status"),
    ]).then(function (results) {
      state.delivered = results[0].delivered;
      appendMessages(results[0].messages);
      appendCards(results[1].cards);
      state.status = results[2];
      if (!$("agent-cards").hidden) markCardsSeen();
      render(state.status);
    }).catch(function () {
      state.status = null;
      state.presence = "The IDE server is not answering. Ask the agent to run ide/ide start.";
      var presence = $("agent-presence");
      if (presence) presence.replaceChildren(el("span", "dot off"), document.createTextNode(state.presence));
    }).then(function () { polling = false; });
  }

  function sendToAgent(text, ctx) {
    text = String(text || "").trim();
    if (!text) return Promise.reject(new Error("empty message"));
    openPanel();
    showTab("chat");
    return fetch("/api/chat", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ text: text, context: ctx || null }),
    }).then(function (response) {
      if (!response.ok) throw new Error("The message was not sent (" + response.status + ").");
      return response.json();
    }).then(function (message) {
      var box = $("agent-chat");
      appendMessages([message]);
      if (box) box.scrollTop = box.scrollHeight;
      updateDeliveryStates();
      return message;
    });
  }

  // --- panel chrome ---

  function panelOpen() { return !document.documentElement.classList.contains("agent-collapsed"); }

  function setPanel(open) {
    document.documentElement.classList.toggle("agent-collapsed", !open);
    var toggle = $("agent-panel-toggle");
    if (toggle) {
      toggle.setAttribute("aria-expanded", String(open));
      $("agent-toggle-label").textContent = open ? "Hide agent" : "Agent";
    }
    try { localStorage.setItem("ide.agentPanel", open ? "open" : "closed"); } catch (error) { /* private mode */ }
  }

  function openPanel() { if (!panelOpen()) setPanel(true); }

  function showTab(name) {
    ["chat", "cards"].forEach(function (tab) {
      $("agent-" + tab).hidden = tab !== name;
      $("agent-tab-" + tab).setAttribute("aria-selected", String(tab === name));
    });
    $("agent-compose").hidden = false;
    if (name === "cards") markCardsSeen();
    if (name === "chat") { var box = $("agent-chat"); box.scrollTop = box.scrollHeight; }
  }

  function start() {
    try { seenCards = Number(localStorage.getItem("ide.cardsSeen")) || 0; } catch (error) { seenCards = 0; }
    setPanel(panelOpen());
    $("agent-panel-toggle").addEventListener("click", function () { setPanel(!panelOpen()); });
    $("agent-tab-chat").addEventListener("click", function () { showTab("chat"); });
    $("agent-tab-cards").addEventListener("click", function () { showTab("cards"); });
    $("agent-context-clear").addEventListener("click", function () { setContext(null); });
    setContext(context);

    var input = $("agent-input");
    var hint = $("agent-compose-hint");
    function submit() {
      var text = input.value;
      if (!text.trim()) return;
      $("agent-send").disabled = true;
      sendToAgent(text, context).then(function () {
        input.value = "";
        hint.textContent = "Enter sends · Shift+Enter for a new line";
        hint.classList.remove("bad");
      }).catch(function (error) {
        hint.textContent = error.message;  // the text stays in the box so nothing is lost
        hint.classList.add("bad");
      }).then(function () { $("agent-send").disabled = false; input.focus(); });
    }
    $("agent-compose").addEventListener("submit", function (event) { event.preventDefault(); submit(); });
    input.addEventListener("keydown", function (event) {
      if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); submit(); }
    });

    poll();
    setInterval(function () { if (!document.hidden) poll(); }, POLL_MS);
    document.addEventListener("visibilitychange", function () { if (!document.hidden) poll(); });
  }

  window.ide = {
    sendToAgent: sendToAgent,
    setContext: setContext,
    getContext: function () { return context; },
    renderMarkdown: renderMarkdown,
    cardElement: cardElement,
    onUpdate: function (fn) { listeners.push(fn); if (state.status) fn(state); },
    openPanel: openPanel,
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
