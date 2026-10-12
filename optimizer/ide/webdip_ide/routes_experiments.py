"""Experiments: the improvement loop as the lab records it.

The agent writes one record per hypothesis before it runs anything (the optimizer-seed
`experiment` skill): `<lab>/experiments/<id>.md`, with front matter (`id`, `policy`, `baseline`,
`candidate`, `status`, `hypothesis`, `decision_rule`, `evals`, and this lab's two optional keys,
`artifacts` and `cost`) and sections (Context, Predictions, Design, Result, Verdict).
`_template.md` is the template and is not a record. The files are the record: this module lists
and renders them, and never writes one.

Pages:
  /experiments           every record, newest first, each with its paired result so far, and
                         "What is closed": the entries of `open_levers.md` (tested, no result yet),
                         `closed_levers.md` and `best_practices.md`
  /experiments/<id>      one record: its front matter, the result so far, the version-log rows of
                         its two versions, requests to the agent, and the record's text

JSON:
  GET /api/experiments   [{id, title, status, policy, baseline, candidate, hypothesis,
                           decision_rule, cost, evals, artifacts, batch, path, link, result}]

The result so far is not computed here. It is the lab's `tools/paired.py` (`paired_report`, the
function behind the command the agent runs) on the games in the record's artifact folders: the
folders its `artifacts: [folder, folder]` key names (a follow-on record whose rule pools its own
games with an earlier record's), and always `.runtime/artifacts/<id>/`, which is where
`tools/run_ab.py` fetches them. `tools/run_ab.py: artifact_dirs` is the same rule. The games are the ones
the dashboard has already read (`routes_dashboard.CACHE`), so a page never parses a game and
never waits for a read: while games are still being read it shows what is in and says so.
"""

from __future__ import annotations

import importlib
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Request

from . import paths, reports_markdown, routes_dashboard
from .routes_dashboard import plain, signed
from .server import render

router = APIRouter()
NAV = ("Experiments", "/experiments")

STATUSES = ("proposed", "running", "confirmed", "refuted", "inconclusive")  # the seed's `record.py`
OPEN = ("proposed", "running")  # no verdict yet
STATUS_TONE = {"running": "warn", "confirmed": "ok", "refuted": "err"}  # the rest stay plain
SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
# Fields of a record made for the pages, left out of the JSON.
PAGE_ONLY = ("body", "modified", "rule_brief", "planned", "date", "hypothesis_html", "decision_rule_html",
             "alone_launched")
# Where `run_ab.py --alone` fetches each arm, and the front-matter list it writes the arm's batch ids in.
ALONE_ARMS = (("-alone-a", "candidate", "alone_a"), ("-alone-b", "baseline", "alone_b"))

_PLACEHOLDER = re.compile(r"<[A-Za-z][^<>]*>")  # the template's `<policy name>`, `<metric>`, `<Experiment title>`
_COMMENT = re.compile(r"(^|\s)#.*$")
_BLOCK_SCALAR = (">", "|", ">-", "|-", ">+", "|+")
# The parts of a decision rule that fit on one line: "+0.08 or more with z >= 2 over 28 balanced paired games"
# (or "on 28 balanced paired games").
_THRESHOLD = re.compile(r"([+\-−]\s?\d*\.\d+)\s+or more")
_MIN_Z = re.compile(r"\bz\s*(?:>=|≥)\s*(\d+(?:\.\d+)?)")
_PLANNED = re.compile(r"\b(?:over|on)\s+(\d+)\s+(?:[\w-]+\s+){0,3}games\b")
# The line under an entry's name: what refuted it (`closed_levers.md`), or what was measured (`open_levers.md`).
_KILLED_BY = re.compile(r"\*\*(?:Killed by|Read):\*\*\s*(.+?)(?=\n\*\*|\Z)", re.S)
_CLOSED_ON = re.compile(r"^(.*?)\s{2,}(?:closed|tested)\s+(.+)$")


# --- reading a record -----------------------------------------------------------------


def _scalar(text: str) -> str:
    return _COMMENT.sub("", text).strip().strip("\"'")


def front_matter(text: str) -> tuple[dict, str]:
    """(a record's front matter, the rest of the file).

    Reads the shapes the record template uses and no more: `key: value` with a trailing
    `# comment`, a folded value (`key: >` and indented lines, joined with spaces), and a list
    written as `[a, b]` or as `- a` lines. The IDE has no YAML library, and a record the seed's
    `record.py validate` accepts is written this way.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    end = next((i for i, line in enumerate(lines[1:], start=1) if line.strip() == "---"), None)
    if end is None:
        return {}, text
    meta: dict = {}
    key = ""
    for line in lines[1:end]:
        item = re.match(r"\s*-\s+(.*)$", line)
        if key and item and (meta[key] == "" or isinstance(meta[key], list)):
            meta[key] = [*meta[key], _scalar(item.group(1))]
        elif key and line[:1] in (" ", "\t") and isinstance(meta[key], str):
            meta[key] = f"{meta[key]} {line.strip()}".strip()
        else:
            name, colon, value = line.partition(":")
            if not colon or not name.strip():
                continue
            key = name.strip().lower()
            value = _scalar(value)
            if value in _BLOCK_SCALAR:
                value = ""
            elif value.startswith("[") and value.endswith("]"):
                value = [_scalar(part) for part in value[1:-1].split(",") if part.strip()]
            meta[key] = value
    return meta, "\n".join(lines[end + 1 :])


def rule_brief(rule: str) -> str:
    """A decision rule's threshold in a few words ("+0.08 or more, z ≥ 2, 28 games"), or "" when
    the rule does not state one in the usual words. The whole rule is on the record's page."""
    threshold, min_z, planned = _THRESHOLD.search(rule), _MIN_Z.search(rule), _PLANNED.search(rule)
    if not threshold:
        return ""
    parts = [f"{threshold.group(1).replace(' ', '').replace('-', '−')} or more"]
    if min_z:
        parts.append(f"z ≥ {min_z.group(1)}")
    if planned:
        parts.append(f"{planned.group(1)} games")
    return ", ".join(parts)


def read_record(path: Path) -> dict:
    """One record. A field the agent has not filled in yet (the template's `<...>` text) is ""."""
    meta, body = front_matter(path.read_text(errors="replace"))

    def field(name: str) -> str:
        value = meta.get(name)
        return value if isinstance(value, str) and not _PLACEHOLDER.search(value) else ""

    heading = reports_markdown.first_heading(body) or ""
    status = field("status").lower()
    rule = field("decision_rule")
    planned = _PLANNED.search(rule)
    folders = artifact_folders(meta.get("artifacts"), path.stem)
    candidate = field("candidate")
    return {
        "id": path.stem,
        "title": heading if heading and not _PLACEHOLDER.search(heading) else path.stem,
        "date": path.stem[:10] if re.match(r"\d{4}-\d{2}-\d{2}", path.stem) else "",
        "modified": path.stat().st_mtime,
        "status": status if status in STATUSES else "unknown",
        "policy": field("policy"),
        "baseline": field("baseline"),
        "candidate": "" if candidate.lower().startswith("n/a") else candidate,
        "hypothesis": field("hypothesis"),
        "hypothesis_html": reports_markdown.render_inline(field("hypothesis")),
        "decision_rule": rule,
        "decision_rule_html": reports_markdown.render_inline(rule),
        "rule_brief": rule_brief(rule),
        "planned": int(planned.group(1)) if planned else None,
        "cost": field("cost"),
        "evals": [e for e in meta["evals"] if e] if isinstance(meta.get("evals"), list) else [],
        # The folders under `.runtime/artifacts` whose games the result is read from.
        "artifacts": folders,
        "batch": folders[0],  # the first folder; kept for readers of the JSON from before a record could name several
        # `run_ab.py --alone` has created batches for the candidate-alone check, whether or not a game is in yet.
        "alone_launched": any(isinstance(meta.get(key), list) and meta[key] for _, _, key in ALONE_ARMS),
        "path": str(path.relative_to(paths.lab_dir())),
        "link": f"/experiments/{path.stem}",
        "body": body,
    }


def artifact_folders(listed, record_id: str) -> list[str]:
    """The folders under `.runtime/artifacts` a record's games are in.

    The names in the front matter's `artifacts: [folder, folder]`, in the order written (a folder
    may be written with or without `.runtime/artifacts/` in front), and then always the record's
    own id, which is where `tools/run_ab.py --record <id>` fetches. An empty or missing list is
    the record's own folder alone. `tools/run_ab.py: artifact_dirs` reads the key the same way.
    """
    names = [str(item).strip().strip("`\"'").rstrip("/").rpartition("/")[2] for item in listed] \
        if isinstance(listed, list) else []  # fmt: skip
    return list(dict.fromkeys([name for name in names if SLUG.match(name)] + [record_id]))


def experiments_dir() -> Path:
    return paths.lab_dir() / "experiments"


def list_records() -> list[dict]:
    """Every record, newest first (by the date its id starts with, then by file time)."""
    folder = experiments_dir()
    found = [p for p in folder.glob("*.md") if not p.name.startswith("_")] if folder.is_dir() else []
    return sorted((read_record(p) for p in found), key=lambda r: (r["date"], r["modified"]), reverse=True)


# --- the result so far ----------------------------------------------------------------


def paired():
    """The lab's `tools/paired.py`."""
    paths.use_lab_tools()
    return importlib.import_module("paired")


def run_ab():
    """The lab's `tools/run_ab.py`."""
    paths.use_lab_tools()
    return importlib.import_module("run_ab")


def games_by_batch() -> tuple[dict[str, dict], int]:
    """(the games read so far under each folder of `.runtime/artifacts`, by episode id; games still to be read).

    Does not wait for a large read: `CACHE` hands out what it has and goes on reading."""
    by_directory, pending, _ = routes_dashboard.CACHE.sync_by_directory(0.0)
    prefix = str(paths.artifacts_dir()) + os.sep
    batches: dict[str, dict] = defaultdict(dict)
    for directory, game in by_directory.items():
        below = directory[len(prefix) :].split(os.sep) if directory.startswith(prefix) else []
        if len(below) > 1:
            batches[below[0]][below[-1]] = game
    return batches, pending


def _finished(games: dict) -> dict:
    return {episode: game for episode, game in games.items() if game.seats and not game.missing_results}


def _games(count: int) -> str:
    return f"{count} game{'' if count == 1 else 's'}"


def _family(record: dict) -> str:
    """The policy name the record's games are followed by: the candidate's, else the record's `policy`."""
    return record["candidate"].rpartition(":")[0] or record["policy"]


def _short(candidate: str, baseline: str) -> tuple[str, str]:
    """('v2', 'v1') for two versions of one policy; the full names otherwise."""
    (a_name, _, a_version), (b_name, _, b_version) = candidate.rpartition(":"), baseline.rpartition(":")
    return (a_version, b_version) if a_name and a_name == b_name else (candidate, baseline)


def alone_check(record: dict, batches: dict[str, dict]) -> list[dict]:
    """The two arms of the candidate-alone check: [{who, games, progress}], or [] when it was never launched.

    `run_ab.py --alone` names its two folders after the record, whatever the record pools. How
    many games an arm asked for is the tool's own count (`run_ab.games_requested`, from the saved
    create responses); a lab that did not launch the arm with the tool has none, and the line
    then says how many are in so far.
    """
    on_disk = {who: len(_finished(batches.get(record["id"] + suffix, {}))) for suffix, who, _ in ALONE_ARMS}
    if not (record["alone_launched"] or any(on_disk.values())):
        return []
    responses = paths.lab_dir() / ".runtime" / "requests" / "responses"
    arms = []
    for suffix, who, _ in ALONE_ARMS:
        games = on_disk[who]
        asked = run_ab().games_requested(record["id"] + suffix, responses)
        if asked:
            progress = f"{games} of {asked} games in"
        else:
            progress = f"{_games(games)} in so far" if games else "no games in yet"
        arms.append({"who": who, "games": games, "progress": progress})
    return arms


def result_so_far(record: dict, batches: dict[str, dict], pending: int) -> dict:
    """What the games on disk say now: how many are in, and `paired.py`'s report (candidate minus
    baseline) when both versions have games. `report` is None until then."""
    pooled: dict = {}  # by episode id: a game fetched into two of the folders counts once
    folders = []
    for folder in record["artifacts"]:
        new = {episode: game for episode, game in _finished(batches.get(folder, {})).items() if episode not in pooled}
        pooled.update(new)
        folders.append({"name": folder, "games": len(new),
                        "replays": "/replays?" + urlencode({"batch": folder, "policy": _family(record)})})  # fmt: skip
    games = list(pooled.values())
    if record["planned"]:
        progress = f"{len(games)} of {record['planned']} games in"
    else:
        progress = f"{_games(len(games))} in" if games else "no games in yet"
    out = {"games_in": len(games), "planned": record["planned"], "progress": progress, "pending": pending,
           "folders": folders, "covers": ", ".join(f"{f['name']} ({f['games']})" for f in folders),
           "report": None, "words": "", "verdict": "", "tone": "", "win": False,
           "alone": alone_check(record, batches)}
    if not (games and record["candidate"] and record["baseline"]):
        return out
    seats = [seat for game in games for seat in game.seats]
    report = paired().paired_report(seats, record["candidate"], record["baseline"])
    if not report["n"]:
        return out
    a, b = _short(record["candidate"], record["baseline"])
    n = report["n"]
    out.update(
        report=report,
        minus=f"{a} minus {b}",
        diff=signed(report["diff"]),
        z=signed(report["z"], 2),
        words=(f"{signed(report['diff'])}, SE {plain(report['se'])}, z {signed(report['z'], 2)} "
               f"over {n} paired game{'' if n == 1 else 's'}"),
        verdict=report["verdict"],
        win=report["verdict"] == f"{record['candidate']} ahead",
        tone={f"{record['candidate']} ahead": "ok", f"{record['baseline']} ahead": "err"}.get(report["verdict"], ""),
    )  # fmt: skip
    return out


def statuses() -> dict[str, str]:
    """Every record's status by id. The agent panel reads it with the cards (`/api/cards`), so an idea
    card whose record has been run stops offering to run it."""
    return {record["id"]: record["status"] for record in list_records()}


def running() -> list[dict]:
    """The records with status `running`, each with how many of its games are in (for the home page)."""
    records = [record for record in list_records() if record["status"] == "running"]
    if not records:
        return []
    batches, pending = games_by_batch()
    return [{**record, "result": result_so_far(record, batches, pending)} for record in records]


# --- what is closed, and the version log -----------------------------------------------


def register(name: str) -> list[dict]:
    """The `## ` sections of one of the lab's registers (`closed_levers.md`, `open_levers.md`,
    `best_practices.md`): [{name, closed, killed_by, entries, html}]. `closed` is the date in the
    heading ("closed YYYY-MM-DD", "tested YYYY-MM-DD") and `killed_by` the entry's **Killed by:**
    or **Read:** line. The text before the first section is its preface."""
    path = paths.lab_dir() / name
    if not path.is_file():
        return []
    # Without the fenced blocks: the format example in a register's preface is not an entry.
    text = re.sub(r"^```.*?^```", "", path.read_text(errors="replace"), flags=re.M | re.S)
    parts = re.split(r"^## +(.+)$", text, flags=re.M)[1:]
    out = []
    for heading, body in zip(parts[::2], parts[1::2]):
        dated = _CLOSED_ON.match(heading.strip())
        killed = _KILLED_BY.search(body)
        out.append({
            "name": dated.group(1) if dated else heading.strip(),
            "closed": dated.group(2) if dated else "",
            "killed_by": reports_markdown.render_inline(" ".join(killed.group(1).split())) if killed else "",
            "entries": len(re.findall(r"^[-*] ", body, flags=re.M)),
            # Each "**Mechanism:** ..." line is its own paragraph, as the register sets them out.
            "html": reports_markdown.render(re.sub(r"\n(?=\*\*)", "\n\n", body)),
        })  # fmt: skip
    return out


def version_rows(versions: list[str]) -> list[dict]:
    """The rows of `players/*/VERSION_LOG.md` for these versions, in the order asked for."""
    found: dict[str, dict] = {}
    for log in sorted((paths.lab_dir() / "players").glob("*/VERSION_LOG.md")):
        header: list[str] = []
        for line in log.read_text(errors="replace").splitlines():
            if not line.startswith("|"):
                header = []
                continue
            cells = reports_markdown._cells(line)
            if cells[0].lower() == "version":
                header = [cell.lower() for cell in cells]
            elif header and cells[0] in versions:
                row = dict(zip(header, cells))

                def column(start: str) -> str:
                    return next((value for name, value in row.items() if name.startswith(start)), "")

                uploaded = column("uploaded")
                if any(name.startswith("uploaded") and "utc" in name for name in header):
                    try:
                        uploaded = datetime.fromisoformat(uploaded).replace(tzinfo=timezone.utc)
                    except ValueError:
                        pass  # "—" for a version that was never uploaded: shown as written
                found[cells[0]] = {
                    "version": cells[0], "uploaded": uploaded,
                    "change": reports_markdown.render_inline(column("the one change")),
                    "validation": reports_markdown.render_inline(column("validation")),
                    "log": str(log.relative_to(paths.lab_dir())),
                }  # fmt: skip
    return [found[version] for version in versions if version in found]


# --- requests to the agent -------------------------------------------------------------


def asks(record: dict, result: dict) -> list[dict]:
    """The requests this record's page offers, as text for the message box (the user sends it)."""
    out = []
    name = f"{record['id']} (“{record['title']}”)" if record["title"] != record["id"] else record["id"]
    card = f"post a result card that links to {record['link']}"
    started = record["status"] == "running" or bool(result["games_in"])
    if record["status"] == "proposed" and not started:
        out.append({"label": "Run this", "text": (
            f"Run the proposed experiment {name}. Check closed_levers.md, open_levers.md and the earlier records in "
            "experiments/, and the record's predictions and decision rule once more, tell me what it will cost "
            "before you launch, then make the one change as a new version "
            f"(tools/ship.py --experiment {record['id']}), write it in the record as the candidate, run the paired "
            f"A/B (tools/run_ab.py --record {record['id']}) and a health game, and {card}."
        )})  # fmt: skip
    if record["status"] in OPEN and started:
        folders = " and ".join(f".runtime/artifacts/{folder}" for folder in record["artifacts"])
        out.append({"label": "Ask the agent for the result", "text": (
            f"What is the result of experiment {name} so far? Read the games in {folders} "
            f"with tools/paired.py ({record['candidate'] or 'the candidate'} against "
            f"{record['baseline'] or 'the baseline'}), read the number against the record's decision rule, and {card}."
        )})  # fmt: skip
        out.append({"label": "Ask the agent to close this record", "text": (
            f"Close the experiment record {name} with the experiment skill: write its Result and Verdict against the "
            "decision rule that was written before the run, set its status, add the lever to closed_levers.md if it "
            f"is refuted or to open_levers.md if it is inconclusive, run record.py validate, and {card}."
        )})  # fmt: skip
    if result["win"] and not result["alone"]:  # once launched, the page shows its progress and no second launch
        out.append({"label": "Ask for the candidate-alone check", "text": (
            f"Experiment {name} shows a paired win for {record['candidate']}. Run the candidate-alone check before "
            f"any promotion: write its pass mark in the record first, then tools/run_ab.py --record {record['id']} "
            f"--alone, and {card}."
        )})  # fmt: skip
    return out


# --- routes ---------------------------------------------------------------------------


def _links(record: dict) -> dict:
    """Where the candidate's numbers are on the dashboard. (The games: `result_so_far`'s `folders`, one
    Replays link each, with `policy` in it: without it the browser follows the remembered policy, which
    may not be in these games.)"""
    name, _, version = record["candidate"].rpartition(":")
    return {"dashboard": "/dashboard?" + urlencode({"policy": name, "version": version}) if name else ""}


@router.get("/experiments")
def experiments_page(request: Request):
    records = list_records()
    batches, pending = games_by_batch() if records else ({}, 0)
    rows = [{**record, "result": result_so_far(record, batches, pending)} for record in records]
    return render(
        request,
        "experiments.html",
        rows=rows,
        pending=pending,
        any_running=any(row["status"] == "running" for row in rows),
        asks={row["id"]: asks(row, row["result"]) for row in rows if row["status"] == "proposed"},
        tones=STATUS_TONE,
        levers=register("closed_levers.md"),
        open_levers=register("open_levers.md"),
        practices=register("best_practices.md"),
        folder=str(experiments_dir()),
    )


@router.get("/experiments/{record_id}")
def experiment_page(request: Request, record_id: str):
    path = experiments_dir() / f"{record_id}.md"
    if not SLUG.match(record_id) or record_id.startswith("_") or not path.is_file():
        # A card may link to a record that was renamed or not written yet.
        response = render(request, "experiments_missing.html", record_id=record_id)
        response.status_code = 404
        return response
    record = read_record(path)
    batches, pending = games_by_batch()
    result = result_so_far(record, batches, pending)
    return render(
        request,
        "experiments_view.html",
        record=record,
        result=result,
        tones=STATUS_TONE,
        is_open=record["status"] in OPEN,
        links=_links(record),
        versions=version_rows([v for v in (record["baseline"], record["candidate"]) if v]),
        asks=asks(record, result),
        html=reports_markdown.render(record["body"], drop_first_h1=True),
        plain=plain,
    )


@router.get("/api/experiments")
def experiments_json():
    records = list_records()
    batches, pending = games_by_batch() if records else ({}, 0)
    out = []
    for record in records:
        result = result_so_far(record, batches, pending)
        row = {k: v for k, v in record.items() if k not in PAGE_ONLY}
        row["result"] = {"games_in": result["games_in"], "planned": result["planned"], "reading": pending,
                         "folders": {f["name"]: f["games"] for f in result["folders"]},
                         "paired": result["report"]}  # fmt: skip
        out.append(row)
    return out
