"""Replays: the episode browser, the viewer and replay annotations.

Pages:
  /replays                      every fetched episode, one row per followed seat, with filters
                                as query parameters (so a card can link to a filtered list);
                                `sort=score` puts the lowest scores first, `sort=-score` the highest.
                                Without `policy` the list follows the policy last chosen here or on
                                the dashboard (a cookie), else the policy the lab names as ours
                                (`routes_dashboard.lab_policy`); `policy=` (empty), or a lab that
                                names none, follows every seat with a log
  /replays/<episode>?phase=N&seat=S   the viewer; `phase` indexes the last replay frame's
                                `history.phases`, `seat` is the roster slot whose log, private
                                press and press audit are shown. `turn=T` in place of `phase`
                                opens at the movement phase of turn T (0 is Spring 1901): for a
                                link made without reading the replay, as the home page's are

JSON:
  GET    /api/replays/<episode>?seat=S            the viewer's data (`episodes.load_view`)
  GET    /api/replays/<episode>/audit-status      {"stamp": mtime of audit.json or 0}
  GET    /api/replays/<episode>/annotations       the episode's annotations
  POST   /api/replays/<episode>/annotations       {text, tag, phase, power, territory} -> the new one
  DELETE /api/replays/<episode>/annotations/<id>
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from . import episodes, routes_dashboard, store
from .routes_chat import require_same_origin
from .server import render

router = APIRouter()
NAV = ("Replays", "/replays")

PAGE_SIZE = 200
SOURCE_WORDS = {"xp": "experience request", "league": "league match", "local": "local run"}
SORTS = ("", "score", "-score")
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
            # An audit is one seat's view of the game: this row has it, or another seat does.
            audited = episode["audit"] and (seat is None or episode["audit_slot"] in (None, seat["slot"]))
            other = None if audited else next((s for s in episode["seats"] if s["slot"] == episode["audit_slot"]), None)
            out.append({
                "episode": episode,
                "seat": seat,
                "audited": audited,
                "audit_of": other["power"] if other else None,
                "guessed": guessed,
                "delta": seat["score"] - episodes.PARITY if seat else None,
                "opponents": opponents,
                "opponent_names": sorted({episodes.policy_name(p) for p in opponents}),
                # Another of our seats at the table (a paired run, or an older version of ours).
                "ours": episodes.policy_name(policy) if policy else "",
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
        and (not f["variant"] or f["variant"] in (episode["variant_id"], episode["variant"]))
        and (not f["batch"] or episode["batch"] == f["batch"])
        and (not f["power"] or (seat is not None and seat["power"] == f["power"]))
        and (not f["opponent"] or any(episodes.matches_policy(p, f["opponent"]) for p in row["opponents"]))
        and (not f["outcome"] or episode["outcome"] == f["outcome"])
        and yes_no(f["tainted"], bool(row["taint"]))
        and yes_no(f["audit"], row["audited"])
        and yes_no(f["annotated"], episode["annotations"] > 0)
        and yes_no(f["flagged"], bool(row["flags"]))
    )


@router.get("/replays")
def replays_page(
    request: Request,
    policy: str | None = None,
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
    sort: str = "",
    page: int = 1,
):
    names = sorted({s["policy"] for e in episodes.index() for s in e["seats"]})
    known = {episodes.policy_name(n) for n in names}
    # The policy we follow is the dashboard's: the same cookie, and the same rule against `ide/ide follow`.
    picked = routes_dashboard.remembered_policy(request)
    remembered = policy is None and picked in known
    if policy is None:
        policy = picked if remembered else routes_dashboard.lab_policy(known)
        remembered = bool(policy)  # a default, like the cookie: not a filter the user set on this page
    sort = sort if sort in SORTS else ""
    filters = {
        "policy": policy, "source": source, "variant": variant, "batch": batch, "power": power,
        "opponent": opponent, "outcome": outcome, "tainted": tainted, "audit": audit, "annotated": annotated,
        "flagged": flagged,
    }  # fmt: skip
    done, total = episodes.deepen()
    every, guessed = _episode_rows(policy)
    rows = [row for row in every if _keep(row, filters)]

    if sort:  # seats first, by score; a row with no followed seat has no score and goes last
        sign = -1 if sort == "-score" else 1
        rows.sort(key=lambda row: (row["seat"] is None, sign * (row["seat"] or {}).get("score", 0.0)))

    all_episodes = [row["episode"] for row in every]
    options = {
        "policy": sorted(known) + names,
        "source": sorted({e["source"] for e in all_episodes}),
        "variant": sorted({e["variant_id"] for e in all_episodes}),  # ids, as on the dashboard
        "batch": sorted({e["batch"] for e in all_episodes if e["batch"]}),
        "power": POWERS,
        "opponent": sorted(known) + names,
        "outcome": sorted({e["outcome"] for e in all_episodes if e["outcome"]}),
    }
    scored = [row for row in rows if row["seat"] and not row["taint"]]
    mean = sum(row["seat"]["score"] for row in scored) / len(scored) if scored else None
    pages = max(1, -(-len(rows) // PAGE_SIZE))
    page = min(max(page, 1), pages)
    response = render(
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
        sort=sort,
        remembered=remembered,
        source_words=SOURCE_WORDS,
    )
    if policy and not remembered and episodes.policy_name(policy) in known:
        routes_dashboard.remember_policy(response, episodes.policy_name(policy))
    return response


def _episode_or_404(episode: str) -> dict:
    row = episodes.find(episode)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no episode {episode!r} under the lab's .runtime/artifacts")
    return row


def _seat(row: dict, seat: int | None, remembered: str = "") -> int | None:
    """The seat to follow: the one the link names; else the audited seat (`default_seat`); else, in a
    game with no audit, a logged seat of the policy we follow (`remembered`)."""
    if seat is not None and any(s["slot"] == seat for s in row["seats"]):
        return seat
    if remembered and not episodes.audit_path(row["id"]).exists():
        ours = [s for s in row["seats"] if s["has_log"] and episodes.policy_name(s["policy"]) == remembered]
        if ours:
            return ours[0]["slot"]
    return episodes.default_seat(row)


def _our_policy(request: Request, row: dict) -> str:
    """The policy we follow: the browser's pick, else the one the lab can name (recorded, or uploaded last)."""
    return routes_dashboard.remembered_policy(request) or routes_dashboard.lab_policy(
        {episodes.policy_name(s["policy"]) for s in row["seats"]}
    )


def _mark_ours(seats: list[dict], ours: str, followed: int | None) -> list[dict]:
    """Each seat with `ours`: true for every seat of the policy we follow (any version of a bare
    name), so a game with two of our seats marks both. A lab that names no policy has only the
    followed seat to go on, so its policy is ours."""
    if not ours:
        ours = next((episodes.policy_name(s["policy"]) for s in seats if s["slot"] == followed), "")
    return [{**s, "ours": bool(ours) and episodes.matches_policy(s["policy"], ours)} for s in seats]


@router.get("/replays/{episode}")
def replay_page(
    request: Request, episode: str, phase: int | None = None, seat: int | None = None, turn: int | None = None
):
    row = episodes.find(episode)
    if row is None:  # a card or a note may link to a game that was never fetched or was removed
        response = render(request, "replays_missing.html", episode=episode)
        response.status_code = 404
        return response
    ours = _our_policy(request, row)
    followed = _seat(row, seat, ours)
    return render(
        request,
        "replays_view.html",
        episode={**row, "seats": _mark_ours(row["seats"], ours, followed)},
        seat=followed,
        phase=phase,
        turn=turn,
        source_words=SOURCE_WORDS,
        tags=store.ANNOTATION_TAGS,
        parity=episodes.PARITY,
    )


@router.get("/api/replays/{episode}")
def replay_data(request: Request, episode: str, seat: int | None = None):
    row = _episode_or_404(episode)
    view = episodes.load_view(row, _seat(row, seat))
    seats = _mark_ours(view["seats"], _our_policy(request, row), view["seat"])
    return {**view, "seats": seats, "annotations": store.annotations(episode),
            "audit_stamp": episodes.audit_stamp(episode)}  # fmt: skip


@router.get("/api/replays/{episode}/audit-status")
def audit_status(episode: str):
    if episode.startswith("."):  # an episode id is a directory name, never a way out of the press folder
        raise HTTPException(status_code=404, detail="no such episode")
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
