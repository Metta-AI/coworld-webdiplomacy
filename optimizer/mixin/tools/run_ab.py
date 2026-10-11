#!/usr/bin/env python3
"""Run one paired A/B end to end: bodies, dry run, launch, record, fetch, read.

    python3 games/webdiplomacy/tools/run_ab.py --record <experiment id> \\
        --a NAME:vN --b NAME:vM --field-set <set name> [-n 6]

Does, in order, what the lab manual's "Run one A/B" recipe lists by hand:

  1. `make_request.py paired --balanced --no-maps` (14 bodies: every power and
     both seat orders for each policy; total games = 14 x n),
  2. a dry run of the first body against the live schema,
  3. `eval_request.py create` for each body,
  4. writes the batch ids into the experiment record's `evals:` list and sets
     `status: running` (the record must already exist with its hypothesis and
     decision rule filled in: this tool will not launch for a record that still
     has template placeholders),
  5. one `fetch_artifacts.py --watch` over all batches into
     `.runtime/artifacts/<record id>`, then `gzip_replays.py`,
  6. prints `paired.py`'s report and both policies' health lines.

`--alone` runs the **candidate-alone check** instead: two separate arms, A alone and B
alone, each with the same six field seats and balanced powers (7 bodies x n per arm; the
field set must have six seats). Use it after any paired win, with a pass mark written in
the record first: a paired win can be a win over the other copy of our policy rather
than over the field (measured 2026-10-10: a +0.079, z 3.1 paired win scored level alone). Its batch ids are
appended to the record's `evals:`, artifacts go to `.runtime/artifacts/<record id>-alone-a`
and `-alone-b`, and the read is `compare.py` (B as baseline).

It does not judge: read the output against the rule you wrote in the record,
then close the record yourself. `--resume` skips steps 1 to 4 and picks up at
the fetch, using the ids already in the record (for an interrupted run).
Policies may be `name:vN` or a policy-version id; give `--a-label/--b-label`
when a ref is an id, because the analysis needs the `name:vN` label.
Standard library only; needs the `coworld` CLI session the seed scripts use.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

LAB = Path(__file__).resolve().parent.parent
ROOT = LAB.parent.parent
EVAL_REQUEST = ROOT / "skills" / "run-eval" / "scripts" / "eval_request.py"
FETCH = ROOT / "skills" / "fetch-artifacts" / "scripts" / "fetch_artifacts.py"


def run(cmd: list[str], capture: bool = True) -> str:
    # Uncaptured commands (the long fetch) send their progress to stderr, so this tool's
    # stdout carries only the final read.
    out = subprocess.run([str(c) for c in cmd], capture_output=capture, text=True,
                         stdout=None if capture else sys.stderr)
    if out.returncode != 0:
        detail = f"\n{(out.stdout or '')[-600:]}\n{(out.stderr or '')[-600:]}" if capture else ""
        if "was not found" in detail and "Policy version" in detail:
            detail += ("\nA policy version in the roster no longer exists. If it is one of the field set's ids, "
                       "the set is stale: list the current field with tools/field.py and update field_sets.json.")
        sys.exit(f"failed: {' '.join(str(c) for c in cmd[:4])} …{detail}")
    return out.stdout or ""


def record_path(record_id: str) -> Path:
    path = LAB / "experiments" / f"{record_id}.md"
    if not path.exists():
        sys.exit(f"no experiment record {path}; create it first (skills/experiment/scripts/record.py new)")
    return path


def evals_in(text: str) -> list[str]:
    """Batch ids in the record's frontmatter `evals: [a, b]` line."""
    match = re.search(r"^evals:\s*\[(.*)\]", text, re.M)
    return [e.strip() for e in match.group(1).split(",") if e.strip()] if match else []


def with_evals(text: str, ids: list[str], status: str | None = None) -> str:
    """The record text with its `evals:` list replaced by `ids` and, optionally, its status set."""
    updated, count = re.subn(r"^evals:\s*\[.*\]", "evals: [" + ", ".join(ids) + "]", text, count=1, flags=re.M)
    if not count:
        raise ValueError("the record has no `evals: [...]` line in its frontmatter")
    if status:
        updated = re.sub(r"^status:\s*\w+", f"status: {status}", updated, count=1, flags=re.M)
    return updated


def has_placeholders(text: str) -> bool:
    """True while the record is still the unfilled template (no hypothesis, no named policy)."""
    parts = text.split("---")
    frontmatter = parts[1] if len(parts) > 2 else ""
    return "<policy" in frontmatter or "One sentence: X happens because Y" in text


def launch(args: argparse.Namespace, record: Path) -> list[str]:
    text = record.read_text()
    if has_placeholders(text):
        sys.exit(f"{record.name} still has template placeholders; fill the hypothesis and decision rule first")
    if evals_in(text):
        sys.exit(f"{record.name} already lists batches; use --resume to fetch and read them")

    bodies_dir = LAB / ".runtime" / "requests"
    stem = bodies_dir / f"{args.record}.json"
    run([sys.executable, LAB / "tools" / "make_request.py", "paired", "--a", args.a, "--b", args.b,
         "--field-set", args.field_set, "-n", args.episodes, "--balanced", "--no-maps",
         "--note", args.record, "--out", stem])
    bodies = sorted(bodies_dir.glob(f"{args.record}-r*.json"))
    run([EVAL_REQUEST, "create", bodies[0], "--dry-run"])
    ids = []
    for body in bodies:
        ids.append(json.loads(run([EVAL_REQUEST, "create", body]))["created"])
        # Write after every create: an interrupted launch must not leave unrecorded batches.
        record.write_text(with_evals(text, ids, status="running"))
    print(f"launched {len(ids)} batches, {len(ids) * args.episodes} games; ids are in {record.name}", file=sys.stderr)
    return ids


def launch_alone(args: argparse.Namespace, record: Path) -> dict[str, list[str]]:
    """Create the two candidate-alone arms and append their ids to the record."""
    bodies_dir = LAB / ".runtime" / "requests"
    ids: dict[str, list[str]] = {"a": [], "b": []}
    for arm, ref in (("a", args.a), ("b", args.b)):
        stem = bodies_dir / f"{args.record}-alone-{arm}.json"
        run([sys.executable, LAB / "tools" / "make_request.py", "field", "--a", ref,
             "--field-set", args.field_set, "-n", args.episodes, "--balanced", "--no-maps",
             "--note", f"{args.record} candidate-alone check, arm {arm}", "--out", stem])
        bodies = sorted(bodies_dir.glob(f"{args.record}-alone-{arm}-r*.json"))
        if arm == "a":
            run([EVAL_REQUEST, "create", bodies[0], "--dry-run"])
        for body in bodies:
            ids[arm].append(json.loads(run([EVAL_REQUEST, "create", body]))["created"])
            current = record.read_text()
            record.write_text(with_evals(current, evals_in(current) + [ids[arm][-1]]))
    print(f"launched {len(ids['a']) + len(ids['b'])} batches, "
          f"{(len(ids['a']) + len(ids['b'])) * args.episodes} games; ids appended to {record.name}", file=sys.stderr)
    return ids


def run_alone(args: argparse.Namespace, record: Path) -> None:
    ids = launch_alone(args, record)
    base = LAB / ".runtime" / "artifacts"
    out = {arm: base / f"{args.record}-alone-{arm}" for arm in ("a", "b")}
    # One fetch per arm, one after the other: both sets of games play at the same time on
    # the platform, and each arm needs its own directory for compare.py.
    for arm in ("a", "b"):
        run([FETCH, *ids[arm], "--watch", "--out", out[arm]], capture=False)
        run([sys.executable, LAB / "tools" / "gzip_replays.py", out[arm]])
    label_a, label_b = args.a_label or args.a, args.b_label or args.b
    print(run([sys.executable, LAB / "tools" / "compare.py", out["b"], out["a"],
               "--baseline", label_b, "--candidate", label_a]))
    print(f"\nRead this against the pass mark in {record}.", file=sys.stderr)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--record", required=True, help="experiment record id (file name without .md)")
    ap.add_argument("--a", required=True, help="candidate: NAME:vN or a policy-version id")
    ap.add_argument("--b", required=True, help="baseline: NAME:vM or a policy-version id")
    ap.add_argument("--a-label", help="NAME:vN label for --a when it is an id")
    ap.add_argument("--b-label", help="NAME:vN label for --b when it is an id")
    ap.add_argument("--field-set", required=True)
    ap.add_argument("-n", "--episodes", type=int, default=6, help="games per body; total = 14 x n (default 6)")
    ap.add_argument("--resume", action="store_true", help="skip launch; fetch and read the batches in the record")
    ap.add_argument("--alone", action="store_true",
                    help="candidate-alone check: A alone and B alone against a six-seat field set")
    args = ap.parse_args(argv)

    record = record_path(args.record)
    if args.alone:
        run_alone(args, record)
        return
    ids = evals_in(record.read_text()) if args.resume else launch(args, record)
    if not ids:
        sys.exit(f"{record.name} lists no batches to resume")

    out = LAB / ".runtime" / "artifacts" / args.record
    run([FETCH, *ids, "--watch", "--out", out], capture=False)
    run([sys.executable, LAB / "tools" / "gzip_replays.py", out])

    label_a, label_b = args.a_label or args.a, args.b_label or args.b
    print(run([sys.executable, LAB / "tools" / "paired.py", out, "--a", label_a, "--b", label_b, "--json"]))
    for label in (label_a, label_b):
        report = run([sys.executable, LAB / "tools" / "wd.py", "metrics", out, "--policy", label])
        print("\n".join(line for line in report.splitlines() if line.startswith(("#", "taint", "overall", "coverage"))))
    print(f"\nRead this against the decision rule in {record}, then close the record.", file=sys.stderr)


if __name__ == "__main__":
    main()
