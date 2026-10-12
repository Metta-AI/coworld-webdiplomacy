#!/usr/bin/env python3
"""What our press agent does with its policy and its messages, per version: a behaviour scorecard.

    python3 games/webdiplomacy/tools/press_behaviour.py DIR... [--policy NAME[:vN]] [--json]

Reads our own seat logs (the reference policy's `press_commit`, `press_out`, `wake` and
`decision` events) under the given artifact directories and prints one column per policy
version. It answers "did the prompt or guard change what the agent does", which a score
cannot: fixed orders, holds, stances, messages.

Rows of the table (one movement phase of one seat is one "phase"):

  phases                       movement phases with a decision line
  committed a policy           share of phases where the agent committed at least once
                               (the rest played the search floor)
  orders fixed                 `require_orders` entries as a share of the orders played, over
                               committed phases
  orders fixed as holds        the fixed orders that are holds, same denominator
  every unit fixed             share of committed phases where every unit was fixed (the
                               search chose nothing)
  holds                        holds as a share of the orders played, committed phases
  named a hostile power        share of committed phases whose policy has a `hostile` stance
  named an ally                the same for `ally`
  used centre values           share of committed phases with a `center_values` entry
  forbade a province           share of committed phases with `forbid_moves_into`
  listed expected orders       share of committed phases with `expected_orders`
  messages per phase           mean messages sent
  3+ messages to one power     share of phases with three or more messages to one recipient
  wakes per phase              mean agent wakes
  LLM cost per phase           mean `llm_cost_usd`, in dollars
  holds freed by the guard     `press_freed_holds` per committed phase (0 unless the build
                               sets PRESS_FREE_PINNED_HOLDS)

Counts only: they describe behaviour, not its cost. Scores come from `paired.py`,
`compare.py` and `matchups.py`. A share over fewer than about 30 phases is an anecdote.
Rival seats have no readable log and are left out. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import webdip_episodes as we  # noqa: E402

METRICS = [
    ("phases", "phases"),
    ("committed", "committed a policy"),
    ("fixed_share", "orders fixed"),
    ("fixed_hold_share", "orders fixed as holds"),
    ("all_fixed", "every unit fixed"),
    ("hold_share", "holds"),
    ("hostile", "named a hostile power"),
    ("ally", "named an ally"),
    ("center_values", "used centre values"),
    ("forbid", "forbade a province"),
    ("expected", "listed expected orders"),
    ("messages", "messages per phase"),
    ("repeat_to_one", "3+ messages to one power"),
    ("wakes", "wakes per phase"),
    ("cost", "LLM cost per phase"),
    ("freed_holds", "holds freed by the guard"),
]
COUNTS = {"phases"}
MEANS = {"messages", "wakes", "cost", "freed_holds"}


def is_hold(order_text: str) -> bool:
    """True for a hold in the policy's standard notation ("A BUL H")."""
    return order_text.split()[-1:] == ["H"]


def commit_shape(policy: dict | None, orders: list[str]) -> dict:
    """The countable facts of one committed policy and the orders it produced."""
    policy = policy or {}
    fixed = list(policy.get("require_orders") or [])
    stances = Counter(str(stance).lower() for stance in (policy.get("stances") or {}).values())
    return {
        "units": len(orders),
        "fixed": len(fixed),
        "fixed_holds": sum(is_hold(text) for text in fixed),
        "all_fixed": bool(orders) and len(fixed) >= len(orders),
        "holds": sum(is_hold(text) for text in orders),
        "hostile": stances["hostile"] > 0,
        "ally": stances["ally"] > 0,
        "center_values": bool(policy.get("center_values")),
        "forbid": bool(policy.get("forbid_moves_into")),
        "expected": bool(policy.get("expected_orders")),
    }


def phase_rows(events: list[dict]) -> list[dict]:
    """One row per movement phase of a seat log that has a `decision` line.

    The policy counted for a phase is the last one committed in it (the one in force at the
    lock). A phase with no commit has `committed` False and no order counts: the floor's
    orders are not in the log."""
    commits: dict[int, dict] = {}
    sent: dict[int, Counter] = {}
    wakes: Counter = Counter()
    for e in events:
        kind = e.get("event")
        if kind == "press_commit":
            commits[int(e["turn"])] = e
        elif kind == "press_out":
            sent.setdefault(int(e["turn"]), Counter())[e.get("to")] += 1
        elif kind == "wake":
            wakes[int(e["turn"])] += 1
    rows = []
    for e in events:
        if e.get("event") != "decision" or e.get("phase") != "Diplomacy":
            continue
        turn = int(e["turn"])
        to = sent.get(turn, Counter())
        row = {"turn": turn, "committed": turn in commits, "messages": sum(to.values()),
               "repeat_to_one": max(to.values(), default=0) >= 3, "wakes": wakes[turn],
               "cost": float(e.get("llm_cost_usd") or 0.0),
               "freed_holds": int((e.get("trace") or {}).get("press_freed_holds") or 0)}
        if turn in commits:
            row.update(commit_shape(commits[turn].get("press_policy"), commits[turn].get("orders") or []))
        rows.append(row)
    return rows


def summarize(rows: list[dict]) -> dict:
    """Aggregate phase rows into the scorecard's numbers (shares in 0..1, None when undefined)."""
    committed = [r for r in rows if r["committed"]]
    orders = sum(r["units"] for r in committed)

    def share(top, bottom):
        return top / bottom if bottom else None

    def of_committed(key):
        return share(sum(bool(r[key]) for r in committed), len(committed))

    def mean(key, over):
        return share(sum(r[key] for r in over), len(over))

    return {
        "phases": len(rows),
        "committed": share(len(committed), len(rows)),
        "fixed_share": share(sum(r["fixed"] for r in committed), orders),
        "fixed_hold_share": share(sum(r["fixed_holds"] for r in committed), orders),
        "all_fixed": of_committed("all_fixed"),
        "hold_share": share(sum(r["holds"] for r in committed), orders),
        "hostile": of_committed("hostile"),
        "ally": of_committed("ally"),
        "center_values": of_committed("center_values"),
        "forbid": of_committed("forbid"),
        "expected": of_committed("expected"),
        "messages": mean("messages", rows),
        "repeat_to_one": share(sum(r["repeat_to_one"] for r in rows), len(rows)),
        "wakes": mean("wakes", rows),
        "cost": mean("cost", rows),
        "freed_holds": mean("freed_holds", committed),
    }


def cell(key: str, value) -> str:
    if value is None:
        return "-"
    if key in COUNTS:
        return str(value)
    if key == "cost":
        return f"${value:.4f}"
    if key in MEANS:
        return f"{value:.2f}"
    return f"{100 * value:.0f}%"


def table(summaries: dict[str, dict], extra: list[tuple[str, str]] | None = None) -> str:
    """Markdown table: one row per metric, one column per label."""
    labels = list(summaries)
    lines = ["| | " + " | ".join(labels) + " |", "|---|" + "---|" * len(labels)]
    for key, title in METRICS + (extra or []):
        lines.append(f"| {title} | " + " | ".join(cell(key, summaries[label].get(key)) for label in labels) + " |")
    return "\n".join(lines)


def rows_by_version(roots: list[Path], policy: str | None) -> tuple[dict[str, list[dict]], Counter]:
    """Phase rows of every readable press seat under `roots`, keyed by `name:vN`."""
    by_version: dict[str, list[dict]] = {}
    seats: Counter = Counter()
    for root in roots:
        for ep in we.episode_dirs(root):
            episode = we.read_json_file(ep / "episode.json") if (ep / "episode.json").exists() else {}
            policies = we.seat_policies(ep, episode)
            for slot, path in we.seat_log_paths(ep).items():
                label = policies.get(slot, "local")
                if policy and label != policy and label.split(":")[0] != policy:
                    continue
                rows = phase_rows(we.read_log(path))
                if not any(r["wakes"] or r["committed"] for r in rows):
                    continue  # a search-only seat, or a press seat whose agent never ran
                by_version.setdefault(label, []).extend(rows)
                seats[label] += 1
    return by_version, seats


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dirs", nargs="+", type=Path, help="artifact directories (batches or episodes)")
    ap.add_argument("--policy", help="NAME (every version) or NAME:vN; default: every policy with a readable press log")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    by_version, seats = rows_by_version(args.dirs, args.policy)
    if not by_version:
        sys.exit("no press seat log found for that policy under the given directories")
    summaries = {label: summarize(rows) for label, rows in sorted(by_version.items())}
    if args.json:
        print(json.dumps({"seats": dict(seats), "versions": summaries}, indent=1))
        return
    print("# Press behaviour by version\n")
    print("seats read: " + ", ".join(f"{label} {n}" for label, n in sorted(seats.items())) + "\n")
    print(table(summaries))
    print("\nCounts only: behaviour, not its cost. A share over fewer than about 30 phases is an anecdote.")


if __name__ == "__main__":
    main()
