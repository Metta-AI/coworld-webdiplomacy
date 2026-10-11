// Dashboard page: filter form, hover notes, the opponents table (sort, details, write-up request).
// No dependencies. Data arrives rendered in the page; `window.dashboard` carries the current view.
(function () {
  "use strict";
  var view = window.dashboard || {};
  var page = document.querySelector(".dash");
  if (!page) return;

  // Filters apply as soon as one changes. Changing the policy drops the version, which
  // belongs to the old policy, and the variant, so the new policy gets its own default.
  var form = document.getElementById("dash-filters");
  if (form) {
    form.addEventListener("change", function (event) {
      if (event.target.name === "policy") {
        form.elements.version.value = "";
        form.elements.variant.disabled = true;
        if (form.elements.opponent) form.elements.opponent.disabled = true;
      }
      Array.prototype.forEach.call(form.elements, function (field) {
        if (field.name && (field.value === "" || (field.name === "source" && field.value === "all"))) field.disabled = true;
      });
      form.submit();
    });
  }

  // While the server is still reading episodes the page reloads itself, but not under a message
  // being typed in the agent panel (a reload would lose it): it then tries again later.
  var reload = Number(page.getAttribute("data-reload"));
  if (reload) setInterval(function () {
    var box = document.getElementById("agent-input");
    if (!(box && box.value)) window.location.reload();
  }, reload * 1000);

  // Hover notes: any element with data-tip.
  var tip = document.getElementById("dash-tip");
  function place(event) {
    var x = Math.min(event.clientX + 14, window.innerWidth - tip.offsetWidth - 8);
    var y = event.clientY + 18;
    if (y + tip.offsetHeight > window.innerHeight - 8) y = event.clientY - tip.offsetHeight - 10;
    tip.style.left = Math.max(8, x) + "px";
    tip.style.top = Math.max(8, y) + "px";
  }
  page.addEventListener("mousemove", function (event) {
    var target = event.target.closest ? event.target.closest("[data-tip]") : null;
    if (!target) { tip.hidden = true; return; }
    tip.textContent = target.getAttribute("data-tip");
    tip.hidden = false;
    place(event);
  });
  page.addEventListener("mouseleave", function () { tip.hidden = true; });

  // Opponents: each opponent is its own <tbody> (a summary row and a details row).
  var table = document.getElementById("dash-opponents");
  if (!table) return;

  table.addEventListener("click", function (event) {
    var more = event.target.closest("[data-more]");
    if (more) {
      var details = more.closest("tbody").querySelector(".dash-more");
      details.hidden = !details.hidden;
      more.setAttribute("aria-expanded", String(!details.hidden));
      more.textContent = details.hidden ? "Details" : "Hide details";
      return;
    }
    var writeup = event.target.closest("[data-writeup]");
    if (writeup) { askForWriteup(writeup); return; }
    var heading = event.target.closest("th[data-sort]");
    if (heading) sortBy(heading);
  });

  function sortBy(heading) {
    var key = heading.getAttribute("data-sort");
    var ascending = heading.getAttribute("aria-sort") === "descending";
    if (key === "name" && !heading.hasAttribute("aria-sort")) ascending = true;
    var bodies = Array.prototype.slice.call(table.tBodies).filter(function (b) { return b.hasAttribute("data-name"); });
    bodies.sort(function (a, b) {
      var left = a.getAttribute("data-" + key), right = b.getAttribute("data-" + key);
      var order = key === "name" ? left.localeCompare(right) : Number(left) - Number(right);
      return ascending ? order : -order;
    });
    bodies.forEach(function (body) { table.appendChild(body); });
    Array.prototype.forEach.call(table.tHead.querySelectorAll("th[aria-sort]"), function (th) { th.removeAttribute("aria-sort"); });
    heading.setAttribute("aria-sort", ascending ? "ascending" : "descending");
  }

  function askForWriteup(button) {
    var opponent = button.getAttribute("data-writeup");
    var scope = (view.variant === "all" ? "all variants" : view.variant) + ", " + view.source_label;
    var text = "Write up why " + view.policy + " wins or loses against " + opponent + " (" + scope +
      "). Use the matchup write-up skill and post the report as a card.";
    var context = { label: view.policy + " vs " + opponent, page: view.page, policy: view.policy, opponent: opponent,
                    variant: view.variant, source: view.source };
    var send = window.ide && window.ide.sendToAgent
      ? window.ide.sendToAgent(text, context)
      : fetch("/api/chat", { method: "POST", headers: { "content-type": "application/json" },
                             body: JSON.stringify({ text: text, context: context }) })
          .then(function (response) { if (!response.ok) throw new Error("not sent (" + response.status + ")"); });
    button.disabled = true;
    send.then(function () { button.textContent = "Asked. The reply comes in the agent panel."; })
        .catch(function (error) { button.disabled = false; button.textContent = "Could not send: " + error.message + ". Try again"; });
  }
})();
