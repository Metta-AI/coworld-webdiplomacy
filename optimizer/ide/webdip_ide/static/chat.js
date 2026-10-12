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
//   window.ide.draft(text)                 put text in the message box for the user to edit and send
//   window.ide.ideaActions(card)           "Test this idea" and "Not now" for an idea card, or a link to the
//                                          result when its experiment record is no longer proposed; null when
//                                          the card is not an idea or the user chose "Not now" in this browser
//
// No dependencies, no build step. The page polls the JSON API every two seconds.
(function () {
  "use strict";

  var POLL_MS = 2000;
  var state = { status: null, presence: "Checking for an agent…", messages: [], cards: [], delivered: 0, records: {} };
  var context = null;
  var contextDismissed = false;  // the user removed the chip: pages stop re-attaching until the next page load
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
  // A time in seconds since 1970, as Pacific time with the abbreviation that is right for its date
  // ("4:46 AM PDT", "Jan 5, 1:42 AM PST"), whatever zone the browser is in. Never write "PT".
  function when(ts) {
    var date = new Date(ts * 1000);
    var sameDay = dayFormat.format(date) === dayFormat.format(new Date());
    return (sameDay ? "" : dayFormat.format(date) + ", ") + clockFormat.format(date);
  }

  // Links may only go to an IDE page or a web address: never javascript: or data:.
  function safeHref(href) {
    href = String(href || "").trim();
    // "/\host" is refused with "//host": a browser reads both as another site's address.
    if (/^\/(?![\/\\])/.test(href) || /^https?:\/\//i.test(href)) return href;
    return null;
  }

  // --- Markdown: escape everything first, then add a small set of tags ---

  // Code spans and link tags are set aside while emphasis is applied, so `_` or `*` inside
  // code or inside an address (/replays/x?a=_b_) is never turned into a tag.
  function inline(text) {
    var kept = [];
    function keep(html) { kept.push(html); return "\u0000" + (kept.length - 1) + "\u0000"; }
    var out = escapeHtml(String(text).replace(/\u0000/g, "")).replace(/`([^`]+)`/g, function (_, body) {
      return keep("<code>" + body + "</code>");
    });
    out = out.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, function (whole, label, href) {
      var safe = safeHref(href.replace(/&amp;/g, "&"));
      if (!safe) return whole;
      var external = /^https?:/i.test(safe);
      return keep('<a href="' + escapeHtml(safe) + '"' + (external ? ' target="_blank" rel="noopener"' : "") + ">") + label + keep("</a>");
    });
    out = out.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    out = out.replace(/(^|[^\w*])\*([^*\s][^*]*)\*(?!\w)/g, "$1<em>$2</em>");
    out = out.replace(/(^|[^\w_])_([^_\s][^_]*)_(?!\w)/g, "$1<em>$2</em>");
    return out.replace(/\u0000(\d+)\u0000/g, function (_, index) { return kept[Number(index)]; });
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
      var query = [];
      if (ctx.phase !== undefined && ctx.phase !== null) query.push("phase=" + encodeURIComponent(ctx.phase));
      if (ctx.seat !== undefined && ctx.seat !== null) query.push("seat=" + encodeURIComponent(ctx.seat));
      return "/replays/" + encodeURIComponent(ctx.episode) + (query.length ? "?" + query.join("&") : "");
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
    var href = safeHref(card.link);
    var heading = el("h4", "", href ? undefined : card.title);
    if (href) {  // the title is the link as well: a larger thing to click than the line under the card
      var titleLink = el("a", "", card.title);
      titleLink.href = href;
      if (href.charAt(0) !== "/") { titleLink.target = "_blank"; titleLink.rel = "noopener"; }
      heading.appendChild(titleLink);
    }
    node.appendChild(heading);
    if (card.body) {
      var body = el("div", "md");
      body.innerHTML = renderMarkdown(card.body);
      node.appendChild(body);
    }
    if (href) {
      var open = el("a", "open", linkLabel(href));
      open.href = href;
      if (href.charAt(0) !== "/") { open.target = "_blank"; open.rel = "noopener"; }
      node.appendChild(open);
    }
    // Under the title, not under the body: an idea's evidence can run to several screens.
    var actions = ideaActions(card);
    if (actions) heading.after(actions);
    return node;
  }

  // --- idea cards: from an idea to an experiment in one click ---

  // "Not now" is remembered in this browser only (card ids in localStorage): the card stays, its
  // two buttons go. The server keeps no state about it.
  var IDEAS_NOT_NOW = "ide.ideasNotNow";
  function ideasNotNow() {
    try { return JSON.parse(localStorage.getItem(IDEAS_NOT_NOW)) || []; } catch (error) { return []; }
  }

  // The request "Test this idea" puts in the message box, so the user only has to press Enter (or
  // change it first). An idea card normally links to the proposed experiment record the agent wrote
  // with it (/experiments/<id>): then the request is to run that record. A card with no record asks
  // for the record first, so the idea is on the Experiments page before anything is built.
  function ideaRecord(card) {
    return /^\/experiments\/([A-Za-z0-9][A-Za-z0-9._-]*)$/.exec(card.link || "");
  }

  function testIdeaText(card) {
    var record = ideaRecord(card);
    if (record) {
      return "Run the proposed experiment " + record[1] + " (\u201c" + card.title + "\u201d). Check closed_levers.md, open_levers.md and " +
        "the earlier records in experiments/, and the record's predictions and decision rule once more, tell me what it will cost before you launch, then make the one " +
        "change as a new version (tools/ship.py --experiment " + record[1] + "), write it in the record as the candidate, run " +
        "the paired A/B (tools/run_ab.py --record " + record[1] + ") and a health game, and post a result card that links to " +
        "/experiments/" + record[1] + ".";
    }
    return "Test this idea: \u201c" + card.title + "\u201d. First write it down as a proposed experiment record with the experiment " +
      "skill (check closed_levers.md, open_levers.md and the earlier records in experiments/; hypothesis, predictions, decision rule and cost; status proposed), so it is on the " +
      "Experiments page, and tell me its cost. Then make the one change as a new version, run a paired A/B against the " +
      "current version at the lab's default size (tools/run_ab.py: 28 games) and a health game, and post a result card that " +
      "links to the record (/experiments/<id>).";
  }

  function ideaActions(card) {
    if (card.kind !== "idea" || ideasNotNow().indexOf(card.id) !== -1) return null;
    var row = el("div", "idea-actions");
    row.dataset.idea = card.id;
    // An idea whose record has left "proposed" has been run: asking again would build, upload and
    // pay for the same experiment a second time. The record has the games and the verdict.
    var record = ideaRecord(card);
    var status = record ? state.records[record[1]] : "";
    if (status && status !== "proposed") {
      var result = el("a", "small", status === "running" ? "Running now: see the games so far" : "Tested (" + status + "): see the result");
      result.href = card.link;
      row.appendChild(result);
      return row;
    }
    var test = el("button", "small", "Test this idea");
    test.type = "button";
    test.title = "Puts a request for an experiment in the message box. Nothing is sent until you press Enter.";
    test.addEventListener("click", function () { draft(testIdeaText(card)); });
    var later = el("button", "small plain", "Not now");
    later.type = "button";
    later.title = "Hide these two buttons for this idea in this browser. The card stays in the Cards tab.";
    later.addEventListener("click", function () {
      try { localStorage.setItem(IDEAS_NOT_NOW, JSON.stringify(ideasNotNow().concat([card.id]))); } catch (error) { /* private mode */ }
      document.querySelectorAll(".idea-actions").forEach(function (other) {
        if (other.dataset.idea === card.id) other.remove();
      });
      listeners.forEach(function (fn) { try { fn(state); } catch (error) { console.error(error); } });
    });
    row.appendChild(test);
    row.appendChild(later);
    return row;
  }

  // Where a card's link goes, in words rather than as a path.
  function linkLabel(href) {
    if (href.charAt(0) !== "/") return "Open the link →";
    var phase = /[?&]phase=(\d+)/.exec(href);
    if (/^\/replays\/[^/?]+/.test(href)) return "Open the replay" + (phase ? " at phase " + phase[1] : "") + " →";
    if (/^\/replays/.test(href)) return "Open these games in Replays →";
    if (/^\/dashboard/.test(href)) return "Open the dashboard →";
    if (/^\/reports\/[^/?]+\/[^/?]+/.test(href)) return "Read the report →";
    if (/^\/reports/.test(href)) return "Open Reports →";
    if (/^\/experiments\/[^/?]+/.test(href)) return "Open the experiment →";
    if (/^\/experiments/.test(href)) return "Open Experiments →";
    return "Open " + href.split("?")[0] + " →";
  }

  function presenceText(status) {
    if (!status) return "Checking for an agent…";
    var seen = status.seen_age === null ? "" : "last seen " + ago(status.seen_age);
    if (status.state === "listening") return "Agent is listening" + (seen ? " · " + seen : "") + ". Messages reach it in a few seconds.";
    if (status.state === "ended") return "The agent session has ended. Start claude again in the optimizer folder: it reads waiting messages when it starts.";
    if (status.state === "working" && stuck(status)) return "Agent " + seen + ", and a message has waited " + ago(status.waiting_age).replace(" ago", "") + ": it is in one long step, or its turn was interrupted. What to do is under the message.";
    if (status.state === "working") return "Agent is working · " + seen + ". It reads new messages at its next step.";
    if (status.state === "idle") return "Agent " + seen + " and not listening. Messages wait until it next runs: to wake it, type any word in its terminal and press Enter.";
    return "No agent attached. Start Claude Code in the optimizer root and say “open the IDE”.";
  }

  // A busy agent takes a message at its next tool call, seconds away as a rule. An interrupted
  // turn (Esc in the terminal) runs no hook, so from here it looks busy too: after this long,
  // stop saying "busy" and say what the user can do.
  var STUCK_AFTER_SECONDS = 25;
  // The one thing that works then. A message typed in the terminal runs the session's
  // UserPromptSubmit hook, which hands over what is waiting here and starts a new waiter. Enter on
  // an empty prompt submits nothing, so no hook runs (hooks.py: HOOK_EVENTS).
  var WAKE = "click into its terminal, type any word (“go” will do) and press Enter: this message is delivered with it. Enter alone does nothing.";
  function stuck(status) {
    return status.waiting_age !== null && status.waiting_age !== undefined && status.waiting_age > STUCK_AFTER_SECONDS;
  }

  // Under each of the user's messages that the agent has not been handed yet, say why it is waiting.
  function updateDeliveryStates() {
    var status = state.status;
    var nodes = document.querySelectorAll("#agent-chat .msg.user");
    var box = $("agent-chat");
    // A status line that appears under the last message must not push it out of view.
    var pinned = box && box.scrollHeight - box.scrollTop - box.clientHeight < 60;
    var lastDelivered = null;
    nodes.forEach(function (node) {
      var line = node.querySelector(".state");
      var seq = Number(node.dataset.seq);
      line.className = "state";
      line.textContent = "";
      if (seq <= state.delivered) { lastDelivered = node; return; }
      line.classList.add("waiting");
      if (!status || status.state === "listening") line.textContent = "Sending to the agent…";
      else if (status.state === "ended") line.textContent = "Waiting: the agent session has ended. Start claude again and it reads this.";
      else if (status.state === "working" && stuck(status)) line.textContent = "Not delivered yet. The agent is in one long step, or its turn was interrupted (Esc). If its terminal shows an empty prompt, " + WAKE;
      else if (status.state === "working") line.textContent = "Waiting: the agent is busy and will read this at its next step.";
      else if (status.state === "idle") line.textContent = "Waiting: the agent is idle and not listening. To wake it, " + WAKE;
      else line.textContent = "Waiting: no agent is attached.";
    });
    var last = nodes[nodes.length - 1];
    if (lastDelivered && lastDelivered === last && !last.nextElementSibling) {
      last.querySelector(".state").textContent = "Delivered to the agent.";
    }
    if (pinned) box.scrollTop = box.scrollHeight;
  }

  function render(status) {
    state.presence = presenceText(status);
    var presence = $("agent-presence");
    if (presence) {
      var kind = !status ? "off" : { listening: "ok pulse", working: stuck(status) ? "warn" : "ok", idle: "warn", ended: "off", none: "off" }[status.state];
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

  // A record's status changed (the agent ran or closed an experiment): draw each idea's actions again.
  function updateRecords(records) {
    if (JSON.stringify(records) === JSON.stringify(state.records)) return;
    state.records = records;
    document.querySelectorAll("#agent-cards .idea-actions").forEach(function (old) {
      var card = state.cards.filter(function (c) { return c.id === old.dataset.idea; })[0];
      if (card) old.replaceWith(ideaActions(card));
    });
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
      updateRecords(results[1].records || {});
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
    }).catch(function () {  // the request never reached the server
      throw new Error("Not sent: the IDE server is not answering.");
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
    $("agent-context-clear").addEventListener("click", function () { contextDismissed = true; setContext(null); });
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

  function draft(text) {
    var input = $("agent-input");
    if (!input) return;
    openPanel();
    showTab("chat");
    input.value = text;
    input.focus();
    input.setSelectionRange(text.length, text.length);
    $("agent-compose-hint").textContent = "Change it if you like, then press Enter to send";
  }

  window.ide = {
    sendToAgent: sendToAgent,
    setContext: function (ctx) { if (!contextDismissed) setContext(ctx); },
    draft: draft,
    getContext: function () { return context; },
    renderMarkdown: renderMarkdown,
    safeHref: safeHref,
    when: when,
    cardElement: cardElement,
    ideaActions: ideaActions,
    onUpdate: function (fn) { listeners.push(fn); if (state.status) fn(state); },
    openPanel: openPanel,
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
