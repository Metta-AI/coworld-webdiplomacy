#!/usr/bin/env python3
"""What each fetched batch cost and how long it took, from the episode rows on disk.

    python3 games/webdiplomacy/tools/batches.py DIR... [--responses DIR] [--json]

DIR is `.runtime/artifacts` or any directory of fetched hosted episodes. One row per batch
(the first directory below DIR, the way `opponent_profile.py` names a game's `source`):

  games        episode rows found, and how many are not `completed`
  launched     the first `created_at` of the batch (Pacific Time)
  finished     the last `completed_at`
  wall         minutes from the first launch to the last finish: what you waited
  game         minutes one game ran (`running_at` to `completed_at`), median and longest
  wait         minutes one game waited before it ran (`created_at` to `running_at`), median and
               longest. A long wait is a queue (other batches were running) or a game the
               platform restarted
  cost         the sum of the rows' `cost_usd`, and per game. This is what the platform recorded
               for the episode after it ran. It is in dollars, not credits
  est. credits the platform's estimate when the request was created
               (`cost_preview.estimated_cost_credits`), summed over the batch's requests, when
               the create responses are on disk. The seed's `eval_request.py create` saves each
               response in a `responses/` folder beside the request body, so the default
               `--responses` is `.runtime/requests/responses` in this lab

Use it to answer "what did that run cost" and "how long do N games take" from a clock and a
row, not from memory: an agent has no clock, so run `date` (or this) before quoting a duration.

What it cannot show: the credits actually charged. Neither the episode row nor the create
response carries them, and where a balance can be read is not known (2026-10-11).
The estimate and `cost_usd` are both the platform's numbers; whether either is the bill, and
how dollars convert to credits, is not known.
League games have rows too (`league-press`, `league-gunboat`); their `wall` spans days and
means nothing. Local runs have no `episode.json` and are skipped. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from matchups import variant_of
from webdip_episodes import episode_dirs, read_json_file

LAB = Path(__file__).resolve().parent.parent
PACIFIC = ZoneInfo("America/Los_Angeles")


def parse_time(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text.replace("Z", "+00:00")) if text else None


def minutes(start: datetime | None, end: datetime | None) -> float | None:
    return (end - start).total_seconds() / 60 if start and end else None


def spread(values: list[float]) -> dict | None:
    return {"median": round(statistics.median(values), 1), "max": round(max(values), 1)} if values else None


def read_estimates(responses: Path) -> dict[str, float]:
    """Request id -> the platform's credit estimate, from saved `eval_request.py create` responses."""
    out = {}
    for path in sorted(responses.glob("*.json")) if responses.is_dir() else []:
        saved = read_json_file(path)
        estimate = ((saved or {}).get("cost_preview") or {}).get("estimated_cost_credits")
        if isinstance(saved, dict) and saved.get("id") and estimate is not None:
            out[saved["id"]] = float(estimate)
    return out


def batch_rows(roots: list[Path], estimates: dict[str, float]) -> list[dict]:
    rows_by_batch: dict[str, list[tuple[dict, str]]] = defaultdict(list)
    seen = set()
    for root in roots:
        for ep in episode_dirs(root):
            path = ep / "episode.json"
            if ep.name in seen or not path.exists():
                continue
            seen.add(ep.name)
            below = ep.relative_to(root).parts
            rows_by_batch[below[0] if len(below) >= 3 else root.name].append((read_json_file(path), variant_of(ep)))
    out = []
    for batch, rows in sorted(rows_by_batch.items()):
        episodes = [row for row, _ in rows]
        created = [t for t in (parse_time(e.get("created_at")) for e in episodes) if t]
        done = [t for t in (parse_time(e.get("completed_at")) for e in episodes) if t]
        game, wait = [], []
        for e in episodes:
            running = parse_time(e.get("running_at"))
            if (ran := minutes(running, parse_time(e.get("completed_at")))) is not None:
                game.append(ran)
            if (waited := minutes(parse_time(e.get("created_at")), running)) is not None:
                wait.append(waited)
        costs = [float(e["cost_usd"]) for e in episodes if isinstance(e.get("cost_usd"), (int, float))]
        requests = sorted({e["experience_request_id"] for e in episodes if e.get("experience_request_id")})
        known = [estimates[r] for r in requests if r in estimates]
        out.append({
            "batch": batch,
            "games": len(episodes),
            "not_completed": sum(e.get("status") != "completed" for e in episodes),
            "variants": dict(Counter(variant for _, variant in rows)),
            "requests": len(requests),
            "launched": min(created).isoformat() if created else None,
            "finished": max(done).isoformat() if done else None,
            "wall_minutes": round(minutes(min(created), max(done)), 1) if created and done else None,
            "game_minutes": spread(game),
            "wait_minutes": spread(wait),
            "cost_usd": round(sum(costs), 2) if costs else None,
            "cost_usd_per_game": round(sum(costs) / len(costs), 3) if costs else None,
            "games_with_cost": len(costs),
            "estimated_credits": round(sum(known), 1) if known else None,
            "requests_with_estimate": len(known),
        })
    return out


def _clock(iso: str | None) -> str:
    return datetime.fromisoformat(iso).astimezone(PACIFIC).strftime("%m-%d %H:%M") if iso else "-"


def _spread(s: dict | None) -> str:
    return f"{s['median']:.0f} / {s['max']:.0f}" if s else "-"


def render(rows: list[dict]) -> str:
    lines = ["| batch | games | variant | launched (PT) | finished (PT) | wall min | game min (median / max) "
             "| wait min (median / max) | cost_usd (per game) | est. credits (per game) |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        games = str(r["games"]) + (f" ({r['not_completed']} not completed)" if r["not_completed"] else "")
        cost = f"${r['cost_usd']:.2f} (${r['cost_usd_per_game']:.3f})" if r["cost_usd"] is not None else "-"
        credits = "-"
        if r["estimated_credits"] is not None:
            credits = f"{r['estimated_credits']:.1f} ({r['estimated_credits'] / r['games']:.2f})"
            if r["requests_with_estimate"] < r["requests"]:
                credits += f", {r['requests_with_estimate']} of {r['requests']} requests"
        wall = f"{r['wall_minutes']:.0f}" if r["wall_minutes"] is not None else "-"
        lines.append(f"| {r['batch']} | {games} | {', '.join(r['variants'])} | {_clock(r['launched'])} | "
                     f"{_clock(r['finished'])} | {wall} | {_spread(r['game_minutes'])} | "
                     f"{_spread(r['wait_minutes'])} | {cost} | {credits} |")
    lines.append("")
    lines.append("cost_usd is the platform's per-episode record, in dollars. est. credits is its estimate at "
                 "create time. Neither is a bill: credits charged cannot be read back.")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dirs", nargs="+", metavar="DIR")
    ap.add_argument("--responses", default=str(LAB / ".runtime" / "requests" / "responses"), metavar="DIR",
                    help="saved `eval_request.py create` responses (default: this lab's .runtime/requests/responses)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    rows = batch_rows([Path(d) for d in args.dirs], read_estimates(Path(args.responses)))
    if not rows:
        print("no hosted episode rows (episode.json) below the given directories", file=sys.stderr)
        return 2
    print(json.dumps(rows, indent=1) if args.json else render(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
