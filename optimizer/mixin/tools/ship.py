#!/usr/bin/env python3
"""Build, upload, and log one version in a single step.

    python3 games/webdiplomacy/tools/ship.py --name POLICY --slug one-change-slug \\
        --change "The one change and its mechanism" [--overrides "KEY=VAL,..."] \\
        [--policy press|search] [--llm-model SLUG] [--experiment ID]

Does, in order: `tools/build.sh` with a tag derived from the slug (one tag per
experiment, never `latest`), `coworld upload-policy` with the slug as its
`purpose` tag, a lookup of the new version's id, and an appended row in
`players/castlereagh/VERSION_LOG.md`. The row is written before this script
returns, so "upload without a row" cannot happen (the optimizer's rule 2).
The log is the one of the source tree this tool builds (`build.sh` builds
`players/castlereagh` and nothing else), so every policy name uploaded from that
tree is logged there; a row's first cell is the uploaded `NAME:vN`, and the IDE
finds a version by that cell in any `players/*/VERSION_LOG.md`.
It also prints which identity uploaded, because the CLI acts as the active
player and a wrong player is easy to miss.

Standard library only; needs Docker and the `coworld` and `softmax` CLIs.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path

LAB = Path(__file__).resolve().parent.parent
VERSION_LOG = LAB / "players" / "castlereagh" / "VERSION_LOG.md"
# The model a press upload gets when --llm-model is not given: the reference policy's own
# default (castlereagh/config.py PRESS_MODEL; a test keeps the two equal). The model is fixed
# per uploaded version, so a different model is a new version.
DEFAULT_LLM_MODEL = "z-ai/glm-5.3-flash"


def run(cmd: list[str], env: dict | None = None) -> str:
    out = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if out.returncode != 0:
        sys.exit(f"{' '.join(cmd[:3])} … failed:\n{out.stdout[-800:]}\n{out.stderr[-800:]}")
    return out.stdout


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", required=True, help="uploaded policy name")
    ap.add_argument("--slug", required=True, help="short kebab-case name of the one change")
    ap.add_argument("--change", required=True, help="the one change and its mechanism (goes in the log row)")
    ap.add_argument("--overrides", default="", help='CASTLEREAGH_OVERRIDES to bake, "KEY=VAL,KEY=VAL"')
    ap.add_argument("--policy", default="press", choices=["press", "search"])
    ap.add_argument("--llm-model",
                    help=f"OpenRouter slug for press (default {DEFAULT_LLM_MODEL}); not allowed for search")
    ap.add_argument("--experiment", default="", help="experiment record id this version serves")
    args = ap.parse_args(argv)
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", args.slug):
        sys.exit("--slug must be kebab-case")
    if args.policy == "search" and args.llm_model:
        sys.exit("--llm-model is not allowed for search")
    if args.policy == "press" and not args.llm_model:
        args.llm_model = DEFAULT_LLM_MODEL

    who = run(["softmax", "status"])
    subject = dict(line.split(": ", 1) for line in who.splitlines() if ": " in line)
    print(f"uploading as {subject.get('subject_type')} {subject.get('subject_id')}", file=sys.stderr)

    env = dict(os.environ)
    # With a private HOME (see docs/platform.md) Docker needs its real config directory for
    # both the build and the upload; without it the build falls back to the legacy builder
    # and fails. "~<user>" resolves from the password database, so it ignores the HOME override.
    env.setdefault("DOCKER_CONFIG", str(Path(os.path.expanduser("~" + os.environ.get("USER", ""))) / ".docker"))

    tag = f"webdip-{args.name}:{args.slug}"
    build = [str(LAB / "tools" / "build.sh"), "--policy", args.policy, "--tag", tag]
    if args.overrides:
        build += ["--overrides", args.overrides]
    print(f"building {tag} (a first build on this machine also builds the player base image, a few minutes)",
          file=sys.stderr)
    run(build, env=env)

    upload = ["coworld", "upload-policy", tag, "--name", args.name, "--tag", f"purpose={args.slug}",
              "--title", args.slug.replace("-", " ")[:50], "--description", args.change[:600]]
    if args.llm_model:
        upload += ["--use-llm", "--llm-model", args.llm_model]
    out = run(upload, env=env)
    match = re.search(rf"Upload complete: {re.escape(args.name)}:v(\d+)", out)
    if not match:
        sys.exit(f"upload output did not name a version:\n{out[-600:]}")
    version = int(match.group(1))

    version_id = lookup_version_id(args.name, version)

    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")
    row = version_log_row(args.name, version, version_id, stamp, args.change, args.policy, args.overrides,
                          args.llm_model, tag, args.experiment, subject.get("subject_id"))
    VERSION_LOG.write_text(insert_row(VERSION_LOG.read_text(), row))
    print(json.dumps({"version": f"{args.name}:v{version}", "policy_version_id": version_id,
                      "image": tag, "version_log": str(VERSION_LOG)}, indent=1))
    print(f"If {args.name} is the policy the IDE's pages should follow, run: ide/ide follow {args.name}",
          file=sys.stderr)


def version_log_row(name: str, version: int, version_id: str, stamp: str, change: str, policy: str,
                    overrides: str, llm_model: str | None, tag: str, experiment: str, uploader: str | None) -> str:
    """One VERSION_LOG.md table row (columns as in players/_VERSION_LOG_template.md)."""
    config = f"`CASTLEREAGH_POLICY={policy}`"
    if overrides:
        config += f", `CASTLEREAGH_OVERRIDES={overrides}`"
    if llm_model:
        config += f", `--llm-model {llm_model}`"
    config += f"; image `{tag}`"
    validation = f"unvalidated (experiment `{experiment}`)" if experiment else "unvalidated"
    # A "|" inside the change text would split the table cell.
    return (f"| {name}:v{version} | `{version_id}` | {stamp} | {change.replace('|', '/')} | {config} | "
            f"{validation} | uploaded as {uploader} by tools/ship.py |\n")


def insert_row(text: str, row: str) -> str:
    """Append `row` to the version table: after its last row, wherever the table sits in the file."""
    lines = text.splitlines(keepends=True)
    header = next((i for i, line in enumerate(lines) if line.startswith("| Version |")), None)
    if header is None:
        raise ValueError("VERSION_LOG.md has no '| Version |' table header")
    last = header
    for i in range(header + 1, len(lines)):
        if not lines[i].startswith("|"):
            break
        last = i
    if not lines[last].endswith("\n"):
        lines[last] += "\n"
    return "".join(lines[:last + 1]) + row + "".join(lines[last + 1:])


def lookup_version_id(name: str, version: int) -> str:
    """The new version's id, via the optimizer's own resolver (it acts as the active player)."""
    resolver = LAB.parent.parent / "skills" / "run-eval" / "scripts" / "eval_request.py"
    out = run([str(resolver), "resolve", "--policy", f"{name}:v{version}"])
    return json.loads(out)["policy_version_id"]


if __name__ == "__main__":
    main()
