# ruff: noqa: E501  (each tool's docstring is its model-facing description; kept on one line)
"""The tools the press agent calls during a wake.

Each tool returns plain text or JSON text. Errors come back as text so the model can
correct itself instead of the wake failing. Every call is logged (`tool_call` event) with
its arguments, result and duration. The type hints and docstrings are the tool schema the
model sees.
"""

import json
import time


class Toolbox:
    def __init__(self, player):
        self.p = player

    def _guard(self, tool, arguments, fn):
        """Run one tool call: enforce the wake deadline, turn ValueError into text the model can
        read, and log the call with its arguments and result."""
        started = time.time()
        if self.p.wake_deadline and self.p.clock() > self.p.wake_deadline:
            result = "TIME UP for this wake. Stop calling tools and give a one-line final answer."
        else:
            try:
                result = fn()
            except ValueError as error:
                result = f"ERROR: {error}"
        text = result if isinstance(result, str) else json.dumps(result)
        self.p.log(event="tool_call", wake=self.p.tracker["wake"], tool=tool, arguments=arguments,
                   result=text, seconds=round(time.time() - started, 2))
        return text

    # --- board and map ---------------------------------------------------------------

    def board(self) -> str:
        """The current board: centres and units of every power, neutral centres, your exposed centres, and the map connectivity of units near you."""
        return self._guard("board", {}, lambda: self.p.service.notation.brief(self.p.country))

    def connections(self, province: str) -> str:
        """Map lookup: which provinces an army or fleet in PROVINCE (e.g. "SER", "BUL") could move to, by unit type and coast. Static adjacency only: these are possible moves, not predictions of what anyone will do."""
        return self._guard("connections", {"province": province},
                           lambda: self.p.service.notation.connections(province))

    # --- search --------------------------------------------------------------------------

    def predict(self, power: str) -> str:
        """The most likely orders of one power this phase under your opponent model and your current committed policy, with frequencies."""
        return self._guard("predict", {"power": power}, lambda: self.p.searched(
            lambda: self.p.service.predict(power, self.p.policy)))

    def search(self, policy: dict) -> str:
        """Run look-ahead search under a policy and return the best orders for your units with expected/worst-case centres and per-order success rates. Policy keys (all optional): stances {POWER: ally|neutral|hostile}, trust {POWER: 0-1}, expected_orders [other powers' promised orders], forbid_moves_into [provinces], require_orders [your orders that must be played], center_values {POWER: bonus per centre taken from them}, risk 0-1. Does not change your submitted orders."""
        return self._guard("search", {"policy": policy}, lambda: self.p.searched(
            lambda: self.p.service.search(policy)[1]))

    def evaluate(self, orders: list[str], policy: dict | None = None) -> str:
        """Score a specific set of your orders (standard notation, e.g. "A PAR - BUR"; units left out hold) against sampled opponents under an optional policy."""
        return self._guard("evaluate", {"orders": orders, "policy": policy}, lambda: self.p.searched(
            lambda: self.p.service.evaluate(orders, policy)[1]))

    def assess_deal(self, power: str, their_orders: list[str], our_orders: list[str],
                    our_forbidden: list[str] | None = None) -> str:
        """Value a proposed deal with one power: expected centres if both sides honour it, if they betray you, and if you betray them."""
        def run():
            service = self.p.service
            honour = {"stances": {power: "ally"}, "trust": {power: 1.0}, "expected_orders": their_orders,
                      "require_orders": our_orders, "forbid_moves_into": our_forbidden or []}
            _, both, _ = service.search(honour)
            _, they_betray = service.evaluate(both["orders"], {"stances": {power: "hostile"}})
            _, we_betray, _ = service.search({"stances": {power: "ally"}, "trust": {power: 1.0},
                                              "expected_orders": their_orders})
            return {"both_honour": {"expected_centres": both["expected_centres"], "our_orders": both["orders"]},
                    "they_betray": {"expected_centres": they_betray["expected_centres"],
                                    "worst_case_centres": they_betray["worst_case_centres"]},
                    "we_betray": {"expected_centres": we_betray["expected_centres"], "our_orders": we_betray["orders"]}}
        arguments = {"power": power, "their_orders": their_orders, "our_orders": our_orders,
                     "our_forbidden": our_forbidden}
        return self._guard("assess_deal", arguments, lambda: self.p.searched(run))

    def commit_orders(self, policy: dict) -> str:
        """Adopt a policy for THIS phase: runs the search and saves the resulting orders to the server now (you can re-commit later). Returns the orders that will be played."""
        return self._guard("commit_orders", {"policy": policy}, lambda: self.p.searched(
            lambda: self.p.commit(policy)))

    # --- press -----------------------------------------------------------------------------

    def send_press(self, to: str, text: str) -> str:
        """Send a message. `to` is a power name (private) or ALL (public). Keep it short."""
        return self._guard("send_press", {"to": to, "text": text}, lambda: self.p.send(to, text))

    def conversation(self, power: str) -> str:
        """Your private message thread with one power, all seasons (the briefing shows only this season)."""
        def run():
            thread = self.p.press_log.conversation(self.p.service.notation.country_id(power))
            return "\n".join(thread) or "(no private messages with this power yet)"
        return self._guard("conversation", {"power": power}, run)

    # --- knowledge -------------------------------------------------------------------------

    def facts(self, power: str) -> str:
        """Referee facts for one power, all game: every move or support it ordered into another power's unit or centre, and whether it succeeded. From adjudicated orders only."""
        def run():
            return self.p.facts.of(self.p.service.notation.power_name(self.p.service.notation.country_id(power)))
        return self._guard("facts", {"power": power}, run)

    def notes(self, key: str, text: str) -> str:
        """Write one note under KEY (replaces that note; empty text deletes it). Notes persist for the rest of the game and appear in every briefing. Use them for anything you want to remember: plans, deals, what a power wants."""
        return self._guard("notes", {"key": key, "text": text}, lambda: self.p.notes.write(key, text))

    def read_notes(self) -> str:
        """All your notes."""
        return self._guard("read_notes", {}, self.p.notes.read)

    def read_skill(self, name: str) -> str:
        """Load the full text of one skill listed in your instructions."""
        def run():
            path = self.p.skills_dir / name.strip() / "SKILL.md"
            if not path.is_file():
                raise ValueError(f"no skill named {name!r}")
            return path.read_text()
        return self._guard("read_skill", {"name": name}, run)

    def all(self):
        return [self.board, self.connections, self.predict, self.search, self.evaluate, self.assess_deal,
                self.commit_orders, self.send_press, self.conversation, self.facts, self.notes, self.read_notes,
                self.read_skill]
