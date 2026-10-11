#!/usr/bin/env python3
"""Read one of our seats' own log for a turn: the press it got and sent, what it committed, what it played.

    python3 games/webdiplomacy/tools/seat_log.py DIR... --game EPISODE_ID --power Russia
        [--when A1902 | S1902-A1903] [--events press_in,press_out,commit,decision,wake,tool,error] [--chars 400]

`opponent_profile.py --game` prints the adjudicated orders, which are public. This prints the
other half for a seat whose log is on disk: why our bot did it. Per movement turn, in the
order the log wrote them:

  press_in    a message the seat received (sender, text)
  press_out   a message it sent (recipient, text)
  commit      each press policy it committed in the turn (`press_commit`: stances, trust,
              required and expected orders, forbidden provinces) with the orders the search
              then produced. Several commits in one turn show the agent changing its mind
  wake        each wake of the press agent: its kind, status, model calls, and its closing note
  tool        the agent's tool calls other than sending press (name, arguments, result)
  decision    the phase's final line: units, centres, `rejected`, the guard and search counters
              in `trace`, and the policy that was in force when orders locked
  error       `exception`, `http_error` and `wake_error` events, and failed `llm_call`s

The default shows everything except `tool`. EPISODE_ID may be a unique prefix. `--when` takes
`S1901`, `A1902`, a range `S1902-A1903`, a year or a range of years; without it the whole game
prints, which is long. Texts are cut at `--chars` characters (default 400; 0 for no cut).

**This output contains private press.** Read it in the terminal; never paste message text into
a report, an experiment record, a card or any other tracked file. Describe what was said in
your own words and cite the episode and turn.

Only seats whose log is on disk can be read: our own, or every seat of a batch that seats only
our account's policies. The event names are the reference policy's (its README lists the log
schema); a policy with another schema prints only the events it shares. Exit 2 when the game or
the seat's log is not found. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from board_counts import in_range, parse_when
from press_audit import turn_label
from webdip_episodes import POWERS, episode_dirs, load_episode, read_log, seat_log_paths

POWER_NAMES = tuple(POWERS.values())
KINDS = ("press_in", "press_out", "commit", "wake", "tool", "decision", "error")
DEFAULT_KINDS = tuple(k for k in KINDS if k != "tool")
POLICY_FIELDS = ("stances", "trust", "require_orders", "expected_orders", "forbid_moves_into", "center_values", "risk")
TRACE_FIELDS = ("press_commits", "press_sent", "wakes")


def find_episode(roots: list[Path], prefix: str) -> Path | None:
    matches = {ep.name: ep for root in roots for ep in episode_dirs(root) if ep.name.startswith(prefix)}
    if len(matches) > 1:
        raise SystemExit(f"{prefix} matches {len(matches)} episodes: give more of the id")
    return next(iter(matches.values()), None)


def cut(text, chars: int) -> str:
    text = text if isinstance(text, str) else json.dumps(text, sort_keys=True)
    text = " ".join(text.split())
    return text if not chars or len(text) <= chars else text[:chars] + " …"


def _wake_turn(row: dict) -> int | None:
    """A wake id reads `<turn>-<n>-<kind>`; `llm_call` and `tool_call` rows carry it and no `turn`."""
    head = str(row.get("wake") or "").split("-")[0]
    return int(head) if head.isdigit() else None


def events_by_turn(rows: list[dict], kinds: tuple[str, ...], chars: int) -> dict[int, list[str]]:
    """turn -> printable lines, in log order. Only movement phases have a turn that maps to a season."""
    out: dict[int, list[str]] = defaultdict(list)
    for row in rows:
        event = row.get("event")
        turn = row.get("turn")
        turn = int(turn) if turn is not None and str(turn).lstrip("-").isdigit() else _wake_turn(row)
        if turn is None:
            continue
        line = None
        if event == "press_in" and "press_in" in kinds:
            line = f"press in   from {row.get('frm')}: {cut(row.get('text', ''), chars)}"
        elif event == "press_out" and "press_out" in kinds:
            line = f"press out  to {row.get('to')}: {cut(row.get('text', ''), chars)}"
        elif event == "press_commit" and "commit" in kinds:
            policy = row.get("press_policy") or {}
            kept = {k: policy[k] for k in POLICY_FIELDS if policy.get(k)}
            line = f"commit     {cut(kept, chars)} -> orders {cut(row.get('orders') or [], chars)}"
        elif event == "wake" and "wake" in kinds:
            line = (f"wake       {row.get('kind')} {row.get('status')}, {row.get('calls')} calls: "
                    f"{cut(row.get('final') or '', chars)}")
        elif event == "tool_call" and "tool" in kinds and row.get("tool") != "send_press":
            line = (f"tool       {row.get('tool')}({cut(row.get('arguments') or '', chars)}) -> "
                    f"{cut(row.get('result') or '', chars)}")
        elif event == "decision" and "decision" in kinds:
            if row.get("phase") != "Diplomacy":
                continue  # retreats and builds share the turn number; the movement line is the one to read
            trace = row.get("trace") or {}
            shown = [k for k in TRACE_FIELDS if k in trace] + sorted(k for k in trace if k.endswith("_refused"))
            counters = ", ".join(f"{k} {trace[k]}" for k in shown)
            policy = row.get("press_policy")
            in_force = cut({k: policy[k] for k in POLICY_FIELDS if policy.get(k)}, chars) \
                if isinstance(policy, dict) else "none (the search floor played)" if "press_policy" in row \
                else "not logged (a search build)"
            line = (f"decision   {row.get('units')} units, {row.get('centers')} centres, rejected "
                    f"{row.get('rejected')}" + (f"; {counters}" if counters else "") + f"; policy in force: {in_force}")
        elif "error" in kinds and event in ("exception", "http_error", "wake_error"):
            line = f"ERROR      {event}: {cut(row.get('error') or row.get('message') or row, chars)}"
        elif "error" in kinds and event == "llm_call" and str(row.get("status")) not in ("200", "ok"):
            line = f"ERROR      llm_call status {row.get('status')}: {cut(row.get('error') or '', chars)}"
        if line:
            out[turn].append(line)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dirs", nargs="+", metavar="DIR")
    ap.add_argument("--game", required=True, metavar="EPISODE_ID", help="an episode id or a unique prefix of one")
    ap.add_argument("--power", required=True, choices=POWER_NAMES, help="the seat to read")
    ap.add_argument("--when", help="S1901, A1902, S1902-A1903, 1902 or 1901-1903 (default: the whole game)")
    ap.add_argument("--events", default=",".join(DEFAULT_KINDS), help=f"comma-separated, from: {', '.join(KINDS)}")
    ap.add_argument("--chars", type=int, default=400, help="cut each text at this many characters (0: no cut)")
    args = ap.parse_args(argv)
    kinds = tuple(k.strip() for k in args.events.split(",") if k.strip())
    if set(kinds) - set(KINDS):
        ap.error(f"unknown --events {sorted(set(kinds) - set(KINDS))}; choose from {', '.join(KINDS)}")
    try:
        when = parse_when(args.when)
    except ValueError as error:
        ap.error(str(error))
    ep = find_episode([Path(d) for d in args.dirs], args.game)
    if ep is None:
        print(f"no episode starting with {args.game} below the given directories", file=sys.stderr)
        return 2
    seats, _ = load_episode(ep)
    seat = next((s for s in seats if s.power == args.power), None)
    path = seat_log_paths(ep).get(seat.slot) if seat else None
    if path is None:
        print(f"{ep.name}: no log on disk for {args.power} (only our own seats' logs can be fetched)", file=sys.stderr)
        return 2
    rows = read_log(path)
    by_turn = events_by_turn(rows, kinds, args.chars)
    print(f"# {ep.name} {args.power} ({seat.policy}, seat {seat.slot}): score {seat.score:.3f}, "
          f"{seat.final_centers} centres" + (f", taint {','.join(seat.taint)}" if seat.taint else ""))
    print(f"log: {path} ({len(rows)} rows). Private press below: do not paste it into a tracked file.")
    shown = 0
    for turn in sorted(t for t in by_turn if in_range(t, when)):
        print(f"\n## {turn_label(turn)} (turn {turn})")
        print("\n".join(by_turn[turn]))
        shown += len(by_turn[turn])
    if not shown:
        print("\nno matching event in that range (a search build logs only `decision` lines; a seat whose pod was "
              "deleted has no log rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
