#!/usr/bin/env python3
"""Who is in a league's field: every policy seen in its recent rounds.

    python3 games/webdiplomacy/tools/field.py press|gunboat|league_<id> [--rounds N] [--json]

The league's filler roster is not readable with player credentials (the
`/v2/leagues/{id}/filler-policies` route returns 403), so this reads it off the
league's own games: `coworld rounds` -> `coworld episodes -r` -> `coworld
episodes <ereq>` (only the single-episode call carries participant names).

Output: one row per policy version with its version id (paste into a roster as
`policy_ref`), filler or entrant, its player as bots see it, rounds seen, and mean league
score; then the seating of each round (who sat, how many seats each), which is what a field
set copies. "As bots see it" is the `name` a bot reads from `WEBDIP_PLAYERS` (Coworld
0.7.16): `player (owner)`, or the player alone when it has no human owner. One player can own
several policies, so a name narrows a seat to that player's rows here, not to one version.
A filler seat is named by the league's filler setting instead, which this data lacks (blank).
"Entrant" is as of the round: a policy whose membership was retired since still shows.
A league round is a few games (how many is a league setting), so these means rest on a
handful of games; they say who is present, not who is strong. Standard library only; needs the
`coworld` CLI on PATH and an authenticated session.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

LEAGUES = {
    "press": "league_1bccc63d-cd0a-47d7-92d7-e762797b5f1c",
    "gunboat": "league_428e91e5-ee25-4f9c-be5e-a4fc4f993f17",
}


def coworld(*args: str):
    out = subprocess.run(["coworld", *args, "--json"], capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit(f"coworld {' '.join(args)} failed: {out.stderr.strip()[:300]}")
    data = json.loads(out.stdout)
    return data["entries"] if isinstance(data, dict) and "entries" in data else data


def seat_name(seat: dict) -> str | None:
    """The name bots are told for this entrant seat, built the way the platform builds it.

    None for a filler (named by the league setting) or a policy with no player (bots get null).
    A player seated twice in one game gets " (2)" after the second seat's name; not added here."""
    player, owner = seat.get("player_name"), seat.get("owner_name")
    if seat.get("is_filler") or not player:
        return None
    return f"{player} ({owner})" if owner else player


def add_episode(field: dict[str, dict], round_number: int, episode: dict) -> None:
    """Fold one league episode's seats into `field` (label -> entry)."""
    # `participant_scores` is by position; `scores` collapses a policy seated twice.
    score_at = {s["position"]: s["score"] for s in episode.get("participant_scores") or []}
    for seat in episode.get("participants") or []:
        entry = field.setdefault(seat["label"], {
            "label": seat["label"],
            "policy_version_id": seat["policy_version_id"],
            "filler": seat["is_filler"],
            "player": seat.get("player_name"),
            "seat_name": seat_name(seat),
            "rounds": [],
            "scores": [],
        })
        entry["rounds"].append(round_number)
        if seat["position"] in score_at:
            entry["scores"].append(score_at[seat["position"]])


def summarize(field: dict[str, dict]) -> list[dict]:
    """Rows sorted fillers first, each with its seat count and mean league score."""
    rows = sorted(field.values(), key=lambda r: (not r["filler"], r["label"]))
    for row in rows:
        row["seats"] = len(row["scores"])
        row["mean_score"] = round(sum(row["scores"]) / len(row["scores"]), 3) if row["scores"] else None
    return rows


def seatings(rows: list[dict]) -> dict[int, dict[str, int]]:
    """Round number -> {policy label: seats it held in that round}, newest round first.

    A field set should copy a real seating: a league that seats one filler twice is a
    different field from one that seats it once."""
    out: dict[int, dict[str, int]] = {}
    for row in rows:
        for number in row["rounds"]:
            seats = out.setdefault(number, {})
            seats[row["label"]] = seats.get(row["label"], 0) + 1
    return dict(sorted(out.items(), reverse=True))


def collect(league_id: str, rounds: int) -> dict[str, dict]:
    field: dict[str, dict] = {}
    for rnd in coworld("rounds", "-l", league_id, "--limit", str(rounds)):
        for row in coworld("episodes", "-r", rnd["id"]):
            add_episode(field, rnd["round_number"], coworld("episodes", row["id"]))
    return field


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("league", help="press, gunboat, or a league_<id>")
    ap.add_argument("--rounds", type=int, default=10, help="most recent rounds to read (default 10)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    rows = summarize(collect(LEAGUES.get(args.league, args.league), args.rounds))
    if args.json:
        print(json.dumps(rows, indent=1))
        return
    print("| policy | version id | kind | player as bots see it | seats | mean score (league games) | rounds |")
    print("|---|---|---|---|---|---|---|")
    for row in rows:
        kind = "filler" if row["filler"] else "entrant"
        print(f"| {row['label']} | `{row['policy_version_id']}` | {kind} | {row['seat_name'] or ''} | "
              f"{row['seats']} | {row['mean_score']} | {sorted(set(row['rounds']))} |")
    print("\n'entrant' means the seat was a league member's WHEN THAT ROUND RAN; the membership may have been "
          "retired since (check the standings: `coworld results <div_id>`).")
    print("\nSeating by round (newest first):")
    for number, seats in seatings(rows).items():
        names = (f"{label} x{n}" if n > 1 else label for label, n in sorted(seats.items()))
        print(f"- round {number}: " + ", ".join(names))


if __name__ == "__main__":
    main()
