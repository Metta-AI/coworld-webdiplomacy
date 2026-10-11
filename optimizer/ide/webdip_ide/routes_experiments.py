"""Experiments: the improvement loop as the lab records it.

The agent writes one record per hypothesis before it runs anything (the optimizer-seed
`experiment` skill): `<lab>/experiments/<id>.md`, with front matter (`id`, `policy`, `baseline`,
`candidate`, `status`, `hypothesis`, `decision_rule`, `evals`) and sections (Context,
Predictions, Design, Result, Verdict). `_template.md` is the template and is not a record.
The files are the record: this module lists and renders them, and never writes one.

Pages:
  /experiments           every record, newest first, each with its paired result so far, and
                         "What is closed": the entries of `closed_levers.md` and `best_practices.md`
  /experiments/<id>      one record: its front matter, the result so far, the version-log rows of
                         its two versions, requests to the agent, and the record's text

JSON:
  GET /api/experiments   [{id, title, status, policy, baseline, candidate, hypothesis,
                           decision_rule, evals, batch, path, link, result}]

The result so far is not computed here. It is the lab's `tools/paired.py` (`paired_report`, the
function behind the command the agent runs) on the games in the record's artifact directory,
`.runtime/artifacts/<id>/`, which is where `tools/run_ab.py` fetches them. The games are the ones
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
PAGE_ONLY = ("body", "modified", "rule_brief", "planned", "date", "hypothesis_html", "decision_rule_html")
ALONE_ARMS = (("-alone-a", "candidate"), ("-alone-b", "baseline"))  # where `run_ab.py --alone` fetches

_ARTIFACTS = re.compile(r"^Artifacts:\s*`\.runtime/artifacts/([\w.\-]+)/?`", re.M)
_PLACEHOLDER = re.compile(r"<[A-Za-z][^<>]*>")  # the template's `<policy name>`, `<metric>`, `<Experiment title>`
_COMMENT = re.compile(r"(^|\s)#.*$")
_BLOCK_SCALAR = (">", "|", ">-", "|-", ">+", "|+")
# The parts of a decision rule that fit on one line: "+0.08 or more with z >= 2 over 28 balanced paired games"
# (or "on 28 balanced paired games").
_THRESHOLD = re.compile(r"([+\-−]\s?\d*\.\d+)\s+or more")
_MIN_Z = re.compile(r"\bz\s*(?:>=|≥)\s*(\d+(?:\.\d+)?)")
_PLANNED = re.compile(r"\b(?:over|on)\s+(\d+)\s+(?:[\w-]+\s+){0,3}games\b")
_KILLED_BY = re.compile(r"\*\*Killed by:\*\*\s*(.+?)(?=\n\*\*|\Z)", re.S)
_CLOSED_ON = re.compile(r"^(.*?)\s{2,}closed\s+(.+)$")


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
    artifacts = _ARTIFACTS.search(body)
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
        "evals": [e for e in meta["evals"] if e] if isinstance(meta.get("evals"), list) else [],
        # The first folder under `.runtime/artifacts`: the replay browser's `batch` filter value.
        "batch": artifacts.group(1) if artifacts else path.stem,
        "path": str(path.relative_to(paths.lab_dir())),
        "link": f"/experiments/{path.stem}",
        "body": body,
    }


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


def games_by_batch() -> tuple[dict[str, list], int]:
    """(the games read so far under each folder of `.runtime/artifacts`, games still to be read).

    Does not wait for a large read: `CACHE` hands out what it has and goes on reading."""
    by_directory, pending, _ = routes_dashboard.CACHE.sync_by_directory(0.0)
    prefix = str(paths.artifacts_dir()) + os.sep
    batches: dict[str, list] = defaultdict(list)
    for directory, game in by_directory.items():
        below = directory[len(prefix) :].split(os.sep) if directory.startswith(prefix) else []
        if len(below) > 1:
            batches[below[0]].append(game)
    return batches, pending


def _finished(games: list) -> list:
    return [game for game in games if game.seats and not game.missing_results]


def _short(candidate: str, baseline: str) -> tuple[str, str]:
    """('v2', 'v1') for two versions of one policy; the full names otherwise."""
    (a_name, _, a_version), (b_name, _, b_version) = candidate.rpartition(":"), baseline.rpartition(":")
    return (a_version, b_version) if a_name and a_name == b_name else (candidate, baseline)


def result_so_far(record: dict, batches: dict[str, list], pending: int) -> dict:
    """What the games on disk say now: how many are in, and `paired.py`'s report (candidate minus
    baseline) when both versions have games. `report` is None until then."""
    games = _finished(batches.get(record["batch"], []))
    if record["planned"]:
        progress = f"{len(games)} of {record['planned']} games in"
    else:
        progress = f"{len(games)} game{'' if len(games) == 1 else 's'} in" if games else "no games in yet"
    out = {"games_in": len(games), "planned": record["planned"], "progress": progress, "pending": pending,
           "report": None, "words": "", "verdict": "", "tone": "", "win": False,
           "alone": [(who, len(_finished(batches.get(record["batch"] + suffix, [])))) for suffix, who in ALONE_ARMS]}
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


def running() -> list[dict]:
    """The records with status `running`, each with how many of its games are in (for the home page)."""
    records = [record for record in list_records() if record["status"] == "running"]
    if not records:
        return []
    batches, pending = games_by_batch()
    return [{**record, "result": result_so_far(record, batches, pending)} for record in records]


# --- what is closed, and the version log -----------------------------------------------


def register(name: str) -> list[dict]:
    """The `## ` sections of one of the lab's registers (`closed_levers.md`, `best_practices.md`):
    [{name, closed, killed_by, entries, html}]. The text before the first section is its preface."""
    path = paths.lab_dir() / name
    if not path.is_file():
        return []
    parts = re.split(r"^## +(.+)$", path.read_text(errors="replace"), flags=re.M)[1:]
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
    if record["status"] == "running" or (record["status"] == "proposed" and result["games_in"]):
        out.append({"label": "Ask the agent for the result", "text": (
            f"What is the result of experiment {name} so far? Read the games in .runtime/artifacts/{record['batch']} "
            f"with tools/paired.py ({record['candidate'] or 'the candidate'} against "
            f"{record['baseline'] or 'the baseline'}), read the number against the record's decision rule, and {card}."
        )})  # fmt: skip
    if record["status"] in OPEN:
        out.append({"label": "Ask the agent to close this record", "text": (
            f"Close the experiment record {name} with the experiment skill: write its Result and Verdict against the "
            "decision rule that was written before the run, set its status, add the lever to closed_levers.md if it "
            f"is refuted, run record.py validate, and {card}."
        )})  # fmt: skip
    if result["win"]:
        out.append({"label": "Ask for the candidate-alone check", "text": (
            f"Experiment {name} shows a paired win for {record['candidate']}. Run the candidate-alone check before "
            f"any promotion: write its pass mark in the record first, then tools/run_ab.py --record {record['id']} "
            f"--alone, and {card}."
        )})  # fmt: skip
    return out


# --- routes ---------------------------------------------------------------------------


def _links(record: dict) -> dict:
    """Where the candidate's numbers and this experiment's games are on the other pages."""
    name, _, version = record["candidate"].rpartition(":")
    family = name or record["policy"]
    return {
        "dashboard": "/dashboard?" + urlencode({"policy": family, "version": version}) if name else "",
        # `policy` as well: without it the browser follows the remembered policy, which may not be in these games.
        "replays": "/replays?" + urlencode({"batch": record["batch"], "policy": family}),
    }


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
        tones=STATUS_TONE,
        levers=register("closed_levers.md"),
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
                         "paired": result["report"]}  # fmt: skip
        out.append(row)
    return out
