"""Reports: the write-ups the agent's skills leave in the lab.

Two kinds, each a folder of Markdown files under `paths.reports_dir()`:

  opponents/<slug>.md   how one opponent policy plays (the opponent-profile skill)
  matchups/<slug>.md    why our policy wins or loses against an opponent or the field
                        (the matchup-writeup skill)

Each file starts with front matter (`title`, `date`, `policy`, `opponent`, `games`,
`variant`, `sources`); a missing field is shown as "-" and never guessed. A profile
belongs to the policy its `opponent` field names (a gunboat profile is a second file,
`<slug>-gunboat.md`), or failing that to the policy whose slug is the file name. The files are the
record: this module only lists and renders them, and never writes one.

Pages:
  /reports                      both kinds, newest first, and the policies in the fetched
                                episodes that have no profile yet (`?kind=opponents|matchups`
                                shows one kind)
  /reports/<kind>/<slug>        one report, rendered (`reports_markdown.py`)

JSON:
  GET /api/reports              [{kind, slug, title, date, policy, opponent, games, variant, sources, path}]
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request

from . import episodes, paths, reports_markdown, routes_dashboard, store
from .server import render

router = APIRouter()
NAV = ("Reports", "/reports")

PACIFIC = ZoneInfo("America/Los_Angeles")
KINDS = {
    "opponents": {
        "label": "Opponent profiles",
        "one": "opponent profile",
        "skill": "opponent-profile",
        "about": "How one opponent plays: openings, first targets, where it grows, how it treats us.",
    },
    "matchups": {
        "label": "Matchup write-ups",
        "one": "matchup write-up",
        "skill": "matchup-writeup",
        "about": "Why our policy wins or loses against each opponent, with the games that show it.",
    },
}
SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _family(policy: str) -> str:
    """'name:v3' -> 'name'."""
    return re.sub(r":v[^:]*$", "", policy)


def _slug(name: str) -> str:
    """The file name the opponent-profile skill uses for a policy (`opponent_profile.slug`)."""
    return re.sub(r"[^a-z0-9]+", "-", _family(name).lower()).strip("-")


def _versions(text: str) -> set[str]:
    """Version labels named in a front-matter value: 'bot:v2, bot:v3' -> {'v2', 'v3'}."""
    return set(re.findall(r":(v[\w.]+)", text or ""))


def read_report(kind: str, path: Path) -> dict:
    """One report's front matter, with fallbacks that are facts about the file (never guesses)."""
    meta, body = reports_markdown.split_front_matter(path.read_text(errors="replace"))
    modified = datetime.fromtimestamp(path.stat().st_mtime, PACIFIC)
    return {
        "kind": kind,
        "slug": path.stem,
        "title": meta.get("title") or reports_markdown.first_heading(body) or path.stem,
        "date": meta.get("date") or "",
        "modified": modified.strftime("%Y-%m-%d %H:%M"),
        "policy": meta.get("policy") or "",
        "opponent": meta.get("opponent") or "",
        "games": meta.get("games") or "",
        "variant": meta.get("variant") or "",
        "sources": meta.get("sources") or "",
        "path": str(path.relative_to(paths.lab_dir())),
        "link": f"/reports/{kind}/{path.stem}",
        "body": body,
    }


def list_reports() -> dict[str, list[dict]]:
    """kind -> its reports, newest first (by front-matter date, then by file time)."""
    out = {}
    for kind in KINDS:
        folder = paths.reports_dir() / kind
        rows = [read_report(kind, p) for p in sorted(folder.glob("*.md"))] if folder.is_dir() else []
        out[kind] = sorted(rows, key=lambda r: (r["date"], r["modified"]), reverse=True)
    return out


def policies_in_data() -> list[dict]:
    """Every policy in the fetched episodes: {name, slug, versions, games, latest}."""
    found: dict[str, dict] = {}
    for row in episodes.index():
        for name in {_family(seat["policy"]) for seat in row["seats"]}:
            entry = found.setdefault(name, {"name": name, "slug": _slug(name), "versions": set(), "games": 0,
                                            "latest": ""})
            entry["versions"].update(seat["policy"] for seat in row["seats"] if _family(seat["policy"]) == name)
            entry["games"] += 1
            entry["latest"] = max(entry["latest"], row.get("date") or "")
    rows = [{**entry, "versions": sorted(entry["versions"])} for entry in found.values()]
    return sorted(rows, key=lambda r: (-r["games"], r["name"]))


def _profiled(report: dict) -> set[str]:
    """The policy names a profile is about: from its `opponent` field, else from its file name."""
    names = {_family(part.strip()) for part in report["opponent"].split(",") if part.strip()}
    return names or {report["slug"]}


def our_policies() -> set[str]:
    """The policies this lab can name as ours: the one the agent recorded (`ide/ide follow`) and
    every name with a row in a version log."""
    return {name for name in (store.followed_policy(), *routes_dashboard.shipped_policies()) if name}


def unreadable_episodes() -> int:
    """Episodes on disk whose seats could not be read: their policies are missing from the list."""
    return sum(not row["seats"] for row in episodes.index())


def profile_gaps(profiles: list[dict], policies: list[dict]) -> tuple[list[dict], dict[str, list[str]]]:
    """(policies with no profile, report slug -> versions in the data that the profile does not name)."""
    missing, stale = [], {}
    for policy in policies:
        mine = [r for r in profiles if policy["name"] in _profiled(r) or r["slug"] == policy["slug"]]
        if not mine:
            missing.append(policy)
        for report in mine:
            named = _versions(report["opponent"])
            unseen = [v for v in policy["versions"] if v.rsplit(":", 1)[-1] not in named]
            if named and unseen:
                stale[report["slug"]] = unseen
    return missing, stale


@router.get("/reports")
def reports_page(request: Request, kind: str | None = None):
    if kind is not None and kind not in KINDS:
        raise HTTPException(404, f"no report kind {kind!r}")
    reports = list_reports()
    missing, stale = profile_gaps(reports["opponents"], policies_in_data())
    ours = our_policies()
    return render(
        request,
        "reports.html",
        kinds={k: v for k, v in KINDS.items() if kind in (None, k)},
        reports=reports,
        # An opponent profile is of somebody else: our own policies are not asked for one.
        missing=[p for p in missing if p["name"] not in ours] if kind in (None, "opponents") else [],
        ours=sorted(p["name"] for p in missing if p["name"] in ours),
        stale=stale,
        unreadable=unreadable_episodes(),
        only=kind,
        reports_path=str(paths.reports_dir()),
    )


@router.get("/reports/{kind}/{slug}")
def report_page(request: Request, kind: str, slug: str):
    if kind not in KINDS or not SLUG.match(slug):
        raise HTTPException(404, "no such report")
    path = paths.reports_dir() / kind / f"{slug}.md"
    if not path.is_file():  # a card or a note may link to a report that was renamed or never written
        response = render(request, "reports_missing.html", kind=KINDS[kind], kind_key=kind, slug=slug)
        response.status_code = 404
        return response
    report = read_report(kind, path)
    stale = []
    if kind == "opponents":
        _, gaps = profile_gaps([report], policies_in_data())
        stale = gaps.get(slug, [])
    return render(
        request,
        "reports_view.html",
        report=report,
        kind=KINDS[kind],
        stale=stale,
        html=reports_markdown.render(report["body"], drop_first_h1=True),
    )


@router.get("/api/reports")
def reports_json():
    return [{k: v for k, v in report.items() if k != "body"} for rows in list_reports().values() for report in rows]
