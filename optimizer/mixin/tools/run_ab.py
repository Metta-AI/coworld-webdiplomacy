#!/usr/bin/env python3
"""Run one paired A/B end to end: bodies, dry run, launch, record, fetch, read.

    python3 games/webdiplomacy/tools/run_ab.py --record <experiment id> \\
        --a NAME:vN --b NAME:vM --field-set <set name> [-n 2]

Does, in order, what the lab manual's "Run one A/B" recipe lists by hand:

  1. `make_request.py paired --balanced --no-maps` (14 bodies: every power and
     both seat orders for each policy; total games = 14 x n),
  2. a dry run of the first body against the live schema,
  3. `eval_request.py create` for each body,
  4. writes the batch ids into the experiment record's `evals:` list and sets
     `status: running` (the record must already exist and be filled in: this
     tool will not launch while the record's front matter still has a `<...>`
     template placeholder in any field, `decision_rule` and `cost` included),
  5. one `fetch_artifacts.py --watch` over all batches into
     `.runtime/artifacts/<record id>`, then `gzip_replays.py`,
  6. prints `paired.py`'s report and both policies' health lines.

Step 6 reads the record's own folder, `.runtime/artifacts/<record id>`, always, and with
it any folders the record's front matter lists, `artifacts: [<folder>, ...]` (names under
`.runtime/artifacts`, read in the order written, the record's own last unless it is
listed). A follow-on record whose decision rule pools its games with an earlier record's
lists that record's folder. The IDE's Experiments page reads the same folders
(`artifact_folders` in `ide/webdip_ide/routes_experiments.py` is the same rule), and
neither reads a folder named only in the record's text.

`--health SET` also launches one health game, right after the batch's requests are created: `--a` alone against the
six-seat field set SET on `classic-press-short` (about 25 minutes). Its id is printed and
written into the record's text as a `Health game:` line, not into `evals:`. Fetch it and read
`wd.py metrics` for it as the lab manual says; this tool does not wait for it.

`--alone` runs the **candidate-alone check** instead: two separate arms, A alone and B
alone, each with the same six field seats and balanced powers (7 bodies x n per arm; the
field set must have six seats). Use it after any paired win, with a pass mark written in
the record first: a paired win can be a win over the other copy of our policy rather
than over the field. Its batch ids are
appended to the record's `evals:` and also kept apart in two front-matter lists, `alone_a:`
and `alone_b:`, so a later `--resume` of the paired run leaves them out and
`--alone --resume` fetches each arm again. Artifacts go to
`.runtime/artifacts/<record id>-alone-a` and `-alone-b`, and the read is `compare.py` (B as
baseline). `compare.py` gives a verdict only from 30 seats a side: `-n 5` (35 games an arm)
or more, and the tool says so when the size is below that.

It does not judge: read the output against the rule you wrote in the record,
then close the record yourself. `--resume` skips steps 1 to 4 and picks up at
the fetch, using the ids already in the record (for an interrupted run). The line
"launched N batches" on stderr also gives the platform's estimate in credits
(`cost_preview.estimated_cost_credits`, summed); it is an estimate, not the bill.
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
ALONE_MIN_GAMES = 30  # compare.py gives a verdict only from this many seats a side
EVAL_REQUEST = ROOT / "skills" / "run-eval" / "scripts" / "eval_request.py"
FETCH = ROOT / "skills" / "fetch-artifacts" / "scripts" / "fetch_artifacts.py"
PLACEHOLDER = re.compile(r"<[A-Za-z][^<>]*>")  # the record template's `<policy name>`, `<metric>`, ...
FOLDER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


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


def ids_in(text: str, key: str) -> list[str]:
    """The ids in a front-matter list line `key: [a, b]` (`alone_a`, `alone_b`); [] when the line is missing."""
    match = re.search(rf"^{key}:\s*\[(.*?)\]", text.split("\n---", 1)[0], re.M)
    return [e.strip() for e in match.group(1).split(",") if e.strip()] if match else []


def with_ids(text: str, key: str, ids: list[str]) -> str:
    """The record text with the front-matter line `key: [...]` set to `ids`; a missing line is added after `evals:`."""
    line = f"{key}: [" + ", ".join(ids) + "]"
    head, rule, rest = text.partition("\n---")
    updated, count = re.subn(rf"^{key}:\s*\[.*?\]", line, head, count=1, flags=re.M)
    if not count:
        updated, count = re.subn(r"^(evals:.*)$", lambda m: f"{m.group(1)}\n{line}", head, count=1, flags=re.M)
    if not count:
        raise ValueError("the record has no `evals: [...]` line in its frontmatter")
    return updated + rule + rest


def paired_ids(text: str) -> list[str]:
    """The record's batch ids without the candidate-alone arms: what a paired `--resume` fetches."""
    alone = set(ids_in(text, "alone_a")) | set(ids_in(text, "alone_b"))
    return [batch for batch in evals_in(text) if batch not in alone]


def estimate(created: dict) -> float:
    """The platform's estimate for one created request, in credits (0.0 when the response has none)."""
    return float((created.get("cost_preview") or {}).get("estimated_cost_credits") or 0.0)


def launched_line(batches: int, games: int, credits: float, where: str) -> str:
    cost = f"the platform estimates {credits:.1f} credits ({credits / games:.2f} a game)" if credits and games \
        else "the platform gave no estimate"
    return f"launched {batches} batches, {games} games; {cost}; {where}"


def with_evals(text: str, ids: list[str], status: str | None = None) -> str:
    """The record text with its `evals:` list replaced by `ids` and, optionally, its status set."""
    updated, count = re.subn(r"^evals:\s*\[.*\]", "evals: [" + ", ".join(ids) + "]", text, count=1, flags=re.M)
    if not count:
        raise ValueError("the record has no `evals: [...]` line in its frontmatter")
    if status:
        updated = re.sub(r"^status:\s*\w+", f"status: {status}", updated, count=1, flags=re.M)
    return updated


def artifact_names(text: str, record_id: str) -> list[str]:
    """The folders under `.runtime/artifacts` the record's result is read from.

    The names in the front matter's `artifacts: [a, b]` list, in the order written (a name may
    carry `.runtime/artifacts/` in front; one that is not a plain folder name is dropped), then
    the record's own id unless it is listed: this tool fetches there, so it is always read.
    The IDE's `artifact_folders` (ide/webdip_ide/routes_experiments.py) is the same rule."""
    match = re.search(r"^artifacts:\s*\[(.*?)\]", text.split("\n---", 1)[0], re.M)
    listed = [name.strip().strip("`\"'").rstrip("/").rpartition("/")[2] for name in match.group(1).split(",")] \
        if match else []
    return list(dict.fromkeys([name for name in listed if FOLDER_NAME.match(name)] + [record_id]))


def artifact_dirs(text: str, record_id: str) -> list[Path]:
    return [LAB / ".runtime" / "artifacts" / name for name in artifact_names(text, record_id)]


def placeholders(text: str) -> list[str]:
    """The template's `<...>` placeholders still in the record's front matter (`<policy name>`,
    `<metric>`, `<what a run would spend, ...>`), and the template's hypothesis sentence."""
    parts = text.split("---")
    frontmatter = parts[1] if len(parts) > 2 else ""
    found = PLACEHOLDER.findall(frontmatter)
    if "One sentence: X happens because Y" in frontmatter:
        found.append("One sentence: X happens because Y …")
    return found


def launch(args: argparse.Namespace, record: Path) -> list[str]:
    text = record.read_text()
    unfilled = placeholders(text)
    if unfilled:
        sys.exit(f"{record.name} still has template placeholders in its front matter; fill them first: "
                 + "; ".join(unfilled))
    if paired_ids(text):
        sys.exit(f"{record.name} already lists batches; use --resume to fetch and read them")

    bodies_dir = LAB / ".runtime" / "requests"
    stem = bodies_dir / f"{args.record}.json"
    run([sys.executable, LAB / "tools" / "make_request.py", "paired", "--a", args.a, "--b", args.b,
         "--field-set", args.field_set, "-n", args.episodes, "--balanced", "--no-maps",
         "--note", args.record, "--out", stem])
    bodies = sorted(bodies_dir.glob(f"{args.record}-r*.json"))
    run([EVAL_REQUEST, "create", bodies[0], "--dry-run"])
    ids, credits = [], 0.0
    for body in bodies:
        created = json.loads(run([EVAL_REQUEST, "create", body]))
        ids.append(created["created"])
        credits += estimate(created)
        # Write after every create: an interrupted launch must not leave unrecorded batches.
        # From the file as it is now, so an edit made to the record meanwhile is kept.
        record.write_text(with_evals(record.read_text(), ids, status="running"))
    print(launched_line(len(ids), len(ids) * args.episodes, credits, f"ids are in {record.name}"), file=sys.stderr)
    return ids


def launch_health(args: argparse.Namespace, record: Path) -> str:
    """Create one short press game with A alone against the six-seat set, and note its id in the record's text."""
    body = LAB / ".runtime" / "requests" / f"{args.record}-health.json"
    run([sys.executable, LAB / "tools" / "make_request.py", "field", "--a", args.a,
         "--field-set", args.health, "-n", 1, "--variant", "classic-press-short", "--no-maps",
         "--note", f"{args.record} health game", "--out", body])
    created = json.loads(run([EVAL_REQUEST, "create", body]))
    batch = created["created"]
    text = record.read_text()
    record.write_text(text + ("" if text.endswith("\n") else "\n") + f"\nHealth game: `{batch}` "
                      f"(`classic-press-short`, {args.a} alone; fetch into `.runtime/artifacts/{args.record}-health` "
                      "and read `wd.py metrics`).\n")
    print(f"health game {batch} created (estimate {estimate(created):.1f} credits); its id is in {record.name}, "
          "not in evals", file=sys.stderr)
    return batch


def launch_alone(args: argparse.Namespace, record: Path) -> dict[str, list[str]]:
    """Create the two candidate-alone arms and append their ids to the record."""
    bodies_dir = LAB / ".runtime" / "requests"
    ids: dict[str, list[str]] = {"a": [], "b": []}
    credits = 0.0
    for arm, ref in (("a", args.a), ("b", args.b)):
        stem = bodies_dir / f"{args.record}-alone-{arm}.json"
        run([sys.executable, LAB / "tools" / "make_request.py", "field", "--a", ref,
             "--field-set", args.field_set, "-n", args.episodes, "--balanced", "--no-maps",
             "--note", f"{args.record} candidate-alone check, arm {arm}", "--out", stem])
        bodies = sorted(bodies_dir.glob(f"{args.record}-alone-{arm}-r*.json"))
        if arm == "a":
            run([EVAL_REQUEST, "create", bodies[0], "--dry-run"])
        for body in bodies:
            created = json.loads(run([EVAL_REQUEST, "create", body]))
            ids[arm].append(created["created"])
            credits += estimate(created)
            current = record.read_text()
            current = with_evals(current, evals_in(current) + [ids[arm][-1]])
            # Also by arm, so the paired `--resume` can leave these out and `--alone --resume` can find them.
            record.write_text(with_ids(current, f"alone_{arm}", ids[arm]))
    batches = len(ids["a"]) + len(ids["b"])
    print(launched_line(batches, batches * args.episodes, credits,
                        f"ids appended to {record.name} (evals, alone_a, alone_b)"), file=sys.stderr)
    return ids


def run_alone(args: argparse.Namespace, record: Path) -> None:
    if 7 * args.episodes < ALONE_MIN_GAMES:
        print(f"{7 * args.episodes} games per arm is below compare.py's floor of {ALONE_MIN_GAMES}: this run can "
              "catch a large reversal and nothing else; use -n 5 or more for a pass or fail", file=sys.stderr)
    if args.resume:
        text = record.read_text()
        ids = {arm: ids_in(text, f"alone_{arm}") for arm in ("a", "b")}
        if not (ids["a"] and ids["b"]):
            sys.exit(f"{record.name} has no alone_a and alone_b lists to resume (they are written by --alone)")
    else:
        ids = launch_alone(args, record)
    base = LAB / ".runtime" / "artifacts"
    out = {arm: base / f"{args.record}-alone-{arm}" for arm in ("a", "b")}
    # One fetch per arm (each arm needs its own directory for compare.py), both at once:
    # the two arms play at the same time, and fetching them one after the other would leave
    # arm B unread until arm A's last game ended.
    watches = [subprocess.Popen([str(c) for c in (FETCH, *ids[arm], "--watch", "--out", out[arm])], stdout=sys.stderr)
               for arm in ("a", "b")]
    failed = [watch.args[-1] for watch in watches if watch.wait() != 0]
    if failed:
        sys.exit(f"failed: the fetch into {', '.join(failed)}; re-run fetch_artifacts.py for that arm by hand")
    for arm in ("a", "b"):
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
    ap.add_argument("-n", "--episodes", type=int, default=2,
                    help="games per body; total = 14 x n (default 2: 28 games, about 50 credits in press "
                         "by the platform's estimate)")
    ap.add_argument("--resume", action="store_true",
                    help="skip launch; fetch and read the batches in the record (with --alone: the two alone arms)")
    ap.add_argument("--health", metavar="SET",
                    help="also launch one classic-press-short health game: --a alone against this six-seat field set")
    ap.add_argument("--alone", action="store_true",
                    help="candidate-alone check: A alone and B alone against a six-seat field set")
    args = ap.parse_args(argv)

    record = record_path(args.record)
    if args.alone:
        run_alone(args, record)
        return
    ids = paired_ids(record.read_text()) if args.resume else launch(args, record)
    if not ids:
        sys.exit(f"{record.name} lists no batches to resume")
    if args.health and not args.resume:
        launch_health(args, record)

    out = LAB / ".runtime" / "artifacts" / args.record
    run([FETCH, *ids, "--watch", "--out", out], capture=False)
    run([sys.executable, LAB / "tools" / "gzip_replays.py", out])

    label_a, label_b = args.a_label or args.a, args.b_label or args.b
    folders = [folder for folder in artifact_dirs(record.read_text(), args.record) if folder.is_dir()]
    if len(folders) > 1:
        print(f"reading {len(folders)} folders pooled, as the record's `artifacts:` lists them: "
              + ", ".join(folder.name for folder in folders), file=sys.stderr)
    print(run([sys.executable, LAB / "tools" / "paired.py", *folders, "--a", label_a, "--b", label_b, "--json"]))
    for label in (label_a, label_b):
        report = run([sys.executable, LAB / "tools" / "wd.py", "metrics", out, "--policy", label])
        print("\n".join(line for line in report.splitlines() if line.startswith(("#", "taint", "overall", "coverage"))))
    print(f"\nRead this against the decision rule in {record}, then close the record.", file=sys.stderr)


if __name__ == "__main__":
    main()
