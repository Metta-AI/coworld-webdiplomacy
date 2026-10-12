#!/usr/bin/env python3
"""Replay recorded press wakes under a different prompt, model or setting, in minutes.

    python3 games/webdiplomacy/tools/wake_bench.py sample DIR... [--policy NAME[:vN]]... -n 100 --out CASES.json
        [--seed 0] [--case EPISODE_ID:POWER:WHEN ...]
    python3 games/webdiplomacy/tools/wake_bench.py run CASES.json --label NAME --out RUN_DIR
        [--overrides "KEY=VAL,..."] [--model SLUG] [--endpoint URL] [--scripted] [--limit N] [--workers 4]
    python3 games/webdiplomacy/tools/wake_bench.py report RUN_DIR... [--json]

A hosted game is the only place a prompt gets a score, and a seat's log can be read only
after its game ends, so the first sign of whether a prompt is even followed costs a whole
game. This tool gives that first sign from games already on disk. It is a **screen for
behaviour, never a verdict on score**: one wake has no consequences and no opponent reacts.

What a case is. The phase-start wake of one movement phase of one of our own seats: the
board (from the replay's public history), the order history before it, every message the
seat had received or sent by then, its notes and opponent beliefs as the seat logged them
after the phase before. `sample` picks cases at random (fixed `--seed`) from our seats under
DIR, and `--case` adds named ones (`--case ereq_0705...:Turkey:A1902`). The cases file holds
paths and clock positions only; keep it and every run under `.runtime/bench/`, not in
`tools/`.

What a run does. For each case it rebuilds that position, then plays the phase through the
reference policy's own code (`castlereagh.press.player.PressPlayer.movement_phase`): the
search floor, one agent wake with the real tools and the real search, the lock. No server
and no other player is involved; messages the agent sends go nowhere. The policy is the
source tree in `players/castlereagh`, with `--overrides` applied the way `tools/build.sh
--overrides` bakes them (`PRESS_SOUL=<your soul>`, `PRESS_REASONING=medium`, ...), so a run
tests exactly what a build of the working tree would play.

The model. With `--endpoint` (or `COWORLD_LLM_ENDPOINT` set) the agent is the policy's real
one, which needs pydantic-ai as the policy does:

    OPENROUTER_API_KEY=... python3 games/webdiplomacy/tools/llm_sidecar_local.py --port 9177 --ledger L.jsonl
    uv run --no-project --python 3.12 --with "pydantic-ai-slim[openai]==2.54.0" \\
        python games/webdiplomacy/tools/wake_bench.py run CASES.json --label my-soul \\
        --overrides "PRESS_SOUL=my-soul" --endpoint http://127.0.0.1:9177 --out .runtime/bench/my-soul

`--scripted` uses no model: a stand-in wake that commits an empty policy. It checks that
every case rebuilds and that the phase plays to the lock (run it before spending on a real
run). This tool itself is standard library only.

What the report shows. The behaviour scorecard of `tools/press_behaviour.py` (same functions,
same rows), one column per run, plus these bench-only rows:

  cases, and wakes that ended ok   the wake finished by itself.
  wakes that ran to a limit    the wake was cut off at its time limit or its limit on model calls
                               (`PRESS_WAKE_SECONDS`, `PRESS_REQUEST_LIMIT`). What the agent had
                               committed by then stands, as it does in a hosted game, so this is
                               a slow or long-winded prompt, not a broken run. The report says so
                               in a note when it is a tenth of the cases or more.
  (wakes that failed)          every other ending. When fewer than 90% of wakes ended ok or at a
                               limit the report says DO NOT READ above the table, with the first
                               model error: a failing model leaves every case on the search
                               floor and the table would still fill in. `run` plays one case
                               first and stops if its model calls fail.
  board rebuilt as recorded    share of cases whose rebuilt "Board" section equals the one in
                               the recorded briefing. Below 100% the bench is not replaying
                               what the seat saw: fix that before reading anything else.
  orders differ from the floor share of cases where the final orders are not the search floor's
  a re-search alone differs    the zero for the row above: the share of cases where the plain
                               search, run once more with no policy and its usual fresh random
                               draws, gives other orders than the floor. Every commit re-runs
                               the search that way, so an agent that changes nothing still
                               "differs" this often. Only the gap between the two rows is the
                               agent's doing.
  centres, final minus floor   mean difference in the search's own expected centres after this
                               phase (no policy, same opponent samples for both). Negative
                               means the agent's steering made the one-phase plan worse by
                               the search's own count; it says nothing about later phases or
                               about deals that pay off later.
  centres, re-search minus floor  the same difference for the plain re-search: the zero for the
                               row above.

Limits to state with any result: only phase-start wakes are replayed (a later wake's
briefing would carry the recorded agent's own commit); notes, messages and the board's
history were produced by the version that played the game, so a new prompt meets a past it
did not make; one wake per case, so run-to-run noise is real: compare runs on the same cases
file, and repeat a run before trusting a small gap.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import press_behaviour  # noqa: E402
import webdip_episodes as we  # noqa: E402

POLICY_SOURCE = Path(__file__).resolve().parents[1] / "players" / "castlereagh"
POWER_IDS = {name.upper(): cid for cid, name in we.POWERS.items()}
PHASE_SECONDS = 180.0  # a classic-press movement phase (240 before webDiplomacy Coworld 0.7.10)
BENCH_EXTRA = [
    ("cases", "cases"),
    ("wake_ok", "wakes that ended ok"),
    ("wake_limit", "wakes that ran to a limit"),
    ("board_matches", "board rebuilt as recorded"),
    ("changed", "orders differ from the floor"),
    ("research_changed", "a re-search alone differs"),
    ("centres_delta", "centres, final minus floor"),
    ("research_delta", "centres, re-search minus floor"),
]
LIMIT_ENDINGS = ("time_limit", "request_limit")  # the wake was cut off; what it had committed stands


# --- cases -----------------------------------------------------------------------------------

def turn_of(when: str) -> int:
    """"S1902" -> 2, "A1902" (or "F1902") -> 3."""
    season, year = when[0].upper(), int(when[1:])
    if season not in "SAF":
        raise ValueError(f"{when!r}: write a season as S1902 or A1902")
    return 2 * (year - 1901) + (0 if season == "S" else 1)


def movement_phase(phases: list[dict], turn: int) -> dict | None:
    return next((p for p in phases if p["phase"] == "Diplomacy" and int(p["turn"]) == turn and p.get("units")), None)


def seat_cases(ep: Path, policies_wanted: list[str] | None) -> list[dict]:
    """Every phase-start wake of our seats in one episode that the replay can rebuild."""
    replay_path, results_path = we.first_existing(ep, we.REPLAY_NAMES), we.first_existing(ep, we.RESULTS_NAMES)
    if replay_path is None or results_path is None:
        return []
    episode = we.read_json_file(ep / "episode.json") if (ep / "episode.json").exists() else {}
    policies = we.seat_policies(ep, episode)
    countries = [int(c) for c in we.read_json_file(results_path).get("countries") or []]
    phases = None
    cases = []
    for slot, log_path in we.seat_log_paths(ep).items():
        label = policies.get(slot, "local")
        if policies_wanted and label not in policies_wanted and label.split(":")[0] not in policies_wanted:
            continue
        turns = sorted({int(e["turn"]) for e in we.read_log(log_path)
                        if e.get("event") == "wake_start" and e.get("kind") == "phase_start"})
        if not turns or slot >= len(countries):
            continue
        if phases is None:
            phases = we.read_json_file(replay_path)[-1]["history"]["phases"]
        for turn in turns:
            if movement_phase(phases, turn):
                cases.append({"id": f"{ep.name}:{we.POWERS[countries[slot]]}:{turn}", "episode_dir": str(ep.resolve()),
                              "slot": slot, "country": countries[slot], "turn": turn, "policy": label})
    return cases


def sample_cases(roots: list[Path], policy: list[str] | None, n: int, seed: int, named: list[str]) -> list[dict]:
    pool = [case for root in roots for ep in we.episode_dirs(root) for case in seat_cases(ep, policy)]
    by_id = {case["id"]: case for case in pool}
    picked = []
    for spec in named:
        episode_id, power, when = spec.split(":")
        key = f"{episode_id}:{power.capitalize()}:{turn_of(when)}"
        if key not in by_id:
            raise ValueError(f"--case {spec}: no phase-start wake of ours found for it under the given directories")
        picked.append(by_id.pop(key))
    rest = sorted(by_id.values(), key=lambda case: case["id"])
    random.Random(seed).shuffle(rest)
    return picked + rest[:max(0, n - len(picked))]


# --- rebuilding one position (standard library only) -------------------------------------------

def board_section(briefing: str) -> str:
    """The briefing's "## Board" section, without the map connectivity that follows it."""
    start = briefing.find("## Board")
    if start < 0:
        return ""
    end = briefing.find("\n## ", start + 1)
    return briefing[start:end if end > 0 else None].strip()


def rebuild(case: dict) -> dict:
    """Everything the phase-start wake of `case` could see, from the replay and the seat log."""
    ep = Path(case["episode_dir"])
    replay = we.first_existing(ep, we.REPLAY_NAMES) if ep.is_dir() else None
    if replay is None:
        raise FileNotFoundError(f"no replay for this case under {ep}: a cases file holds paths to games on disk, "
                                f"so sample again if the games moved")
    frames = we.read_json_file(replay)
    phases = frames[-1]["history"]["phases"]
    turn, me = int(case["turn"]), int(case["country"])
    phase = movement_phase(phases, turn)
    units = [{"id": i + 1, "countryID": u["countryID"], "type": u["type"], "terrID": u["terrID"], "retreating": False}
             for i, u in enumerate(phase["units"]) if not u.get("retreating")]
    events = we.read_log(we.seat_log_paths(ep)[int(case["slot"])])
    start = next(e for e in events if e.get("event") == "wake_start" and e.get("kind") == "phase_start"
                 and int(e["turn"]) == turn)
    messages = []
    for e in events:
        if e.get("t", 0) > start["t"] or e.get("event") not in ("press_in", "press_out"):
            continue
        if e["event"] == "press_in":
            sender, to = POWER_IDS[e["frm"]], 0 if e.get("to") == "ALL" else me
        else:
            sender, to = me, 0 if e.get("to") == "ALL" else POWER_IDS[e["to"]]
        # Sent messages carry no id in the log, so ids are re-issued in arrival order.
        messages.append({"id": len(messages) + 1, "turn": int(e["turn"]), "fromCountryID": sender,
                         "toCountryID": to, "message": e["text"]})
    before = [e for e in events if e.get("event") == "workspace" and int(e.get("turn", turn)) < turn]
    notes = next((e["notes"] for e in reversed(before) if isinstance(e.get("notes"), dict)), {})
    beliefs = next((e["beliefs"] for e in reversed(before) if isinstance(e.get("beliefs"), dict)), {})
    request = next((e for e in events if e.get("event") == "llm_request" and e.get("wake") == start["wake"]), None)
    sent = (request or {}).get("messages", [])
    recorded = next((m.get("content") or "" for m in sent if m.get("role") == "user"), "")
    return {"variant": frames[-1]["variant"], "units": units, "centers": phase["centers"], "turn": turn,
            "country": me, "history": {"phases": [p for p in phases if int(p["turn"]) < turn]},
            "messages": messages, "notes": notes, "beliefs": beliefs, "recorded_board": board_section(recorded)}


# --- playing one case through the policy's own code ---------------------------------------------

class SkipClock:
    """Real time for a wake's limits; `sleep` skips ahead so idle waiting for the lock costs nothing."""

    def __init__(self):
        self.skipped = 0.0

    def __call__(self):
        return time.time() + self.skipped

    def sleep(self, seconds):
        self.skipped += seconds


class ReplayApi:
    """Stands in for the game server for one rebuilt phase: serves the position, records what is saved or sent."""

    def __init__(self, position: dict, board: dict, game_id: int, clock, phase_seconds: float):
        self.country_id, self.game_id = position["country"], game_id
        self.position, self.board = position, board
        self.slots = [{"unitID": u["id"]} for u in position["units"] if int(u["countryID"]) == position["country"]]
        self.deadline = clock() + phase_seconds
        self.saved, self.sent = [], []

    def context(self):
        return {"game": {"turn": self.position["turn"], "phase": "Diplomacy", "pressType": "Regular",
                         "processTime": self.deadline},
                "orders": {"orders": self.slots},
                "messages": {"messages": list(self.position["messages"])},
                "files": {"game": {"url": "game"}, "variant": {"url": "variant"}, "history": {"url": "history"}}}

    def file(self, ref):
        return {"game": {**self.board, "turn": self.position["turn"], "phase": "Diplomacy"},
                "variant": self.position["variant"], "history": self.position["history"]}[ref["url"]]

    def orders(self, context, orders, ready="Yes"):
        self.saved.append((ready, list(orders)))
        return list(orders)

    def request(self, route, body=None, **params):
        self.sent.append(body)
        return {}


def scripted_wake(player):
    """The `--scripted` stand-in for a model: commit an empty policy, send nothing."""
    def run_wake(agent, prompt, seconds, limit):
        player.commit({})
        return "scripted: committed an empty policy", "ok"
    return run_wake


def run_case(case: dict, index: int, wake_factory=None, phase_seconds: float = PHASE_SECONDS) -> dict:
    """Play one case. `wake_factory(player)` returns a `run_wake` stand-in; None uses the policy's
    real agent (needs COWORLD_LLM_ENDPOINT and pydantic-ai). Returns {"row": ..., "events": [...]}."""
    sys.path.insert(0, str(POLICY_SOURCE))
    from castlereagh import bot, config, golden
    from castlereagh.press.player import PressPlayer

    position = rebuild(case)
    events, briefings = [], []
    clock = SkipClock()
    with tempfile.TemporaryDirectory() as state_dir:
        config.PRESS_STATE_DIR = state_dir
        api = ReplayApi(position, golden._board(position["variant"], position["units"], position["centers"]),
                        index + 1, clock, phase_seconds)
        notes_file = Path(state_dir) / f"{api.game_id}-{api.country_id}" / "notes.json"
        notes_file.parent.mkdir(parents=True)
        notes_file.write_text(json.dumps(position["notes"]))

        def log(**fields):
            events.append({"t": round(clock(), 1), **fields})

        if wake_factory is None:
            player = PressPlayer("wake-bench", api, 0, log, clock=clock, sleep=clock.sleep)
            real = player.run_wake
        else:
            player = PressPlayer("wake-bench", api, 0, log, agent=object(), clock=clock, sleep=clock.sleep)
            real = wake_factory(player)

        def run_wake(agent, prompt, seconds, limit):
            briefings.append(prompt)
            return real(agent, prompt, seconds, limit)

        player.run_wake = run_wake
        player.state["search"] = {"logodds": dict(position["beliefs"]), "pending": None}
        player.play(api.context(), bot.play_phase)

        row = {"case": case["id"], "power": we.POWERS[position["country"]], **press_behaviour.phase_rows(events)[0]}
        wakes = [e for e in events if e.get("event") == "wake"]
        row["wake_ok"] = bool(wakes) and wakes[0].get("status") == "ok"
        row["wake_status"] = wakes[0].get("status") if wakes else "no wake"
        row["wake_limit"] = row["wake_status"] in LIMIT_ENDINGS
        failed = [e for e in events if e.get("event") == "llm_call" and e.get("status") != 200]
        row["llm_failed"] = len(failed)
        if failed:
            row["llm_error"] = f'HTTP {failed[0].get("status")}: {str(failed[0].get("error"))[:200]}'
        row["board_matches"] = (board_section(briefings[0]) == position["recorded_board"]
                                if briefings and position["recorded_board"] else None)
        render = player.service.notation.render
        floor, final = [render(o) for o in api.saved[0][1]], [render(o) for o in player.orders]
        row["changed"] = sorted(floor) != sorted(final)
        # The zero for `changed`: every commit re-runs the search with fresh random draws, so the
        # plain search run once more, with no policy, already gives other orders some of the time.
        research = [render(o) for o in player.service.search(None)[0]]
        row["research_changed"] = sorted(floor) != sorted(research)
        row["centres_delta"] = row["research_delta"] = None
        try:
            scores = []
            for orders in (floor, final, research):
                player.service.calls = 10_000  # the same RNG key, so all are scored on the same opponent samples
                scores.append(player.service.evaluate(orders, None)[1]["expected_centres"])
            row["centres_delta"] = round(scores[1] - scores[0], 3)
            row["research_delta"] = round(scores[2] - scores[0], 3)
        except ValueError:
            pass  # an order the notation cannot read back; the row keeps its other fields
        row["final_orders"], row["floor_orders"] = final, floor
        row["sent"] = [body.get("message") for body in api.sent if body]
    return {"row": row, "events": events}


def _worker(job):
    case, index, overrides, scripted = job
    sys.path.insert(0, str(POLICY_SOURCE))
    from castlereagh import bot
    if overrides:
        bot.apply_overrides(overrides)
    try:
        return run_case(case, index, scripted_wake if scripted else None)
    except Exception as error:  # noqa: BLE001  one bad case must not lose a paid run
        return {"row": {"case": case["id"], "error": repr(error)[:300]}, "events": []}


# --- read-out ------------------------------------------------------------------------------------

def summarize(rows: list[dict]) -> dict:
    """The scorecard of `press_behaviour.summarize`, plus the bench-only numbers."""
    played = [r for r in rows if "error" not in r]

    def share(key):
        known = [r[key] for r in played if r.get(key) is not None]
        return sum(bool(v) for v in known) / len(known) if known else None

    def mean(key):
        known = [r[key] for r in played if r.get(key) is not None]
        return sum(known) / len(known) if known else None

    return {**press_behaviour.summarize(played), "cases": len(rows), "errors": len(rows) - len(played),
            "wake_ok": share("wake_ok"), "wake_limit": share("wake_limit"),
            "board_matches": share("board_matches"), "changed": share("changed"),
            "research_changed": share("research_changed"),
            "centres_delta": mean("centres_delta"), "research_delta": mean("research_delta")}


MIN_WAKES_OK = 0.9  # below this share of wakes ending ok or at a limit, a run describes the failures, not the prompt
LIMIT_NOTE = 0.1    # from this share of wakes cut off at a limit, the report says so


def validity(summary: dict, rows: list[dict]) -> str | None:
    """Why a run must not be read, or None. A failing model leaves every case on the search floor
    and the table still fills in, so the check is made here and printed above the table."""
    problems = []
    if summary["errors"]:
        problems.append(f'{summary["errors"]} of {summary["cases"]} cases could not be played')
    finished = None if summary["wake_ok"] is None else summary["wake_ok"] + (summary.get("wake_limit") or 0)
    if finished is not None and finished < MIN_WAKES_OK:
        reason = next((r["llm_error"] for r in rows if r.get("llm_error")), None)
        problems.append(f'only {100 * finished:.0f}% of wakes ended ok or at a limit'
                        + (f" (first model error: {reason})" if reason else ""))
    if summary["board_matches"] is not None and summary["board_matches"] < 1:
        problems.append(f'the board was rebuilt as recorded in only {100 * summary["board_matches"]:.0f}% of cases')
    return "; ".join(problems) or None


def limit_note(label: str, summary: dict) -> str | None:
    """A line for a run where many wakes were cut off at a limit: readable, but say what it is."""
    share = summary.get("wake_limit") or 0
    if share < LIMIT_NOTE:
        return None
    return (f"Note on `{label}`: {100 * share:.0f}% of wakes ran to their time or request limit. What the agent "
            f"had committed by then is what the rows count, as in a hosted game: a slow prompt, not a failed run.")


def bench_cell(key: str, value) -> str:
    if value is None:
        return "-"
    if key == "cases":
        return str(value)
    if key in ("centres_delta", "research_delta"):
        return f"{value:+.2f}"
    return f"{100 * value:.0f}%"


def report(run_dirs: list[Path]) -> tuple[dict[str, dict], str]:
    summaries, warnings = {}, []
    for run_dir in run_dirs:
        saved = json.loads((run_dir / "rows.json").read_text())
        summaries[saved["label"]] = summarize(saved["rows"])
        problem = validity(summaries[saved["label"]], saved["rows"])
        summaries[saved["label"]]["not_valid"] = problem
        if problem:
            warnings.append(f"**DO NOT READ the `{saved['label']}` column: {problem}.**")
        elif note := limit_note(saved["label"], summaries[saved["label"]]):
            warnings.append(note)
    labels = list(summaries)
    lines = warnings + ([""] if warnings else []) + [press_behaviour.table(summaries)]
    for key, title in BENCH_EXTRA:
        cells = " | ".join(bench_cell(key, summaries[label].get(key)) for label in labels)
        lines.append(f"| {title} | {cells} |")
    return summaries, "\n".join(lines)


# --- command line ----------------------------------------------------------------------------------

def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    s = sub.add_parser("sample", help="pick cases from our seats under DIR")
    s.add_argument("dirs", nargs="+", type=Path)
    s.add_argument("--policy", action="append", metavar="NAME[:vN]",
                   help="NAME (every version) or NAME:vN; repeatable; default: every seat with a press log")
    s.add_argument("-n", type=int, default=100, help="cases in all, the named ones included")
    s.add_argument("--seed", type=int, default=0)
    s.add_argument("--case", action="append", default=[], metavar="EPISODE_ID:POWER:WHEN",
                   help="always include this phase, e.g. ereq_0705...:Turkey:A1902; repeatable")
    s.add_argument("--out", required=True, type=Path)
    r = sub.add_parser("run", help="play the cases under one label")
    r.add_argument("cases", type=Path)
    r.add_argument("--label", required=True, help="name of this run in the report")
    r.add_argument("--out", required=True, type=Path, help="run directory: rows.json and one events file per case")
    r.add_argument("--overrides", default="", help='config overrides, "KEY=VAL,KEY=VAL", as tools/build.sh takes them')
    r.add_argument("--model", help="model slug (sets COWORLD_LLM_MODEL); default: the policy's PRESS_MODEL")
    r.add_argument("--endpoint", help="LLM sidecar URL (sets COWORLD_LLM_ENDPOINT), e.g. http://127.0.0.1:9177")
    r.add_argument("--scripted", action="store_true", help="no model: a stand-in wake that commits an empty policy")
    r.add_argument("--limit", type=int, help="play only the first N cases")
    r.add_argument("--workers", type=int, default=4)
    p = sub.add_parser("report", help="the behaviour table, one column per run")
    p.add_argument("runs", nargs="+", type=Path)
    p.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.command == "sample":
        cases = sample_cases(args.dirs, args.policy, args.n, args.seed, args.case)
        if not cases:
            sys.exit("no phase-start wake of that policy found: the seats need a press log and a replay")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({"seed": args.seed, "policy": args.policy, "cases": cases}, indent=1))
        powers = sorted({we.POWERS[c["country"]] for c in cases})
        print(f"wrote {len(cases)} cases to {args.out}: {len({c['episode_dir'] for c in cases})} games, "
              f"{len(powers)} powers, turns {min(c['turn'] for c in cases)} to {max(c['turn'] for c in cases)}")
    elif args.command == "run":
        import os
        if args.endpoint:
            os.environ["COWORLD_LLM_ENDPOINT"] = args.endpoint
        if args.model:
            os.environ["COWORLD_LLM_MODEL"] = args.model
        if not args.scripted and not os.environ.get("COWORLD_LLM_ENDPOINT"):
            sys.exit("no model: give --endpoint (see llm_sidecar_local.py) or --scripted")
        cases = json.loads(args.cases.read_text())["cases"][:args.limit]
        jobs = [(case, i, args.overrides, args.scripted) for i, case in enumerate(cases)]
        # One case first: a model that fails every call would otherwise fail the whole run case by case.
        with ProcessPoolExecutor(max_workers=1) as pool:
            first = pool.submit(_worker, jobs[0]).result()["row"]
        if first.get("llm_failed") and not first.get("wake_ok"):
            sys.exit(f"stopped before the run: the first case's model calls failed ({first.get('llm_error')}). "
                     "Nothing was written.")
        args.out.mkdir(parents=True, exist_ok=True)
        rows = []
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            for case, result in zip(cases, pool.map(_worker, jobs)):
                rows.append(result["row"])
                name = case["id"].replace(":", "_") + ".jsonl"
                (args.out / name).write_text("".join(json.dumps(e) + "\n" for e in result["events"]))
                print(f"{len(rows)}/{len(cases)} {case['id']}" + (f" ERROR {result['row']['error']}"
                      if "error" in result["row"] else ""), file=sys.stderr)
        (args.out / "rows.json").write_text(json.dumps(
            {"label": args.label, "overrides": args.overrides, "scripted": args.scripted,
             "model": None if args.scripted else (args.model or "policy default"),
             "cases_file": str(args.cases), "rows": rows}, indent=1))
        print(report([args.out])[1])
    else:
        summaries, text = report(args.runs)
        print(json.dumps(summaries, indent=1) if args.json else text)


if __name__ == "__main__":
    main()
