#!/usr/bin/env python3
"""Load webDiplomacy episode directories into per-seat records (the lab's one parser).

Every other tool here (`wd.py`, `paired.py`, `compare.py`) reads episodes through
this module. Standard-library Python 3.12+; import it from a script in this folder.

Inputs (any mix; pass a directory and every episode below it is found):
- Hosted episodes downloaded by the seed's `fetch-artifacts` skill:
  `.runtime/artifacts/<xreq>/<ereq>/` with `episode.json`, `results.json`,
  `replay.json` or `replay.bin` (plain or gzip JSON), and our own seat logs in
  `policy-logs/<policy_version_id>.<slot>.log`.
- Local `coworld run-episode` output (from `wd.py local` / `wd.py arena` or by hand):
  `results.json`, `replay` (plain or gzip JSON), `logs/policy_agent_<slot>.log`,
  and, when `wd.py` wrote it, `seating.json` (one label per slot).
A directory is an episode when it holds a `results*` file or `episode.json`;
otherwise its subdirectories are searched.

Output: one `Seat` per slot. The seat's `policy` is `name:vN` for hosted episodes
(from episode.json participants), the `seating.json` label for local runs, else
"local". Always stratify by `power`: countries are a seeded shuffle per episode and
the powers differ a lot in strength.

Format facts (webdiplomacy 0.7.7-0.7.8, verified on hosted and local artifacts):
- results.json `scores` and `countries` are in slot order; `members[].countryID` and
  `members[].supplyCenterNo` are strings; `outcome` is drawn | won | cancelled.
- Final supply centres come from results.json `members[].supplyCenterNo`. The replay's
  last `Finished` history entry shows ownership from before the final autumn.
- The replay is a JSON array of public frames; the last frame's `history.phases[]`
  holds per-phase `centers` (every owned territory, not only supply centres) and
  adjudicated `orders` with `success` / `dislodged`.
- Hosted seat logs sometimes arrive as a Python bytes literal (`b'...'`).

Our policy's log schema (the reference policy keeps the lab's): one JSON object per
line with `event`. `decision` (one per phase, `rejected` = orders upstream silently
dropped), `exception`, `http_error`, `llm_call` (`status`, cost in `cost_usd` or
`usage.cost`). The bundled random bot logs `orders_saved` with `rejected`.

Taint flags on a seat (drop or flag before computing means):
  cancelled         the game was cancelled (every seat scores 1/7)
  episode_failed    the hosted episode row is failed / error / cancelled
  rejected_orders   our decision log shows upstream dropped at least one order
  exception         our seat log has an `exception` event
  llm_failing       at least half of the seat's `llm_call`s failed: the seat silently
                    played its non-LLM floor
Seats without a log (rivals' hosted logs are private) cannot carry log taints.

Example:
    from webdip_episodes import load_dirs
    seats, statuses = load_dirs([Path(".runtime/artifacts/xreq_...")])
"""

from __future__ import annotations

import ast
import gzip
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

POWERS = {1: "England", 2: "France", 3: "Italy", 4: "Germany", 5: "Austria", 6: "Turkey", 7: "Russia"}
SOLO_CENTERS = 18
LLM_FAILING_SHARE = 0.5  # a seat with at least this share of failed llm_calls is tainted
FAILED_EPISODE_STATUSES = {"failed", "error", "cancelled"}

RESULTS_NAMES = ("results.json", "results.bin", "results")
REPLAY_NAMES = ("replay.json", "replay.json.gz", "replay.gz", "replay.bin", "replay")
HOSTED_LOG = re.compile(r"^(?P<pvid>.+)\.(?P<slot>\d+)\.log$")


@dataclass
class Seat:
    episode_id: str
    slot: int
    policy: str  # "name:vN" (hosted), seating.json label (local), or "local"
    power: str
    score: float
    final_centers: int | None  # from results.json members, never from the replay
    survived: bool | None
    solo: bool
    outcome: str
    reason: str
    final_year: int | None
    centers_by_year: dict[int, int] = field(default_factory=dict)  # supply centres after each autumn
    orders: int = 0  # movement orders adjudicated (public history)
    orders_failed: int = 0  # non-hold movement orders that did not succeed (bounced, cut)
    dislodged: int = 0
    log: dict = field(default_factory=dict)  # our policy's telemetry; empty when no seat log
    taint: list[str] = field(default_factory=list)


def read_json_file(path: Path):
    """Parse a JSON file that may be gzip-compressed regardless of its name."""
    data = path.read_bytes()
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return json.loads(data)


def read_log(path: Path | None) -> list[dict]:
    """JSON-object lines of a seat log; decodes a whole-file Python bytes literal."""
    if path is None or not path.exists():
        return []
    text = path.read_text(errors="replace")
    if text.startswith(("b'", 'b"')):
        text = ast.literal_eval(text.strip()).decode(errors="replace")
    rows = []
    for line in text.splitlines():
        if line.startswith("{"):
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
    return rows


def llm_call_failed(call: dict) -> bool:
    status = call.get("status")
    return (status is not None and int(status) != 200) or bool(call.get("error"))


def llm_call_cost(call: dict) -> float:
    if "cost_usd" in call:
        return float(call.get("cost_usd") or 0.0)
    return float((call.get("usage") or {}).get("cost") or 0.0)


def summarize_log(rows: list[dict]) -> dict:
    """Aggregate our policy's stdout telemetry."""
    decisions = [r for r in rows if r.get("event") == "decision"]
    legacy = [r for r in rows if r.get("event") == "orders_saved"]  # bundled random bot
    calls = [r for r in rows if r.get("event") == "llm_call"]
    trace = Counter()
    for d in decisions:
        trace.update(d.get("trace") or {})
    return {
        "decisions": len(decisions) or len(legacy),
        "rejected": sum(d.get("rejected") or 0 for d in decisions + legacy),
        "exceptions": sum(r.get("event") == "exception" for r in rows),
        "http_errors": sum(r.get("event") == "http_error" for r in rows),
        "llm_calls": len(calls),
        "llm_failed": sum(llm_call_failed(c) for c in calls),
        "llm_cost_usd": round(sum(llm_call_cost(c) for c in calls), 6),
        "max_compute_ms": max((d.get("compute_ms") or 0 for d in decisions), default=None),
        "trace": dict(trace),
    }


def log_taint(log: dict) -> list[str]:
    taint = []
    if log.get("rejected"):
        taint.append("rejected_orders")
    if log.get("exceptions"):
        taint.append("exception")
    if log.get("llm_calls") and log["llm_failed"] / log["llm_calls"] >= LLM_FAILING_SHARE:
        taint.append("llm_failing")
    return taint


def first_existing(ep: Path, names: tuple[str, ...]) -> Path | None:
    return next((ep / n for n in names if (ep / n).is_file()), None)


def seat_log_paths(ep: Path) -> dict[int, Path]:
    """slot -> seat log, for the local (`logs/`) and fetch-artifacts (`policy-logs/`) layouts."""
    out = {}
    for path in sorted((ep / "logs").glob("policy_agent_*.log")):
        out[int(path.stem.rsplit("_", 1)[1])] = path
    for path in sorted((ep / "policy-logs").glob("*.log")):
        match = HOSTED_LOG.match(path.name)
        if match:
            out[int(match["slot"])] = path
    return out


def _policies(ep: Path, episode: dict) -> dict[int, str]:
    out = {}
    for p in episode.get("participants") or []:
        if p.get("policy_name") is not None:
            out[int(p["position"])] = f'{p["policy_name"]}:v{p.get("version")}'
    if not out and (ep / "seating.json").exists():
        out = dict(enumerate(json.loads((ep / "seating.json").read_text())))
    return out


def final_year_of(results: dict) -> int | None:
    # Year of the last completed autumn: play stops at autumn (odd turn) or is observed one
    # phase later in the next spring (even turn); both mean the autumn before was the last.
    final_turn = (results.get("final_state") or {}).get("turn")
    return 1901 + (int(final_turn) - 1) // 2 if final_turn is not None else None


def replay_tables(replay: list | None) -> tuple[dict[int, Counter], dict[int, Counter]]:
    """(supply centres per country by year after each autumn, order stats per country)."""
    if not replay:
        return {}, {}
    last = replay[-1]
    supply = {t["id"] for t in last["variant"]["territories"] if t["supply"] and t.get("coast") != "Child"}
    centers_by_year: dict[int, Counter] = {}
    order_stats: dict[int, Counter] = {}
    for ph in last["history"]["phases"]:
        turn, phase = ph["turn"], ph["phase"]
        if phase == "Diplomacy":
            for o in ph.get("orders") or []:
                c = order_stats.setdefault(o["countryID"], Counter())
                c["orders"] += 1
                c["failed"] += o["type"] != "Hold" and not o.get("success")
                c["dislodged"] += bool(o.get("dislodged"))
        # Ownership changes at the end of each autumn; the entries showing the post-autumn
        # position are that winter's Builds or the next spring's Diplomacy. The final
        # Finished entry is stale (pre-final-autumn), so it is skipped here.
        if phase == "Builds":
            year = 1901 + turn // 2
        elif phase == "Diplomacy" and turn % 2 == 0 and turn > 0:
            year = 1901 + turn // 2 - 1
        else:
            continue
        centers_by_year[year] = Counter(c["countryID"] for c in ph.get("centers") or [] if c["terrID"] in supply)
    return centers_by_year, order_stats


def load_episode(ep: Path) -> tuple[list[Seat], dict]:
    """Return (seats, status) for one episode directory. `status` records coverage gaps."""
    episode = read_json_file(ep / "episode.json") if (ep / "episode.json").exists() else {}
    status = {"dir": str(ep), "episode_id": episode.get("id") or str(ep),
              "episode_status": episode.get("status", "local"),
              "coworld_version": episode.get("coworld_version"), "missing": []}
    results_path = first_existing(ep, RESULTS_NAMES)
    if results_path is None:
        status["missing"].append("results")
        return [], status
    results = read_json_file(results_path)
    replay_path = first_existing(ep, REPLAY_NAMES)
    try:
        replay = read_json_file(replay_path) if replay_path else None
    except (ValueError, OSError):
        replay = None
    if not replay:
        status["missing"].append("replay")
    status["outcome"] = results.get("outcome", "")

    policies = _policies(ep, episode)
    logs = seat_log_paths(ep)
    members = {int(m["countryID"]): m for m in results.get("members") or []}
    final_year = final_year_of(results)
    outcome = results.get("outcome", "")
    episode_taint = []
    if outcome == "cancelled":
        episode_taint.append("cancelled")
    if status["episode_status"] in FAILED_EPISODE_STATUSES:
        episode_taint.append("episode_failed")
    centers_by_year, order_stats = replay_tables(replay)
    scores = results.get("scores") or []

    seats = []
    for slot, country in enumerate(results.get("countries") or []):
        country = int(country)
        member = members.get(country, {})
        finals = int(member["supplyCenterNo"]) if member.get("supplyCenterNo") is not None else None
        stats = order_stats.get(country, Counter())
        trajectory = {y: c.get(country, 0) for y, c in sorted(centers_by_year.items())}
        if final_year is not None and finals is not None:
            trajectory[final_year] = finals  # results.json wins over the stale replay entry
        seat = Seat(
            episode_id=status["episode_id"],
            slot=slot,
            policy=policies.get(slot, "local"),
            power=POWERS[country],
            score=float(scores[slot]) if slot < len(scores) and scores[slot] is not None else 0.0,
            final_centers=finals,
            survived=(finals > 0) if finals is not None else None,
            solo=outcome == "won" and (finals or 0) >= SOLO_CENTERS,
            outcome=outcome,
            reason=results.get("reason", ""),
            final_year=final_year,
            centers_by_year=trajectory,
            orders=stats["orders"],
            orders_failed=stats["failed"],
            dislodged=stats["dislodged"],
            taint=list(episode_taint),
        )
        rows = read_log(logs.get(slot))
        if rows:
            seat.log = summarize_log(rows)
            seat.taint += log_taint(seat.log)
        seats.append(seat)
    return seats, status


def is_episode_dir(path: Path) -> bool:
    return (path / "episode.json").exists() or first_existing(path, RESULTS_NAMES) is not None


def episode_dirs(root: Path) -> list[Path]:
    """Every episode directory at or below `root`, sorted."""
    if is_episode_dir(root):
        return [root]
    out = []
    for child in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")):
        out.extend(episode_dirs(child))
    return out


def load_dirs(roots: list[Path]) -> tuple[list[Seat], list[dict]]:
    seats, statuses = [], []
    for root in roots:
        for ep in episode_dirs(root):
            s, st = load_episode(ep)
            seats.extend(s)
            statuses.append(st)
    return seats, statuses


def field_par(seats: list[Seat], is_target) -> dict[str, float]:
    """Mean score per power over the non-target seats (the same-batch field par)."""
    groups: dict[str, list[float]] = {}
    for s in seats:
        if not is_target(s):
            groups.setdefault(s.power, []).append(s.score)
    return {power: sum(v) / len(v) for power, v in groups.items()}


def drop_tainted_episodes(seats: list[Seat], is_target) -> tuple[list[Seat], set[str]]:
    """Remove every seat of an episode whose target seat (or the episode) is tainted."""
    bad = {s.episode_id for s in seats if s.taint and (is_target(s) or set(s.taint) & {"cancelled", "episode_failed"})}
    return [s for s in seats if s.episode_id not in bad], bad
