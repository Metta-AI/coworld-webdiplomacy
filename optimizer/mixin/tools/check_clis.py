#!/usr/bin/env python3
"""Warn when the `coworld` or `softmax` CLI is missing or older than PyPI's latest.

    python3 games/webdiplomacy/tools/check_clis.py [-v]

The lab uses the CLIs installed as uv tools (`uv tool install coworld`,
`uv tool install softmax-cli`). A stale tool fails in confusing ways, and a tool
installed from a local checkout can sit on an old dev build for months without
anyone noticing. The optimizer's SessionStart hook runs this script, so it prints
nothing when both tools are current and never fails the session: exit status is
always 0, and network errors only skip the comparison. `-v`, for a run by hand, also
prints the versions when both are current.

Standard-library Python 3.12+.
"""

from __future__ import annotations

import argparse
import json
import os
import pwd
import re
import subprocess
import urllib.request

# uv tool name -> command it installs.
TOOLS = {"coworld": "coworld", "softmax-cli": "softmax"}
PYPI_URL = "https://pypi.org/pypi/{package}/json"


def installed_versions() -> dict[str, str] | None:
    """Map uv tool name to installed version, or None when uv is unavailable."""
    # uv finds its tools through HOME. This lab tells sessions to use a private HOME for
    # Softmax credentials, which would make every tool look "not installed", so ask uv with
    # the account's real home directory.
    env = dict(os.environ, HOME=pwd.getpwuid(os.getuid()).pw_dir)
    try:
        listing = subprocess.run(["uv", "tool", "list"], capture_output=True, text=True, check=True,
                                 timeout=10, env=env).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_tool_list(listing)


def parse_tool_list(listing: str) -> dict[str, str]:
    """Parse `uv tool list` output: lines like `coworld v0.1.58`."""
    versions = {}
    for line in listing.splitlines():
        match = re.match(r"^(\S+) v(\S+)", line)
        if match:
            versions[match.group(1)] = match.group(2)
    return versions


def latest_version(package: str) -> str | None:
    try:
        with urllib.request.urlopen(PYPI_URL.format(package=package), timeout=5) as response:
            return json.load(response)["info"]["version"]
    except (OSError, ValueError, KeyError):
        return None


def release_tuple(version: str) -> tuple[int, ...]:
    """Leading numeric release, so `0.1.38.post1.dev750` compares as (0, 1, 38)."""
    match = re.match(r"\d+(\.\d+)*", version)
    return tuple(int(part) for part in match.group(0).split(".")) if match else ()


def problems(installed: dict[str, str], latest: dict[str, str | None]) -> list[str]:
    found = []
    for package, command in TOOLS.items():
        have = installed.get(package)
        want = latest.get(package)
        if have is None:
            found.append(f"`{command}` is not installed as a uv tool. Fix: uv tool install {package}")
        elif want and release_tuple(have) < release_tuple(want):
            found.append(f"`{command}` is {have}; the latest release is {want}. Fix: uv tool install --force {package}")
    return found


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="also say so when both tools are current (the hook stays silent)")
    args = parser.parse_args(argv)
    installed = installed_versions()
    if installed is None:
        print("CLI check: `uv` was not found, so the coworld and softmax CLIs cannot be checked.")
        return
    latest = {package: latest_version(package) for package in TOOLS}
    found = problems(installed, latest)
    if found:
        print("CLI check: update these before using the platform (stale CLIs fail in confusing ways).")
        for problem in found:
            print(f"- {problem}")
    elif args.verbose:
        versions = ", ".join(f"{package} {installed.get(package)}" for package in TOOLS)
        checked = "current" if all(latest.values()) else "installed (PyPI was not reachable, so not compared)"
        print(f"CLI check: {versions}: {checked}.")


if __name__ == "__main__":
    main()
