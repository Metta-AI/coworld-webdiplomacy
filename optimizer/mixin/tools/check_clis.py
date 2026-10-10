#!/usr/bin/env python3
"""Warn when the `coworld` or `softmax` CLI is missing or older than PyPI's latest.

    python3 games/webdiplomacy/tools/check_clis.py

The lab uses the CLIs installed as uv tools (`uv tool install coworld`,
`uv tool install softmax-cli`). A stale tool fails in confusing ways, and a tool
installed from a local checkout can sit on an old dev build for months without
anyone noticing. The optimizer's SessionStart hook runs this script, so it prints
nothing when both tools are current and never fails the session: exit status is
always 0, and network errors only skip the comparison.

Standard-library Python 3.12+.
"""

import json
import re
import subprocess
import urllib.request

# uv tool name -> command it installs.
TOOLS = {"coworld": "coworld", "softmax-cli": "softmax"}
PYPI_URL = "https://pypi.org/pypi/{package}/json"


def installed_versions() -> dict[str, str] | None:
    """Map uv tool name to installed version, or None when uv is unavailable."""
    try:
        listing = subprocess.run(["uv", "tool", "list"], capture_output=True, text=True, check=True, timeout=10).stdout
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


def main() -> None:
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


if __name__ == "__main__":
    main()
