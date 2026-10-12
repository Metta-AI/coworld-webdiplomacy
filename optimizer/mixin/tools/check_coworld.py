#!/usr/bin/env python3
"""Say when the webDiplomacy Coworld or the optimizer template has changed since this lab last checked.

    python3 games/webdiplomacy/tools/check_coworld.py [-v]     # anything new?
    python3 games/webdiplomacy/tools/check_coworld.py --show   # print the new changelog entries in full
    python3 games/webdiplomacy/tools/check_coworld.py --ack    # after applying them: record that this lab is current

The game and this lab's template both live in coworld-webdiplomacy, and its `CHANGELOG.md` has
one dated entry for each change a player or an optimizer must act on. Each entry names the
Coworld version that was live and says what to do in an optimizer. The lab keeps the copy it
was last brought up to date with, as `games/webdiplomacy/CHANGELOG.md`. This tool compares
that copy with the current file on GitHub and looks up the hosted Coworld version
(`coworld list --json`: the canonical `webdiplomacy` entry).

It reports two things: changelog entries the lab's copy does not have, and a hosted Coworld
version that differs from the newest entry's (the game was released before its entry was
written; read the repository's recent commits then). The lab manual, "Keep the lab current",
says how to apply an entry. `--ack` replaces the lab's copy with the current file; run it only
after the entries are applied, and commit the result.

The optimizer's SessionStart hook runs this with no options, so it prints nothing when the lab
is current and never fails the session: exit status is always 0, and a network or CLI error
only skips that comparison. `-v`, for a run by hand, also says so when nothing is new.

Standard-library Python 3.12+.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import urllib.request
from pathlib import Path

LAB = Path(__file__).resolve().parent.parent
LOCAL = LAB / "CHANGELOG.md"
UPSTREAM_URL = "https://raw.githubusercontent.com/Metta-AI/coworld-webdiplomacy/main/CHANGELOG.md"
# An entry's heading: `## 2026-10-12 · Coworld 0.7.9 · Title`.
HEADING = re.compile(r"^## (\d{4}-\d{2}-\d{2}) · Coworld (\S+) · (.+)$")


def entries(changelog: str) -> dict[str, str]:
    """Map each entry's heading line to the entry's full text, in file order (newest first)."""
    found: dict[str, str] = {}
    current = None
    for line in changelog.splitlines():
        if line.startswith("## "):
            current = line.strip() if HEADING.match(line.strip()) else None
            if current:
                found[current] = ""
        if current:
            found[current] += line + "\n"
    return found


def new_entries(local: str, upstream: str) -> dict[str, str]:
    """The upstream entries whose heading the lab's copy does not have."""
    have = entries(local)
    return {heading: text for heading, text in entries(upstream).items() if heading not in have}


def newest_version(changelog: str) -> str | None:
    """The Coworld version named by the first (newest) entry."""
    for heading in entries(changelog):
        return HEADING.match(heading).group(2)
    return None


def fetch_upstream() -> str | None:
    try:
        with urllib.request.urlopen(UPSTREAM_URL, timeout=8) as response:
            return response.read().decode()
    except (OSError, ValueError):
        return None


def hosted_version() -> str | None:
    """The canonical hosted webDiplomacy Coworld's version, or None when the CLI cannot say."""
    try:
        listing = subprocess.run(["coworld", "list", "--json"], capture_output=True, text=True, check=True,
                                 timeout=20).stdout
        return canonical_version(json.loads(listing))
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def canonical_version(listing: dict) -> str | None:
    for row in listing.get("entries", []):
        if row.get("name") == "webdiplomacy" and row.get("canonical"):
            return row.get("version")
    return None


def report(local: str | None, upstream: str, hosted: str | None) -> list[str]:
    """The lines to print; empty when the lab is current."""
    lines = []
    fresh = new_entries(local or "", upstream)
    if local is None:
        lines.append(f"This lab has no {LOCAL.name}, so every entry counts as new.")
    if fresh:
        lines.append(f"{len(fresh)} changelog entr{'y' if len(fresh) == 1 else 'ies'} since this lab was last "
                     "brought up to date:")
        lines += [f"- {heading.removeprefix('## ')}" for heading in fresh]
        lines.append("Read them (`tools/check_coworld.py --show`), apply each one's \"In your optimizer\" steps "
                     "(lab manual, \"Keep the lab current\"), then run `tools/check_coworld.py --ack` and commit.")
    logged = newest_version(upstream)
    if hosted and logged and hosted != logged:
        lines.append(f"The hosted webDiplomacy Coworld is {hosted}, and the changelog's newest entry is for "
                     f"{logged}: the changelog may not cover this release yet. Read the recent commits of "
                     "https://github.com/Metta-AI/coworld-webdiplomacy before you rely on a game fact.")
    return lines


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="also say so when nothing is new (the hook stays silent)")
    parser.add_argument("--show", action="store_true", help="print the new changelog entries in full")
    parser.add_argument("--ack", action="store_true",
                        help="record that the new entries are applied: replace the lab's copy with the current file")
    args = parser.parse_args(argv)

    upstream = fetch_upstream()
    if upstream is None or not entries(upstream):
        if args.verbose or args.show or args.ack:
            print(f"Coworld check: could not read {UPSTREAM_URL}; nothing compared.")
        return
    local = LOCAL.read_text() if LOCAL.exists() else None
    if args.ack:
        LOCAL.write_text(upstream)
        print(f"Coworld check: {LOCAL.name} now matches upstream (newest entry: Coworld {newest_version(upstream)}). "
              "Commit it.")
        return
    if args.show:
        print("".join(new_entries(local or "", upstream).values()) or "Coworld check: no new changelog entries.")
        return
    hosted = hosted_version()
    lines = report(local, upstream, hosted)
    if lines:
        print("Coworld check: the game or the optimizer template has changed. Do this before other work.")
        print("\n".join(lines))
    elif args.verbose:
        seen = f"hosted Coworld {hosted}" if hosted else "hosted version not read (is the coworld CLI logged in?)"
        print(f"Coworld check: no new changelog entries; {seen}.")


if __name__ == "__main__":
    main()
