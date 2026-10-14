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
six-seat field set SET on `classic-press-short` (about 25 minutes). `--health-games N` makes it N games in
that one request (one game can fail for a reason that is not the build). Its id is printed and
written into the record's text as a `Health game:` line, not into `evals:`. Fetch it and read
`wd.py metrics` for it as the lab manual says; this tool does not wait for it.

`--variant VARIANT` runs a **screen stage** instead: the same paired, balanced design on another
variant, in practice `classic-press-short` (ends 1904, about 25 minutes against 50 to 75 for a
full game). It answers "does the build run, and did the mechanism fire" a game-length sooner,
and nothing about score: the short game has a different endgame, so its games get no
`paired.py` read and are never pooled with the full run. Its batch ids are appended to the
record's `evals:` and kept apart in a front-matter list `screen:`, so the paired launch and its
`--resume` leave them out (`--variant ... --resume` fetches them again). Artifacts go to
`.runtime/artifacts/<record id>-screen`; the read is each version's health lines
(`wd.py metrics`) and its behaviour table (`press_behaviour.py`). It can run before the full
launch or beside it. Write what the screen must show into the record's decision rule first.
`--config KEY=VALUE` (repeatable, screen stage only) shortens the screen further or shortens
the league's own variant: `--variant classic-press --config end_year=1903 --config
phase_minutes=2` is about 12 minutes of play. `make_request.py --help` has the settings.

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

`--dry-run` prices the run and launches nothing: it builds the same request bodies (in
`.runtime/requests/dry-run/`, apart from a launch's), checks the first against the live
schema, and prints the platform's quoted credits. It works with the paired run, `--alone`,
`--variant` and `--health`, and does not touch the record. **The platform has no route that
prices a request without creating it** (the quote exists only in the create response), so
the number is the platform's own estimate for the last request of the same kind that this
lab created: same variant, seats, LLM budget and games per request, read from the saved
create responses in `.runtime/requests/responses`. When no saved request has the same
games per request it prints the range between the nearest sizes, because the quote per
game is not the same at every size (2.23 a game at 1 to 3 games a request and 2.82 at 10,
on 2026-10-11) and it moves with time (3.3 a game five hours later), so a saved quote more than
an hour or two old can be well short. Its last line sets that beside what `tools/batches.py` reports for the
finished batches of the last 24 hours on the same variant: the estimate they were quoted
and the `cost_usd` the platform recorded after they ran.

It does not judge: read the output against the rule you wrote in the record,
then close the record yourself. `--resume` skips steps 1 to 4 and picks up at
the fetch, using the ids already in the record (for an interrupted run). The line
"launched N batches" on stderr also gives the platform's estimate in credits
(`cost_preview.estimated_cost_credits`, summed); it is an estimate, not the bill.

`--max-credits N` puts a limit on a paired launch. The platform prices a request only when it
is created, so the tool creates the first batch, reads its quote, and stops there if the whole
set at that price would pass N; it checks again after every batch, so a price that rises
mid-launch also stops it. A stopped launch has created some batches (their ids are in the
record) and prints how many; those do not cover every power and both seat orders. `--add-set`
launches one more full set into a record that already has batches, for a run sized in steps
(launch a small set, see its price, add another): the new ids join `evals:`, the games land in
the same folder, and the read covers every set together. Write the plan for sets into the
record's decision rule before the first launch; adding a set because a result looked close is
optional stopping.
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
from datetime import datetime, timedelta, timezone
from pathlib import Path

import batches

LAB = Path(__file__).resolve().parent.parent
ROOT = LAB.parent.parent
ALONE_MIN_GAMES = 30  # compare.py gives a verdict only from this many seats a side
EVAL_REQUEST = ROOT / "skills" / "run-eval" / "scripts" / "eval_request.py"
FETCH = ROOT / "skills" / "fetch-artifacts" / "scripts" / "fetch_artifacts.py"
RESPONSES = LAB / ".runtime" / "requests" / "responses"  # where `eval_request.py create` saves each response
TONIGHT_HOURS = 24  # the dry run compares its quote with finished batches launched within this many hours
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
    """The record's batch ids without the alone arms and the screen stage: what a paired `--resume` fetches."""
    apart = set(ids_in(text, "alone_a")) | set(ids_in(text, "alone_b")) | set(ids_in(text, "screen"))
    return [batch for batch in evals_in(text) if batch not in apart]


def paired_request(args: argparse.Namespace, stem: Path, variant: str | None = None) -> list:
    """The `make_request.py paired` command for this run; `variant` replaces the field set's own."""
    note = args.record if variant is None else f"{args.record} screen stage on {variant}"
    command = [sys.executable, LAB / "tools" / "make_request.py", "paired", "--a", args.a, "--b", args.b,
               "--field-set", args.field_set, "-n", args.episodes, "--balanced", "--no-maps",
               "--note", note, "--out", stem]
    if variant:
        command += ["--variant", variant] + [part for pair in args.config for part in ("--config", pair)]
    return command


def alone_request(args: argparse.Namespace, arm: str, ref: str, stem: Path) -> list:
    """The `make_request.py field` command for one arm of the candidate-alone check."""
    return [sys.executable, LAB / "tools" / "make_request.py", "field", "--a", ref,
            "--field-set", args.field_set, "-n", args.episodes, "--balanced", "--no-maps",
            "--note", f"{args.record} candidate-alone check, arm {arm}", "--out", stem]


def health_request(args: argparse.Namespace, body: Path) -> list:
    """The `make_request.py field` command for the one short health game of `--health`."""
    return [sys.executable, LAB / "tools" / "make_request.py", "field", "--a", args.a,
            "--field-set", args.health, "-n", args.health_games, "--variant", "classic-press-short", "--no-maps",
            "--note", f"{args.record} health game", "--out", body]


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


def over_limit(credits: float, last: float, left: int, max_credits: float | None) -> float | None:
    """The projected total when creating the `left` remaining bodies at the last body's quote would pass
    `max_credits`; None when it fits, when there is no limit, or when nothing is left to create."""
    projected = credits + last * left
    return projected if max_credits is not None and left and projected > max_credits else None


def stopped_line(done: int, total: int, games: int, credits: float, projected: float, max_credits: float) -> str:
    affordable = int(max_credits // (projected / total)) if projected else 0
    return (f"STOPPED at the credit limit: {done} of {total} batches launched, {games} games, {credits:.1f} credits "
            f"quoted. All {total} would be about {projected:.1f} at the price just quoted, over the limit of "
            f"{max_credits:.1f}. Nothing more was launched. The batches launched do not cover every power and "
            f"both seat orders, so they are not a balanced run by themselves: tell the user, then either raise "
            f"the limit and launch a full set beside them (--add-set), or read them as a partial run and say so "
            f"in the record. The limit covers {affordable} of {total} batches at this price.")


def add_set_stem(bodies_dir: Path, record_id: str) -> str:
    """The body-file stem of the next added set: `<record>-add2`, then `-add3`, ..."""
    used = {int(match.group(1)) for path in bodies_dir.glob(f"{record_id}-add*-r*.json")
            if (match := re.match(rf"{re.escape(record_id)}-add(\d+)-r", path.name))}
    return f"{record_id}-add{max(used, default=1) + 1}"


def launch(args: argparse.Namespace, record: Path) -> list[str]:
    """Create the paired bodies and write their ids into the record. Returns every paired id of the record.

    With `--add-set` the record already lists batches and one more full set is created beside them.
    With `--max-credits` the launch stops as soon as the bodies still to create, at the quote the
    platform gave for the last one, would take the run past the limit."""
    text = record.read_text()
    unfilled = placeholders(text)
    if unfilled:
        sys.exit(f"{record.name} still has template placeholders in its front matter; fill them first: "
                 + "; ".join(unfilled))
    earlier = paired_ids(text)
    if earlier and not args.add_set:
        sys.exit(f"{record.name} already lists batches; use --resume to fetch and read them, or --add-set to "
                 f"launch one more full set into the same record")
    if args.add_set and not earlier:
        sys.exit(f"{record.name} lists no batches yet; --add-set adds a set to a record that has been launched")

    bodies_dir = LAB / ".runtime" / "requests"
    stem = add_set_stem(bodies_dir, args.record) if args.add_set else args.record
    run(paired_request(args, bodies_dir / f"{stem}.json"))
    bodies = sorted(bodies_dir.glob(f"{stem}-r*.json"))
    run([EVAL_REQUEST, "create", bodies[0], "--dry-run"])
    ids, credits = [], 0.0
    for index, body in enumerate(bodies):
        created = json.loads(run([EVAL_REQUEST, "create", body]))
        ids.append(created["created"])
        credits += estimate(created)
        # Write after every create: an interrupted launch must not leave unrecorded batches.
        # From the file as it is now, so an edit made to the record meanwhile is kept.
        current = record.read_text()
        record.write_text(with_evals(current, evals_in(current) + [ids[-1]] if args.add_set else ids,
                                     status="running"))
        projected = over_limit(credits, estimate(created), len(bodies) - index - 1, args.max_credits)
        if projected is not None:
            print(stopped_line(len(ids), len(bodies), len(ids) * args.episodes, credits, projected,
                               args.max_credits), file=sys.stderr)
            break
    print(launched_line(len(ids), len(ids) * args.episodes, credits, f"ids are in {record.name}"), file=sys.stderr)
    return earlier + ids


def launch_health(args: argparse.Namespace, record: Path) -> str:
    """Create the short press health game(s), A alone against the six-seat set, and note the id in the record's text."""
    body = LAB / ".runtime" / "requests" / f"{args.record}-health.json"
    run(health_request(args, body))
    created = json.loads(run([EVAL_REQUEST, "create", body]))
    batch = created["created"]
    text = record.read_text()
    games = "1 game" if args.health_games == 1 else f"{args.health_games} games"
    record.write_text(text + ("" if text.endswith("\n") else "\n") + f"\nHealth game: `{batch}` "
                      f"({games}, `classic-press-short`, {args.a} alone; fetch into "
                      f"`.runtime/artifacts/{args.record}-health` and read `wd.py metrics`).\n")
    print(f"health request {batch} created, {games} (estimate {estimate(created):.1f} credits); "
          f"its id is in {record.name}, not in evals", file=sys.stderr)
    return batch


def launch_screen(args: argparse.Namespace, record: Path) -> list[str]:
    """Create the paired games on `--variant` and keep their ids apart, in `evals:` and in `screen:`."""
    bodies_dir = LAB / ".runtime" / "requests"
    run(paired_request(args, bodies_dir / f"{args.record}-screen.json", args.variant))
    bodies = sorted(bodies_dir.glob(f"{args.record}-screen-r*.json"))
    run([EVAL_REQUEST, "create", bodies[0], "--dry-run"])
    ids, credits = [], 0.0
    for body in bodies:
        created = json.loads(run([EVAL_REQUEST, "create", body]))
        ids.append(created["created"])
        credits += estimate(created)
        current = record.read_text()
        current = with_evals(current, evals_in(current) + [ids[-1]])
        # Also apart, so the paired `--resume` leaves these out and `--variant ... --resume` finds them.
        record.write_text(with_ids(current, "screen", ids))
    print(launched_line(len(ids), len(ids) * args.episodes, credits,
                        f"ids appended to {record.name} (evals, screen)"), file=sys.stderr)
    return ids


def run_screen(args: argparse.Namespace, record: Path) -> None:
    """The screen stage: the paired design on another variant, read for behaviour and health only."""
    if args.resume:
        ids = ids_in(record.read_text(), "screen")
        if not ids:
            sys.exit(f"{record.name} has no screen list to resume (it is written by --variant)")
    else:
        ids = launch_screen(args, record)
    out = LAB / ".runtime" / "artifacts" / f"{args.record}-screen"
    run([FETCH, *ids, "--watch", "--out", out], capture=False)
    run([sys.executable, LAB / "tools" / "gzip_replays.py", out])
    label_a, label_b = args.a_label or args.a, args.b_label or args.b
    for label in (label_a, label_b):
        report = run([sys.executable, LAB / "tools" / "wd.py", "metrics", out, "--policy", label])
        print("\n".join(line for line in report.splitlines()
                        if line.startswith(("#", "taint", "telemetry", "coverage"))))
        print(run([sys.executable, LAB / "tools" / "press_behaviour.py", out, "--policy", label]))
    print(f"\nScreen stage on {args.variant}: read the health lines and the behaviour table against the mechanism "
          f"check in {record}. It gives NO score verdict (the variant is not the league's), and its games are "
          "never pooled with the full run's.", file=sys.stderr)


def launch_alone(args: argparse.Namespace, record: Path) -> dict[str, list[str]]:
    """Create the two candidate-alone arms and append their ids to the record."""
    bodies_dir = LAB / ".runtime" / "requests"
    ids: dict[str, list[str]] = {"a": [], "b": []}
    credits = 0.0
    for arm, ref in (("a", args.a), ("b", args.b)):
        stem = bodies_dir / f"{args.record}-alone-{arm}.json"
        run(alone_request(args, arm, ref, stem))
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


def request_kind(variant: str | None, seats: int, llm_limit_per_seat: float | None) -> tuple:
    """What two requests must share for one's quote to stand for the other's, games per request aside."""
    return variant, seats, round(llm_limit_per_seat, 4) if llm_limit_per_seat else None


def saved_quotes(responses: Path) -> list[dict]:
    """The platform's estimates in the saved create responses, oldest first: kind, games, credits, when."""
    quotes = []
    for path in sorted(responses.glob("*.json")) if responses.is_dir() else []:
        saved = batches.read_json_file(path)
        preview = (saved or {}).get("cost_preview") if isinstance(saved, dict) else None
        games = (saved or {}).get("episode_count") if isinstance(saved, dict) else None
        if not preview or preview.get("estimated_cost_credits") is None or not games:
            continue
        seats = len((saved.get("requested") or {}).get("roster") or [])
        budget = preview.get("player_pod_llm_spend_limit_usd")
        quotes.append({"kind": request_kind(saved.get("variant_id"), seats, budget),
                       "games": games, "credits": float(preview["estimated_cost_credits"]),
                       "created_at": saved.get("created_at") or "", "file": path.name})
    return sorted(quotes, key=lambda q: q["created_at"])


def quote(body: dict, quotes: list[dict]) -> dict:
    """The platform's quote for one request like `body`, from the saved quotes of the same kind.

    `basis` is `exact` (a saved request with the same games per request: its newest quote),
    `between` (none of that size: the per-game quotes of the nearest smaller and larger sizes,
    as a range), `nearest` (sizes on one side only: that size's per-game quote) or `none`.
    `low` and `high` are credits for this one request; equal unless the basis is `between`."""
    seats = len(body.get("roster") or [])
    limit = body.get("episode_player_llm_spend_limit_usd")
    kind = request_kind((body.get("target") or {}).get("variant_id"), seats, limit / seats if limit and seats else None)
    games = body["num_episodes"]
    same = [q for q in quotes if q["kind"] == kind]
    if not same:
        return {"basis": "none", "low": None, "high": None, "from": []}
    exact = [q for q in same if q["games"] == games]
    if exact:
        return {"basis": "exact", "low": exact[-1]["credits"], "high": exact[-1]["credits"], "from": [exact[-1]]}
    newest_by_size = {q["games"]: q for q in same}  # oldest first, so the newest quote of each size is kept
    smaller = [size for size in newest_by_size if size < games]
    larger = [size for size in newest_by_size if size > games]
    used = [newest_by_size[size] for size in ([max(smaller)] if smaller else []) + ([min(larger)] if larger else [])]
    amounts = sorted(q["credits"] / q["games"] * games for q in used)
    return {"basis": "between" if len(used) == 2 else "nearest", "low": amounts[0], "high": amounts[-1], "from": used}


def _credits(low: float, high: float, digits: int = 1) -> str:
    """An amount, or a range when the two ends differ at the precision shown (2 digits for a per-game rate)."""
    return f"{low:.{digits}f}" if round(high - low, digits) == 0 else f"{low:.{digits}f} to {high:.{digits}f}"


def _pacific(iso: str) -> str:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(batches.PACIFIC).strftime("%m-%d %H:%M")


def quote_line(label: str, bodies: list[dict], quotes: list[dict]) -> tuple[str, float | None, float | None]:
    """One line of the dry run for a set of same-shaped requests, with the low and high total in credits."""
    games = sum(body["num_episodes"] for body in bodies)
    size = bodies[0]["num_episodes"]
    variant = (bodies[0].get("target") or {}).get("variant_id")
    head = f"{label}: {len(bodies)} request(s) x {size} game(s) = {games} game(s) on {variant}"
    each = [quote(body, quotes) for body in bodies]
    if any(q["basis"] == "none" for q in each):
        return f"{head}; no saved quote for a request of this kind (variant, seats, LLM budget)", None, None
    low, high = sum(q["low"] for q in each), sum(q["high"] for q in each)
    first = each[0]
    sizes = " and ".join(f"{q['credits'] / q['games']:.2f} a game at {q['games']} a request" for q in first["from"])
    when = ", ".join(sorted({_pacific(q["created_at"]) for q in first["from"] if q["created_at"]}))
    if first["basis"] == "exact":
        basis = f"the platform's quote for this same request, {sizes} (quoted {when} PT)"
    else:
        basis = f"no saved quote at {size} a request; the platform quoted {sizes} (quoted {when} PT)"
    a_game = _credits(low / games, high / games, 2)
    return f"{head}; {_credits(low, high)} credits ({a_game} a game): {basis}", low, high


def games_requested(batch: str, responses: Path) -> int | None:
    """The games this tool asked for in the batch it fetched into the folder `batch`; None when it launched none.

    A launch names its bodies, and so the saved create responses, `<folder>-r<rotation>[m].json`,
    and a set added with `--add-set` `<folder>-add<k>-r<rotation>[m].json`."""
    saved = [batches.read_json_file(path) for path in sorted(responses.glob(f"{batch}-*.json"))
             if re.fullmatch(r"(-add\d+)?-r\d+m?\.json", path.name[len(batch):])] if responses.is_dir() else []
    counts = [response.get("episode_count") for response in saved if isinstance(response, dict)]
    return sum(counts) if counts and all(counts) else None


def all_games_in(row: dict, responses: Path) -> bool:
    """Whether the batch is over: every game on disk completed, and none still to come.

    `fetch_artifacts.py --watch` fills a batch's folder as games end, so a batch that is still
    playing looks finished by its rows alone. For a batch this tool launched, the games asked
    for are known (`games_requested`); any other batch is judged by its rows."""
    if not row["finished"] or row["not_completed"]:
        return False
    asked = games_requested(row["batch"], responses)
    return asked is None or row["games"] == asked


def finished_line(variant: str, low: float | None, high: float | None, games: int, artifacts: Path, responses: Path,
                  now: datetime) -> str:
    """How this dry run's quote compares with `tools/batches.py`'s rows for recent finished batches on `variant`."""
    since = now - timedelta(hours=TONIGHT_HOURS)
    fetched = [artifacts] if artifacts.is_dir() else []  # a lab that has fetched nothing has no folder yet
    rows = [row for row in batches.batch_rows(fetched, batches.read_estimates(responses))
            if all_games_in(row, responses) and variant in row["variants"]
            and row["launched"] and datetime.fromisoformat(row["launched"]) >= since]
    if not rows:
        return (f"tools/batches.py: no finished batch on {variant} launched in the last {TONIGHT_HOURS} hours "
                f"below {artifacts}, so nothing to set this quote beside")
    played = sum(row["games"] for row in rows)
    line = (f"tools/batches.py, {len(rows)} finished batch(es) on {variant} in the last {TONIGHT_HOURS} hours, "
            f"{played} games: ")
    quoted = [row for row in rows
              if row["estimated_credits"] is not None and row["requests_with_estimate"] == row["requests"]]
    if quoted:
        per_game = sorted(row["estimated_credits"] / row["games"] for row in quoted)
        line += f"quoted {_credits(per_game[0], per_game[-1], 2)} credits a game at create"
        if low is not None:
            mine = (low / games, high / games)
            where = "the same" if abs(mine[0] - per_game[0]) < 0.05 and abs(mine[1] - per_game[-1]) < 0.05 else \
                "above" if mine[0] > per_game[-1] + 0.05 else "below" if mine[1] < per_game[0] - 0.05 \
                else "within that range"
            line += f" (this dry run: {_credits(*mine, 2)}, {where})"
    else:
        line += "no create estimate on disk for them"
    paid = [row for row in rows if row["cost_usd"] is not None]
    if paid:
        dollars = sum(row["cost_usd"] for row in paid) / sum(row["games_with_cost"] for row in paid)
        line += f"; recorded ${dollars:.2f} a game after they ran (`cost_usd`, dollars, not credits, not a bill)"
    return line


def dry_run_bodies(args: argparse.Namespace) -> list[tuple[str, list[dict]]]:
    """Build the bodies a launch would create, in a folder apart from a launch's, as (label, bodies) groups.

    The health game, when asked for, is the last group and is labelled "health game"."""
    bodies_dir = LAB / ".runtime" / "requests" / "dry-run"
    bodies_dir.mkdir(parents=True, exist_ok=True)
    groups = []
    if args.alone:
        for arm, ref in (("a", args.a), ("b", args.b)):
            run(alone_request(args, arm, ref, bodies_dir / f"{args.record}-alone-{arm}.json"))
            groups.append((f"alone, arm {arm} ({ref})", sorted(bodies_dir.glob(f"{args.record}-alone-{arm}-r*.json"))))
    elif args.variant:
        run(paired_request(args, bodies_dir / f"{args.record}-screen.json", args.variant))
        groups.append(("screen stage", sorted(bodies_dir.glob(f"{args.record}-screen-r*.json"))))
    else:
        run(paired_request(args, bodies_dir / f"{args.record}.json"))
        groups.append(("paired", sorted(bodies_dir.glob(f"{args.record}-r*.json"))))
    if args.health:
        body = bodies_dir / f"{args.record}-health.json"
        run(health_request(args, body))
        groups.append(("health game", [body]))
    run([EVAL_REQUEST, "create", groups[0][1][0], "--dry-run"])
    return [(label, [json.loads(path.read_text()) for path in paths]) for label, paths in groups]


def dry_run_report(groups: list[tuple[str, list[dict]]], quotes: list[dict], artifacts: Path, responses: Path,
                   now: datetime) -> str:
    """The dry run's text: one quote line per group, the total, and the line beside `tools/batches.py`."""
    lines = ["DRY RUN: nothing launched, no credits spent, the record is not touched."]
    totals = []
    for label, bodies in groups:
        line, low, high = quote_line(label, bodies, quotes)
        lines.append(line)
        totals.append((label, low, high, sum(body["num_episodes"] for body in bodies)))
    priced = all(low is not None for _, low, _, _ in totals)
    if priced and len(totals) > 1:
        lines.append(f"total: {_credits(sum(t[1] for t in totals), sum(t[2] for t in totals))} credits")
    lines.append("These are the platform's estimates for earlier requests of the same kind, not a fresh quote: it has "
                 "no route that prices a request without creating it. The launch prints the real one.")
    # The comparison is for the run's own games; the one short health game is left out of it.
    games = [t for t in totals if t[0] != "health game"]
    variant = (groups[0][1][0].get("target") or {}).get("variant_id")
    lines.append(finished_line(variant, sum(t[1] for t in games) if priced else None,
                               sum(t[2] for t in games) if priced else None, sum(t[3] for t in games),
                               artifacts, responses, now))
    return "\n".join(lines)


def dry_run(args: argparse.Namespace) -> None:
    """Price the run from the platform's saved quotes and launch nothing."""
    groups = dry_run_bodies(args)  # also checks the first body against the live schema
    print(dry_run_report(groups, saved_quotes(RESPONSES), LAB / ".runtime" / "artifacts", RESPONSES,
                         datetime.now(timezone.utc)))


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--record", required=True, help="experiment record id (file name without .md)")
    ap.add_argument("--a", required=True, help="candidate: NAME:vN or a policy-version id")
    ap.add_argument("--b", required=True, help="baseline: NAME:vM or a policy-version id")
    ap.add_argument("--a-label", help="NAME:vN label for --a when it is an id")
    ap.add_argument("--b-label", help="NAME:vN label for --b when it is an id")
    ap.add_argument("--field-set", required=True)
    ap.add_argument("-n", "--episodes", type=int, default=2,
                    help="games per body; total = 14 x n (default 2: 28 games, 39 to 92 credits in press "
                         "by the platform's estimate)")
    ap.add_argument("--resume", action="store_true",
                    help="skip launch; fetch and read the batches in the record (with --alone: the two alone arms)")
    ap.add_argument("--max-credits", type=float, metavar="N",
                    help="paired launch: stop creating batches as soon as the rest, at the price the platform "
                         "just quoted, would take this launch past N credits (the price is known only at create)")
    ap.add_argument("--add-set", action="store_true",
                    help="launch one more full paired set into a record that already lists batches, and read "
                         "all of its sets together")
    ap.add_argument("--dry-run", action="store_true",
                    help="launch nothing: build the bodies, check the first against the live schema, and print the "
                         "platform's quoted credits for requests of this kind, beside tonight's finished batches")
    ap.add_argument("--health", metavar="SET",
                    help="also launch one classic-press-short health game: --a alone against this six-seat field set")
    ap.add_argument("--health-games", type=int, default=1, metavar="N",
                    help="with --health: how many health games (default 1; 2 or 3 when a lost pod would cost time)")
    ap.add_argument("--alone", action="store_true",
                    help="candidate-alone check: A alone and B alone against a six-seat field set")
    ap.add_argument("--variant", metavar="VARIANT",
                    help="screen stage: play the paired design on this variant (classic-press-short, about 25 "
                         "minutes) and read health and behaviour only; no score verdict")
    ap.add_argument("--config", action="append", default=[], metavar="KEY=VALUE",
                    help="with --variant only: a game_config_overrides setting for the screen games, "
                         "e.g. end_year=1903 or phase_minutes=2 for a shorter game")
    args = ap.parse_args(argv)

    record = record_path(args.record)
    if args.config and not args.variant:
        sys.exit("--config changes the game, so it is for the screen stage only: give --variant too "
                 "(--variant classic-press keeps the league's variant)")
    if args.alone and args.variant:
        sys.exit("--alone and --variant are two different runs; give one")
    if (args.add_set or args.max_credits is not None) and (args.alone or args.variant or args.resume):
        sys.exit("--add-set and --max-credits apply to the paired launch only, not to --alone, --variant or --resume")
    if args.dry_run:
        if args.resume:
            sys.exit("--dry-run prices a launch and --resume skips the launch; give one")
        dry_run(args)
        return
    if args.alone:
        run_alone(args, record)
        return
    if args.variant:
        run_screen(args, record)
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
