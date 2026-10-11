"""Replays: the episode browser, the viewer and replay annotations.

Pages:
  /replays                      every fetched episode, one row per followed seat, with filters
                                as query parameters (so a card can link to a filtered list)
  /replays/<episode>?phase=N&seat=S   the viewer; `phase` indexes the last replay frame's
                                `history.phases`, `seat` is the roster slot whose log, private
                                press and press audit are shown

JSON:
  GET    /api/replays/<episode>?seat=S            the viewer's data (`episodes.load_view`)
  GET    /api/replays/<episode>/audit-status      {"stamp": mtime of audit.json or 0}
  GET    /api/replays/<episode>/annotations       the episode's annotations
  POST   /api/replays/<episode>/annotations       {text, tag, phase, power, territory} -> the new one
  DELETE /api/replays/<episode>/annotations/<id>
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from . import episodes, store
from .routes_chat import require_same_origin
from .server import render

router = APIRouter()
NAV = ("Replays", "/replays")

PAGE_SIZE = 200
POWERS = ("England", "France", "Italy", "Germany", "Austria", "Turkey", "Russia")
YES_NO = ("", "yes", "no")


def _episode_rows(policy: str) -> tuple[list[dict], bool]:
    """One table row per followed seat (per episode when it has none). Returns (rows, any guess)."""
    out = []
    guessed_any = False
    for episode in episodes.index():
        seats, guessed = episodes.followed_seats(episode, policy or None)
        guessed_any |= guessed and bool(seats)
        if policy and not seats:
            continue
        for seat in seats or [None]:
            opponents = sorted({s["policy"] for s in episode["seats"] if seat is None or s["slot"] != seat["slot"]})
            flags = episodes.flags(episode, seat) if seat else []
            taint = sorted(set(episode["taint"]) | set(seat["taint"] if seat else []))
            winner = next((s for s in episode["seats"] if s["solo"]), None)
            out.append({
                "episode": episode,
                "seat": seat,
                "guessed": guessed,
                "delta": seat["score"] - episodes.PARITY if seat else None,
                "opponents": opponents,
                "opponent_names": sorted({episodes.policy_name(p) for p in opponents}),
                "flags": flags,
                "flags_known": episode["indexed"],
                "taint": taint,
                "winner": winner,
            })  # fmt: skip
    return out, guessed_any


def _keep(row: dict, f: dict) -> bool:
    episode, seat = row["episode"], row["seat"]

    def yes_no(value: str, actual: bool) -> bool:
        return not value or (value == "yes") == actual

    return (
        (not f["source"] or episode["source"] == f["source"])
        and (not f["variant"] or episode["variant"] == f["variant"])
        and (not f["batch"] or episode["batch"] == f["batch"])
        and (not f["power"] or (seat is not None and seat["power"] == f["power"]))
        and (not f["opponent"] or any(episodes.matches_policy(p, f["opponent"]) for p in row["opponents"]))
        and (not f["outcome"] or episode["outcome"] == f["outcome"])
        and yes_no(f["tainted"], bool(row["taint"]))
        and yes_no(f["audit"], episode["audit"])
        and yes_no(f["annotated"], episode["annotations"] > 0)
        and yes_no(f["flagged"], bool(row["flags"]))
    )


@router.get("/replays")
def replays_page(
    request: Request,
    policy: str = "",
    source: str = "",
    variant: str = "",
    batch: str = "",
    power: str = "",
    opponent: str = "",
    outcome: str = "",
    tainted: str = "",
    audit: str = "",
    annotated: str = "",
    flagged: str = "",
    page: int = 1,
):
    filters = {
        "policy": policy, "source": source, "variant": variant, "batch": batch, "power": power,
        "opponent": opponent, "outcome": outcome, "tainted": tainted, "audit": audit, "annotated": annotated,
        "flagged": flagged,
    }  # fmt: skip
    done, total = episodes.deepen()
    every, guessed = _episode_rows(policy)
    rows = [row for row in every if _keep(row, filters)]

    all_episodes = [row["episode"] for row in every]
    names = sorted({s["policy"] for e in episodes.index() for s in e["seats"]})
    options = {
        "policy": sorted({episodes.policy_name(n) for n in names}) + names,
        "source": sorted({e["source"] for e in all_episodes}),
        "variant": sorted({e["variant"] for e in all_episodes}),
        "batch": sorted({e["batch"] for e in all_episodes if e["batch"]}),
        "power": POWERS,
        "opponent": sorted({episodes.policy_name(n) for n in names}) + names,
        "outcome": sorted({e["outcome"] for e in all_episodes if e["outcome"]}),
    }
    scored = [row for row in rows if row["seat"] and not row["taint"]]
    mean = sum(row["seat"]["score"] for row in scored) / len(scored) if scored else None
    pages = max(1, -(-len(rows) // PAGE_SIZE))
    page = min(max(page, 1), pages)
    return render(
        request,
        "replays.html",
        rows=rows[(page - 1) * PAGE_SIZE : page * PAGE_SIZE],
        shown=len(rows),
        seats_total=len(every),
        episodes_total=total,
        indexed=done,
        filters=filters,
        options=options,
        guessed=guessed and not policy,
        mean=mean,
        mean_n=len(scored),
        parity=episodes.PARITY,
        page=page,
        pages=pages,
        yes_no=YES_NO,
    )


def _episode_or_404(episode: str) -> dict:
    row = episodes.find(episode)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no episode {episode!r} under the lab's .runtime/artifacts")
    return row


def _seat(row: dict, seat: int | None) -> int | None:
    if seat is not None and any(s["slot"] == seat for s in row["seats"]):
        return seat
    return episodes.default_seat(row)


@router.get("/replays/{episode}")
def replay_page(request: Request, episode: str, phase: int | None = None, seat: int | None = None):
    row = episodes.find(episode)
    if row is None:
        return render(request, "replays_missing.html", episode=episode)
    return render(
        request,
        "replays_view.html",
        episode=row,
        seat=_seat(row, seat),
        phase=phase,
        tags=store.ANNOTATION_TAGS,
        parity=episodes.PARITY,
    )


@router.get("/api/replays/{episode}")
def replay_data(episode: str, seat: int | None = None):
    row = _episode_or_404(episode)
    view = episodes.load_view(row, _seat(row, seat))
    return {**view, "annotations": store.annotations(episode), "audit_stamp": episodes.audit_stamp(episode)}


@router.get("/api/replays/{episode}/audit-status")
def audit_status(episode: str):
    return {"stamp": episodes.audit_stamp(episode)}


@router.get("/api/replays/{episode}/annotations")
def list_annotations(episode: str):
    _episode_or_404(episode)
    return store.annotations(episode)


@router.post("/api/replays/{episode}/annotations", dependencies=[Depends(require_same_origin)])
def add_annotation(episode: str, body: dict = Body(...)):
    _episode_or_404(episode)
    text = str(body.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail="an annotation needs text")
    phase = body.get("phase")
    try:
        return store.add_annotation(
            episode,
            author="user",
            text=text,
            tag=body.get("tag") or "note",
            phase=int(phase) if phase is not None else None,
            power=body.get("power") or None,
            territory=body.get("territory") or None,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.delete("/api/replays/{episode}/annotations/{annotation_id}", dependencies=[Depends(require_same_origin)])
def delete_annotation(episode: str, annotation_id: str):
    if not store.delete_annotation(episode, annotation_id):
        raise HTTPException(status_code=404, detail="no such annotation")
    return {"deleted": annotation_id}
