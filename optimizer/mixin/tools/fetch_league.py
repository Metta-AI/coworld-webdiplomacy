#!/usr/bin/env python3
"""Fetch a league's own games (its rounds) into the artifacts layout the loader reads.

    python3 games/webdiplomacy/tools/fetch_league.py press|gunboat|league_<id> \\
        [--policy NAME | NAME:vN | <policy version id>] [--rounds N] [--out DIR] [--skip replay,logs]

`fetch_artifacts.py` fetches experience requests (XP requests). League rounds are not
requests, so this walks the league instead, with the same listing `tools/field.py` uses
(`coworld rounds` -> `coworld episodes -r` -> `coworld episodes <ereq>`), and saves every
finished episode of the most recent rounds (20 unless `--rounds N`), or with `--policy` only
the episodes that seat that policy:

    .runtime/artifacts/league-<press|gunboat>/round-<NNNN>/<ereq>/     (`league-<league id>` for another league)
        episode.json    the episode row, plus a `league_round` block (league id and key, round id and number)
        results.json, replay.*, game.log
        policy-logs/<policy version id>.<seat>.log    our own seats only (others return 403)
        artifacts/<policy version id>.<seat>.zip      our own seats only
        .done           written last; a re-run skips episodes that have it

**How a reader tells a league game from an XP-request game:** `episode.json` has a non-null
`round_id` for a league game (an XP-request episode has `round_id: null` and an
`experience_request_id`), and the directory sits under `league-*`. `webdip_episodes.py`'s
`episode_source` reads both. The `league_round` block this tool adds says which league and
which round number, which the platform's row does not.

A league round is a few games (how many, and how often, are league settings: read them with
`coworld leagues <league_id> --json`), so expect a few episodes per round.
Run `tools/gzip_replays.py` on the output afterwards. Re-running is safe: an episode still
running is skipped and picked up next time. It acts as the identity the `coworld` CLI is
using (`softmax get-token`), so our own seat logs arrive only when that identity owns the
policy. Standard library only; needs the `coworld` and `softmax` CLIs and a login.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import field

LAB = Path(__file__).resolve().parent.parent
SERVER = "https://softmax.com/api/observatory"
TERMINAL = {"completed", "failed", "cancelled", "canceled", "timed_out", "error"}
# (artifact type on the platform, file stem); the same three the XP-request fetcher saves.
EPISODE_ARTIFACTS = (("replay", "replay"), ("results", "results"), ("logs", "game.log"))


def seats_policy(episode: dict, ref: str | None) -> bool:
    """Whether `ref` (a policy name, `name:vN`, or a policy version id) holds a seat. None matches all."""
    if not ref:
        return True
    for seat in episode.get("participants") or []:
        label = seat.get("label") or f"{seat.get('policy_name')}:v{seat.get('version')}"
        if ref in (label, seat.get("policy_name"), seat.get("policy_version_id")):
            return True
    return False


def league_episodes(league_id: str, rounds: int, coworld=field.coworld):
    """Yield (round row, full episode row) for the league's most recent rounds, newest first.

    Only the single-episode call carries participant names, hence the third call
    (the same walk as `field.collect`)."""
    for rnd in coworld("rounds", "-l", league_id, "--limit", str(rounds)):
        for row in coworld("episodes", "-r", rnd["id"]):
            yield rnd, coworld("episodes", row["id"])


def episode_dir(out: Path, rnd: dict, episode: dict) -> Path:
    return out / f"round-{int(rnd['round_number']):04d}" / episode["id"]


def suffix_for(content_type: str) -> str:
    if "json" in content_type:
        return ".json"
    if "zip" in content_type:
        return ".zip"
    return ".bin"


def download(token: str, path: str, dest: Path, add_suffix: bool = False) -> bool:
    """GET `path` into `dest`. False when the platform has none (404) or it is not ours (403)."""
    # The default urllib User-Agent is refused at the edge (403, "error code: 1010"), which
    # would read here as "not ours"; name ourselves.
    headers = {"Authorization": f"Bearer {token}", "User-Agent": "webdip-fetch-league"}
    request = urllib.request.Request(SERVER + path, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            if add_suffix:
                dest = dest.with_name(dest.name + suffix_for(response.headers.get("content-type", "")))
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "wb") as handle:
                while chunk := response.read(1 << 20):
                    handle.write(chunk)
    except urllib.error.HTTPError as error:
        if error.code in (403, 404):
            return False
        raise
    return True


def fetch_episode(episode: dict, rnd: dict, league: dict, out: Path, skip: frozenset[str] = frozenset(),
                  get=download, token: str = "") -> str:
    """Save one league episode. Returns "fetched", "have" (already complete), "running", or
    "empty" when no download succeeded (nothing is marked done, so the next run tries again)."""
    ep_dir = episode_dir(out, rnd, episode)
    if (ep_dir / ".done").exists():
        return "have"
    if episode.get("status") not in TERMINAL:
        return "running"
    ep_dir.mkdir(parents=True, exist_ok=True)
    row = dict(episode)
    row["league_round"] = {"league_id": league["id"], "league": league["key"], "round_id": rnd["id"],
                           "round_number": rnd["round_number"]}
    (ep_dir / "episode.json").write_text(json.dumps(row, indent=2, default=str))
    ereq = episode["id"]
    got = False
    for artifact, stem in EPISODE_ARTIFACTS:
        if artifact not in skip:
            got |= bool(get(token, f"/v2/episode-requests/{ereq}/artifacts/{artifact}", ep_dir / stem,
                            add_suffix=not stem.endswith(".log")))
    for seat in episode.get("participants") or []:
        version, position = seat.get("policy_version_id"), seat.get("position")
        if version is None or position is None:
            continue
        got |= bool(get(token, f"/v2/episode-requests/{ereq}/{version}/policy-logs/{position}",
                        ep_dir / "policy-logs" / f"{version}.{position}.log"))
        got |= bool(get(token, f"/v2/episode-requests/{ereq}/{version}/policy-artifact/{position}",
                        ep_dir / "artifacts" / f"{version}.{position}.zip"))
    if not got:
        # Every download was refused or missing. Marking it done would leave a folder with a
        # row and nothing else for good. Leave it for the next run.
        return "empty"
    (ep_dir / ".done").write_text(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    return "fetched"


def league_key(league: str) -> dict:
    """{"id", "key"} for `press`, `gunboat` or a raw league id (whose key is the id itself)."""
    if league in field.LEAGUES:
        return {"id": field.LEAGUES[league], "key": league}
    known = {league_id: key for key, league_id in field.LEAGUES.items()}
    return {"id": league, "key": known.get(league, league)}


def current_token() -> str:
    out = subprocess.run(["softmax", "get-token"], capture_output=True, text=True)
    if out.returncode != 0 or not out.stdout.strip():
        sys.exit("softmax get-token failed: run `softmax login` first")
    return out.stdout.strip()


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("league", help="press, gunboat, or a league_<id>")
    ap.add_argument("--policy", help="only episodes that seat this policy (name, name:vN or version id)")
    ap.add_argument("--rounds", type=int, default=20, help="most recent rounds to read (default 20)")
    ap.add_argument("--out", type=Path, help="output root (default <lab>/.runtime/artifacts/league-<league>)")
    ap.add_argument("--skip", default="", help="comma-separated artifact types to leave out: replay, results, logs")
    args = ap.parse_args(argv)

    league = league_key(args.league)
    out = args.out or LAB / ".runtime" / "artifacts" / f"league-{league['key']}"
    skip = frozenset(part for part in args.skip.split(",") if part)
    token = current_token()
    counts = {"fetched": 0, "have": 0, "running": 0, "empty": 0, "other policies": 0}
    for rnd, episode in league_episodes(league["id"], args.rounds):
        if not seats_policy(episode, args.policy):
            counts["other policies"] += 1
            continue
        state = fetch_episode(episode, rnd, league, out, skip, token=token)
        counts[state] += 1
        if state == "fetched":
            print(f"  fetched round {rnd['round_number']} {episode['id']} ({episode.get('status')})", flush=True)
        elif state == "empty":
            print(f"  nothing could be downloaded for round {rnd['round_number']} {episode['id']}: every request "
                  "was refused or missing; it is not marked done and the next run tries again", file=sys.stderr)
    print(json.dumps({"out": str(out), **counts}))


if __name__ == "__main__":
    main()
