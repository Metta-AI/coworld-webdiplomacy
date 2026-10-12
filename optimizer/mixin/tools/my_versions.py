#!/usr/bin/env python3
"""Every version the active player has uploaded, by policy, with the ones that sit in a league marked.

    python3 games/webdiplomacy/tools/my_versions.py [--policy NAME]... [--in-league] [--past] [--json]

Answers "what is already uploaded under this player, and which of it is entered somewhere"
without a hand-written API call. It acts as the identity the CLIs act as (`softmax status`):
for a player, that player's versions; for the main user, everything the user owns.

One block per policy name, the policy with the newest upload first, and inside it the newest
version first. A version that holds a league entry now (membership status `competing`) is
marked `IN LEAGUE` with the league, the division and its state (`active`, `benched`,
`champion`). `--past` also shows entries that ended (`disqualified`: superseded, inactive).
`--policy NAME` keeps the named policies (exact names; repeat it); `--in-league` keeps only
the versions with a current entry.

Uploading a version enters nothing. A version is in a league only when it was submitted
(`coworld submit`), which is the one gated act in this optimizer; this tool only reads.

Where the rows come from: `GET /v2/policy-versions` and `GET /v2/league-policy-memberships`
on the Observatory API, every page (the next page's token is in the `X-Next-Cursor` response
header; a single call returns at most 500 versions or 1,000 memberships, and a count from one
page is wrong for a busy player). The token is `softmax get-token`'s.
Standard library only; needs the `softmax` CLI and a signed-in session.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

SERVER = "https://softmax.com/api/observatory"
PACIFIC = ZoneInfo("America/Los_Angeles")
LIVE_STATUS = "competing"  # the membership statuses the API's own `active_only` filter keeps


def cli(*args: str) -> str:
    out = subprocess.run(["softmax", *args], capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit(f"softmax {' '.join(args)} failed: {out.stderr.strip()[:300]}; run `softmax login` first")
    return out.stdout


def identity() -> dict[str, str]:
    """`softmax status` as a dict: `subject_type` (player or user) and `subject_id` are what this tool needs."""
    return dict(line.split(": ", 1) for line in cli("status").splitlines() if ": " in line)


def api_get(token: str, path: str, params: dict) -> tuple[list, str | None]:
    """One page of a list route: (rows, the next page's token or None)."""
    request = urllib.request.Request(
        f"{SERVER}{path}?{urllib.parse.urlencode(params)}",
        # The site refuses urllib's default User-Agent with "403 error code: 1010".
        headers={"Authorization": f"Bearer {token}", "User-Agent": "webdip-optimizer-tools"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response), response.headers.get("X-Next-Cursor")
    except urllib.error.HTTPError as error:
        sys.exit(f"GET {path} failed {error.code}: {error.read()[:300].decode(errors='replace')}")


def all_pages(get_page, path: str, params: dict) -> list[dict]:
    """Every row of a list route. `get_page(path, params)` returns (rows, next token)."""
    rows, cursor = [], None
    while True:
        page, cursor = get_page(path, {**params, **({"cursor": cursor} if cursor else {})})
        rows += page
        if not cursor or not page:
            return rows


def owner_filter(who: dict[str, str]) -> dict:
    """The query that selects the active identity's rows: one player's, or all the user's own."""
    if who.get("subject_type") == "player":
        return {"player_id": who["subject_id"]}
    return {"mine": "true"}


def entry(membership: dict) -> dict:
    """What this tool shows of one league membership."""
    division = membership.get("division") or {}
    return {
        "league": (membership.get("league") or {}).get("name"),
        "league_id": (membership.get("league") or {}).get("id"),
        "division": division.get("name"),
        "status": membership.get("status"),
        "substatus": membership.get("substatus"),
        "champion": bool(membership.get("is_champion")),
        "current": membership.get("status") == LIVE_STATUS,
        "since": membership.get("start_time"),
        "ended": membership.get("end_time"),
        "membership_id": membership.get("id"),
    }


def group_versions(versions: list[dict], memberships: list[dict]) -> list[dict]:
    """Policies, the one with the newest upload first; in each, its versions newest first with their league entries."""
    entries: dict[str, list[dict]] = {}
    for membership in memberships:
        version_id = (membership.get("policy_version") or {}).get("id")
        if version_id:
            entries.setdefault(version_id, []).append(entry(membership))
    policies: dict[str, list[dict]] = {}
    for row in versions:
        leagues = sorted(entries.get(row["policy_version_id"], []), key=lambda e: (not e["current"], e["league"] or ""))
        policies.setdefault(row["policy_name"], []).append({
            "version": row["version"],
            "policy_version_id": row["policy_version_id"],
            "created_at": row["created_at"],
            "player": row.get("player_name"),
            "leagues": leagues,
        })
    out = []
    for name, rows in policies.items():
        rows.sort(key=lambda r: r["created_at"], reverse=True)
        out.append({"policy": name, "versions": rows, "newest": rows[0]["created_at"],
                    "in_league": sum(any(e["current"] for e in r["leagues"]) for r in rows)})
    return sorted(out, key=lambda p: p["newest"], reverse=True)


def select(policies: list[dict], names: list[str], in_league: bool) -> list[dict]:
    """Keep the named policies (all when none is named) and, with `in_league`, only versions entered now."""
    kept = []
    for policy in policies:
        if names and policy["policy"] not in names:
            continue
        versions = [v for v in policy["versions"] if any(e["current"] for e in v["leagues"])] if in_league \
            else policy["versions"]
        if versions:
            kept.append({**policy, "versions": versions})
    return kept


def _clock(iso: str) -> str:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(PACIFIC).strftime("%Y-%m-%d %H:%M")


def _entry_text(e: dict) -> str:
    state = ", ".join(part for part in (e["substatus"], "champion" if e["champion"] and e["substatus"] != "champion"
                                        else None) if part) or e["status"]
    where = f"{e['league']} / {e['division']}" if e["division"] else str(e["league"])
    if e["current"]:
        return f"IN LEAGUE {where} ({state})"
    return f"was in {where} ({e['status']}{', ' + e['substatus'] if e['substatus'] else ''})"


def render(policies: list[dict], who: dict[str, str], past: bool) -> str:
    versions = sum(len(p["versions"]) for p in policies)
    entered = sum(any(e["current"] for e in v["leagues"]) for p in policies for v in p["versions"])
    lines = [f"{who.get('subject_type')} {who.get('subject_id')}: {versions} version(s) in {len(policies)} "
             f"policy name(s), {entered} in a league now. Times are Pacific.", ""]
    for policy in policies:
        mark = f", {policy['in_league']} in a league now" if policy["in_league"] else ""
        lines.append(f"{policy['policy']}  ({len(policy['versions'])} version(s){mark})")
        for v in policy["versions"]:
            shown = [e for e in v["leagues"] if e["current"] or past]
            marks = "  " + "; ".join(_entry_text(e) for e in shown) if shown else ""
            lines.append(f"  v{v['version']:<4} {_clock(v['created_at'])}  {v['policy_version_id']}{marks}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--policy", action="append", default=[], metavar="NAME",
                    help="keep this policy name (exact; repeat for several)")
    ap.add_argument("--in-league", action="store_true", help="only versions that hold a league entry now")
    ap.add_argument("--past", action="store_true", help="also show league entries that ended")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    who = identity()
    if not who.get("subject_id"):
        sys.exit("softmax status names no identity; run `softmax login` first")
    token = cli("get-token").strip()

    def get_page(path: str, params: dict) -> tuple[list, str | None]:
        return api_get(token, path, params)

    versions = all_pages(get_page, "/v2/policy-versions", {**owner_filter(who), "limit": 500})
    memberships = all_pages(get_page, "/v2/league-policy-memberships", {**owner_filter(who), "limit": 1000})
    policies = select(group_versions(versions, memberships), args.policy, args.in_league)
    if not policies:
        print("no versions match", file=sys.stderr)
        return 2
    print(json.dumps(policies, indent=1) if args.json else render(policies, who, args.past), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
