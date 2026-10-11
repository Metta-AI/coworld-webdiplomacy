// Reports pages: every button with data-ask sends its text to the agent through the shared chat
// (window.ide.sendToAgent, from chat.js) with the report it is about as context.
(function () {
  "use strict";

  var status = document.getElementById("report-ask-status");

  function say(text, bad) {
    if (!status) return;
    status.textContent = text;
    status.classList.toggle("bad", Boolean(bad));
  }

  document.querySelectorAll("button[data-ask]").forEach(function (button) {
    button.addEventListener("click", function () {
      // Flat values: the chat shows the context as "key value" pairs.
      var context = { report: button.dataset.kind + (button.dataset.slug ? "/" + button.dataset.slug : "") };
      if (button.dataset.slug) context.page = "/reports/" + button.dataset.kind + "/" + button.dataset.slug;
      button.disabled = true;
      window.ide.sendToAgent(button.dataset.ask, context).then(function () {
        say("Sent to the agent. Its answer and the card appear in the panel on the right.");
      }).catch(function (error) {
        button.disabled = false;
        say(error.message, true);
      });
    });
  });
})();
