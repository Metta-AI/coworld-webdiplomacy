// Experiments pages: a button with data-draft puts its request in the agent's message box for the
// user to change and send (window.ide.draft, from chat.js). While games are being read, or an
// experiment is running, the page reloads itself, but never under a message being typed.
(function () {
  "use strict";

  document.querySelectorAll("button[data-draft]").forEach(function (button) {
    button.addEventListener("click", function () { window.ide.draft(button.dataset.draft); });
  });

  var page = document.querySelector("[data-reload]");
  var box = document.getElementById("agent-input");
  if (page) setInterval(function () {
    if (document.hidden || (box && box.value)) return;
    // An opened entry of "What is closed" is being read: leave it open.
    if (document.querySelector(".closed-list details[open]")) return;
    location.reload();
  }, Number(page.dataset.reload) * 1000);
})();
