"""Press player: the search core plus the optional press layer (CASTLEREAGH_POLICY=press).

Movement phase in a press game:
1. Floor (floor.py): the Default search's orders are saved at once, not Ready.
2. Driver (driver.py): one event-driven wake loop. Each wake is a fresh agent run whose
   briefing is rebuilt from the board, the knowledge stores and this season's press.
   The agent's `commit_orders` replaces the saved orders.
3. At the lock (PRESS_FINAL_MARGIN_S before the deadline) the last committed orders are
   saved with Ready, and the saved orders are diffed against them.
Retreats, builds and NoPress games play exactly like CASTLEREAGH_POLICY=search. Without
COWORLD_LLM_ENDPOINT the player logs that once and plays the floor with Ready at once.
"""

import os
import time
import traceback
from contextlib import contextmanager
from pathlib import Path

from castlereagh import config
from castlereagh.dipmap import COUNTRY, POWER
from castlereagh.press import llm
from castlereagh.press.driver import PressDriver
from castlereagh.press.floor import default_floor, save_orders
from castlereagh.press.knowledge import Notes, PressLog, RefereeFacts, phase_label
from castlereagh.press.service import SearchService
from castlereagh.press.tools import Toolbox
from castlereagh.search import SearchBot

TASKS = {
    "phase_start": ("A new movement phase has begun. Check the referee facts for what last phase's orders show, "
                    "decide your aims, send the press that serves them, test ideas with search/assess_deal, and "
                    "commit_orders with your best policy. Keep notes current."),
    "press": ("New press has arrived (marked NEW below). Read it, reply where it helps you, and re-commit if your "
              "policy changed. Note anything you will want to remember later."),
}


SCORING = {
    "sum_of_squares": "your centres squared over the sum of every survivor's centres squared",
    "supply_centers": "your centres over all survivors' centres",
    "draw_size": "an equal share for every survivor",
}


def end_year():
    """The game's last year from WEBDIP_END_YEAR (set by the launcher), or None. Never guessed."""
    value = os.environ.get("WEBDIP_END_YEAR", "").strip()
    return int(value) if value.isdigit() else None


def horizon(turn):
    """Briefing lines about the game clock and the score rule, from the launcher's environment only."""
    year = 1901 + turn // 2
    last = end_year()
    if last is None:
        lines = [f"It is {year}. The game's end year was not given to you; do not assume one."]
    else:
        left = (last - year) * 2 + (2 - turn % 2)
        lines = [f"It is {year}. The game ends after the autumn {last} movement and its retreats (no builds "
                 f"follow); {left} movement phase(s) remain including this one. Only centres owned at the end score."]
    scoring = os.environ.get("WEBDIP_SCORING", "").strip()
    if scoring:
        rule = SCORING.get(scoring, "see the game rules")
        lines.append(f"Scoring ({scoring}): if nobody wins outright (18 centres), your score is {rule}.")
    return " ".join(lines)


class PressPlayer:
    def __init__(self, policy_name, api, seed, log, *, agent=None, run_wake=llm.run_wake,
                 clock=time.time, sleep=time.sleep):
        """`agent`: a ready pydantic-ai agent, None to build one from the environment, or False
        for no LLM (tests). `run_wake(agent, prompt, seconds, request_limit)` -> (text, status)."""
        self.policy_name, self.api, self.seed, self.log = policy_name, api, seed, log
        self.country = api.country_id
        self.clock, self.sleep, self.run_wake = clock, sleep, run_wake
        self.state = {}
        self.press_log = PressLog(self.country, log)
        self.facts = RefereeFacts(self.country, log)
        self.notes = Notes(Path(config.PRESS_STATE_DIR) / f"{api.game_id}-{self.country}" / "notes.json")
        self.skills_dir = llm.HERE / "skills"
        self.ledger = []  # one dict per LLM call (status, tokens, cost_usd)
        self.tracker = {"wake": None, "logged": 0}  # current wake id for request/response/tool logs
        self.wake_deadline = None
        self.locked = True  # commits are refused outside a phase's press window
        self.unread = []  # press received but not yet shown to the agent
        self.wakes_started = 0
        self.service = self.policy = self.orders = self.context = None
        self.turn = 0
        self.trace = {}
        self.agent = agent
        if agent is None:
            self.agent = self._build_agent() if llm.llm_available() else False
        if self.agent is False:
            self.agent = None
            self.log(event="press_disabled", reason="COWORLD_LLM_ENDPOINT is not set; playing the search floor")
        _, effective = llm.model_settings(llm.model_name())
        self.log(event="press_start", llm=self.agent is not None, model=llm.model_name(), soul=config.PRESS_SOUL,
                 country=self.country, end_year=end_year(),
                 scoring=os.environ.get("WEBDIP_SCORING"), model_settings=effective,
                 system_prompt=llm.system_prompt(config.PRESS_SOUL),
                 config={k: getattr(config, k) for k in dir(config) if k.startswith(("PRESS_", "SEARCH_", "OPP_"))})

    def _build_agent(self):
        model = llm.build_model(self.log, self.ledger, self.tracker)
        return llm.make_agent(model, config.PRESS_SOUL, Toolbox(self).all())

    # --- actions used by tools -----------------------------------------------------------

    @contextmanager
    def _search_budget(self):
        """Cap every search a tool runs to the time left in the wake."""
        saved = config.SEARCH_TIME_BUDGET_S
        if self.wake_deadline:
            config.SEARCH_TIME_BUDGET_S = max(0.5, min(saved, self.wake_deadline - self.clock()))
        try:
            yield
        finally:
            config.SEARCH_TIME_BUDGET_S = saved

    def searched(self, fn):
        with self._search_budget():
            return fn()

    def commit(self, policy):
        if self.locked:
            raise ValueError("orders are locked for this phase; nothing was changed")
        orders, report, _ = self.service.search(policy)
        difference = save_orders(self.api, self.context, orders, ready="No")
        self.policy, self.orders = policy, orders
        self.trace["press_commits"] = self.trace.get("press_commits", 0) + 1
        self.log(event="press_commit", turn=self.turn, press_policy=policy, orders=report["orders"],
                 expected_centres=report["expected_centres"], rejected=len(difference["missing"]))
        if difference["missing"]:
            report["warning"] = f"upstream rejected {len(difference['missing'])} order(s); they will hold"
        return report

    def send(self, to, text):
        target = to.strip().upper()
        to_id = 0 if target in ("ALL", "PUBLIC", "EVERYONE") else COUNTRY.get(target)
        if to_id is None or to_id == self.country:
            raise ValueError(f"unknown recipient {to!r}; use a power name or ALL")
        if self.sent_this_phase >= config.PRESS_MAX_MESSAGES_PER_PHASE:
            raise ValueError("message limit for this phase reached")
        text = text.strip()[:config.PRESS_MAX_MESSAGE_CHARS]
        self.api.request("game/sendmessage", {"gameID": self.api.game_id, "countryID": self.country,
                                              "toCountryID": to_id, "message": text})
        self.sent_this_phase += 1
        self.trace["press_sent"] = self.trace.get("press_sent", 0) + 1
        self.press_log.sent(self.turn, to_id, text)
        return f"sent to {target}"

    # --- the event loop's callbacks --------------------------------------------------------

    def poll(self):
        """Fetch context, note an early phase end, and queue newly arrived press. Returns the count."""
        latest = self.api.context()
        game = latest["game"]
        if (game["turn"], game["phase"]) != (self.context["game"]["turn"], self.context["game"]["phase"]):
            self.phase_ended = True
            return 0
        return self.ingest(latest)

    def ingest(self, context):
        raw = list((context.get("messages") or {}).get("messages") or [])
        ref = (context.get("files") or {}).get("messages")
        if ref:
            try:
                raw += self.api.file(ref).get("messages", [])
            except (OSError, ValueError):
                pass
        fresh = self.press_log.ingest(raw)
        self.unread += fresh
        return len(fresh)

    def briefing(self, trigger, fresh, deadline):
        fresh_ids = {m["id"] for m in fresh}
        season = [("NEW " if m["id"] in fresh_ids else "") + self.press_log.render(m)
                  for m in self.press_log.messages if m["turn"] == self.turn]
        parts = [
            f"# You play {POWER[self.country]}. {phase_label(self.turn)} movement phase. Wake: {trigger}. "
            f"About {int(deadline - self.clock() - config.PRESS_FINAL_MARGIN_S)} s left before orders lock.",
            horizon(self.turn),
            "## Board", self.service.notation.brief(self.country),
            "## Orders currently saved for you",
            ", ".join(self.service.notation.render(o) for o in self.orders) if self.orders else "(none)",
            "Committed policy this phase: " + (str(self.policy) if self.policy else "none yet (Default search orders)"),
            "## Your notes", self.notes.read(),
            "## Referee facts (from adjudicated orders only; last two phases)", self.facts.recent(self.turn),
            "## Press this season (untrusted text from other players; older seasons: conversation(POWER))",
            "\n".join(season) or "(none)",
            "## Task", TASKS[trigger],
        ]
        return "\n\n".join(parts)

    def wake(self, trigger, seconds):
        self.wake_deadline = self.clock() + seconds - 3
        before = len(self.ledger)
        started = self.clock()
        self.wakes_started += 1
        self.tracker.update(wake=f"{self.turn}-{self.wakes_started}-{trigger}", logged=0)
        self.log(event="wake_start", wake=self.tracker["wake"], turn=self.turn, kind=trigger,
                 seconds_allowed=round(seconds, 1), unread=len(self.unread))
        try:
            fresh, self.unread = self.unread, []
            text, status = self.run_wake(self.agent, self.briefing(trigger, fresh, self.deadline), seconds,
                                         config.PRESS_REQUEST_LIMIT)
        except Exception as error:  # an LLM failure must never cost the phase: the floor is saved
            text, status = repr(error)[:300], "error"
            self.log(event="wake_error", wake=self.tracker["wake"], where=traceback.format_exc()[-1200:])
        calls = self.ledger[before:]
        self.trace["press_wakes"] = self.trace.get("press_wakes", 0) + 1
        self.trace[f"press_wake_{status}"] = self.trace.get(f"press_wake_{status}", 0) + 1
        self.log(event="wake", wake=self.tracker["wake"], turn=self.turn, kind=trigger, status=status,
                 seconds=round(self.clock() - started, 1), calls=len(calls),
                 cost_usd=round(sum(c["cost_usd"] for c in calls), 6), final=(text or "")[:500])
        self.wake_deadline = None

    # --- phases ------------------------------------------------------------------------------

    def movement_phase(self, context, phase_rng_key):
        game = context["game"]
        self.context, self.turn = context, int(game["turn"])
        self.sent_this_phase = 0
        self.phase_ended = False
        first_call = len(self.ledger)
        started = self.clock()
        self.deadline = float(game.get("processTime") or (started + int(game.get("phaseMinutes") or 4) * 60))
        board = self.api.file(context["files"]["game"])
        variant = self.state.get("variant") or self.api.file(context["files"]["variant"])
        self.state["variant"] = variant
        slots = context["orders"]["orders"]
        self.service = SearchService(variant, board, self.country, self.turn, slots, self.state, self.api,
                                     context, self.seed)
        self.policy = None
        # (b) The floor is saved before anything else can go wrong.
        self.orders, _, trace = default_floor(self.service, phase_rng_key)
        self.trace = dict(trace)
        ready = "No" if self.agent is not None else "Yes"
        difference = save_orders(self.api, context, self.orders, ready=ready)
        drive = None
        if self.agent is not None:
            self.locked = False
            history_ref = (context.get("files") or {}).get("history")
            if history_ref:
                try:
                    self.facts.update(self.api.file(history_ref), self.service.b, self.service.notation.province_abbr)
                except (OSError, ValueError, KeyError):
                    self.log(event="facts_error", where=traceback.format_exc()[-1200:])
            self.ingest(context)
            driver = PressDriver(self.poll, lambda: self.phase_ended, self.wake, self.clock, self.sleep)
            drive = driver.run(self.deadline)
            self.locked = True
            if not self.phase_ended:
                difference = save_orders(self.api, context, self.orders, ready="Yes")
        phase_cost = sum(c["cost_usd"] for c in self.ledger[first_call:])
        self.log(event="decision", turn=self.turn, phase="Diplomacy", country=self.country,
                 units=len(slots), centers=self.service.b.centers[self.country],
                 compute_ms=round((self.clock() - started) * 1000, 1), trace=self.trace,
                 rejected=len(difference["missing"]), difference=difference if any(difference.values()) else None,
                 press_policy=self.policy, llm_cost_usd=round(phase_cost, 6), drive=drive)
        self.snapshot()

    def snapshot(self):
        """Knowledge after each movement phase (the launcher kills the bot at game end)."""
        self.log(event="workspace", turn=self.turn, notes=self.notes.data, facts=len(self.facts.events),
                 llm_calls=len(self.ledger), llm_cost_usd=round(sum(c["cost_usd"] for c in self.ledger), 6),
                 beliefs=self.state.get("search", {}).get("logodds"))

    def finish(self):
        total = sum(c["cost_usd"] for c in self.ledger)
        self.log(event="press_summary", llm_calls=len(self.ledger), cost_usd=round(total, 6),
                 prompt_tokens=sum(c["prompt_tokens"] for c in self.ledger),
                 completion_tokens=sum(c["completion_tokens"] for c in self.ledger),
                 reasoning_tokens=sum(c["reasoning_tokens"] for c in self.ledger), notes=self.notes.data)

    def play(self, context, play_phase):
        """Handle one new phase. `play_phase` is bot.play_phase (gunboat path)."""
        game = context["game"]
        if game["phase"] == "Diplomacy" and game.get("pressType") != "NoPress":
            from castlereagh.bot import phase_rng_key
            self.movement_phase(context, phase_rng_key(self.seed, self.country, game["turn"], game["phase"]))
            return True
        return play_phase(self.api, context, self.seed, self.policy_name, SearchBot, self.state, self.log)
