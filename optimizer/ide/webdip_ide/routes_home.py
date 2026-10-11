"""The home page: where the followed policy stands, and which games to open next.

  GET /    the headline number for the policy the user follows (the `dashboard_policy` cookie,
           else the dashboard's own default), "Games worth opening" (the lowest and highest
           scores among that policy's recent games, with flags and who lied to us), the
           experiments that are running (with how many of their games are in), the user's
           notes not yet sent to the agent, the reports written since the last sitting, and
           the agent's newest idea cards with their two actions.

Nothing here is computed twice. The headline is `routes_dashboard.summary()`: the dashboard's
choice of policy and variant, its cached report and its sentence. The games come from the
replay browser's index (`episodes.index()`), the flags from `episodes.flags()`, the liars from
each game's `audit.json`. The page does not wait for a large read: while the dashboard or the index
is still reading games it says so in one line and reloads itself.
"""

from __future__ import annotations

import json
import threading
import time

from fastapi import APIRouter, Request

from . import episodes, hooks, paths, routes_dashboard, routes_experiments, routes_reports, store
from .server import render

router = APIRouter()
NAV = None  # home is the brand link in the top bar

RECENT = 40  # "recent" is the followed policy's newest games, this many
WORST, BEST = 5, 2
LIES = ("betrayed", "deceived")  # audit categories that mean "we relied on it and it did not hold"
VISIT_COOKIE = "home_visit"  # "<time of the last request>:<time the sitting before this one ended>"
SITTING_GAP = 30 * 60  # seconds away from the home page that start a new sitting

_lock = threading.Lock()
_audits: dict[str, tuple[float, dict]] = {}  # episode id -> (audit.json mtime, {"slot", "powers"}); under `_lock`


def _audit(episode: str) -> dict | None:
    """The part of a game's press audit the worklist needs, read once per version of the file."""
    stamp = episodes.audit_stamp(episode)
    if not stamp:
        return None
    with _lock:
        cached = _audits.get(episode)
    if cached and cached[0] == stamp:
        return cached[1]
    try:
        data = json.loads(episodes.audit_path(episode).read_text())
        kept = {"slot": data.get("slot"), "powers": (data.get("summary") or {}).get("powers") or {}}
    except (ValueError, OSError, AttributeError):
        return None  # half-written or damaged: the viewer says so when the game is opened
    with _lock:
        _audits[episode] = (stamp, kept)
    return kept


def liars(episode: str, slot: int) -> list[dict] | None:
    """Who lied to seat `slot`, most lies first: [{power, count, turn, quote}]. None without an audit of that seat.

    `turn` and `quote` are the first lie's, so a link can open the game where it was said.
    """
    audit = _audit(episode)
    if audit is None or audit["slot"] != slot:
        return None
    out = []
    for power, entry in audit["powers"].items():
        lies = sorted((f for f in entry.get("flagged") or [] if f.get("category") in LIES), key=lambda f: f["turn"])
        if lies:
            out.append({"power": power.title(), "count": len(lies), "turn": lies[0]["turn"],
                        "quote": lies[0].get("quote", "")})  # fmt: skip
    return sorted(out, key=lambda liar: (-liar["count"], liar["power"]))


def turning_point(seat: dict, worst: bool) -> dict | None:
    """The year this seat lost (`worst`) or gained the most centres: {turn, text}, or None.

    `turn` is that year's autumn, the moves that decided the count. Needs the deep index row
    (`centers_by_year`); a game not read yet has none.
    """
    years = sorted((seat.get("centers_by_year") or {}).items())
    changes = [(after - before, -year, before, after) for (_, before), (year, after) in zip(years, years[1:])]
    if not changes:
        return None
    change, minus_year, before, after = min(changes) if worst else max(changes)
    if change == 0 or (change > 0) == worst:
        return None
    return {"turn": (-minus_year - 1901) * 2 + 1, "text": f"{before} to {after} centres in {-minus_year}"}


def _row(episode: dict, seat: dict, worst: bool) -> dict:
    point = turning_point(seat, worst)
    link = f"/replays/{episode['id']}"
    if seat["has_log"]:
        link += f"?seat={seat['slot']}"
    winner = next((s for s in episode["seats"] if s["solo"]), None)
    if winner:
        ended = "we won" if winner["slot"] == seat["slot"] else f"{winner['power']} won"
    else:
        ended = episode["outcome"] or "no result"
    return {
        "episode": episode,
        "seat": seat,
        "delta": seat["score"] - episodes.PARITY,
        "ended": ended,
        "flags": episodes.flags(episode, seat) if episode["indexed"] and not episode["index_error"] else [],
        "flags_known": episode["indexed"] and not episode["index_error"],
        "liars": liars(episode["id"], seat["slot"]) if seat["has_log"] else None,
        "point": point,
        "link": link,
        "opens_at": f"{link}{'&' if '?' in link else '?'}turn={point['turn']}" if point else link,
    }


def worklist(policy: str, variant: str = "") -> dict:
    """The followed policy's recent games worth opening: the lowest and the highest scores.

    `variant` is the dashboard's variant id for the headline, so the list and the number are
    about the same games; empty means every variant. Without `policy` (nothing chosen and the
    dashboard has read nothing yet) the seats with a log are followed, as the replay browser
    does. Crashed and cut-short games are counted but not ranked: their score measures the
    crash. Equal scores keep the newer game first.
    """
    recent, tainted = [], 0
    for episode in episodes.index():
        if variant and episode["variant_id"] != variant:
            continue
        seats, _ = episodes.followed_seats(episode, policy or None)
        for seat in seats:
            if episode["taint"] or seat["taint"]:
                tainted += 1
            else:
                recent.append((episode, seat))
        if len(recent) + tainted >= RECENT:
            break
    by_score = sorted(recent, key=lambda pair: pair[1]["score"])
    worst = by_score[:WORST]
    best = by_score[WORST:][-BEST:][::-1]
    return {
        "worst": [_row(episode, seat, True) for episode, seat in worst],
        "best": [_row(episode, seat, False) for episode, seat in best],
        "considered": len(recent),
        "tainted": tainted,
    }


def unsent_notes() -> dict:
    """The user's notes that no message to the agent has carried: {count, games: [(episode id, count)]}."""
    sent = set()
    for message in store.messages():
        if message["sender"] == "user":
            sent.update((message.get("context") or {}).get("annotations") or [])
    games = []
    for episode, rows in store.all_annotations().items():
        waiting = sum(1 for row in rows if row["author"] == "user" and row["id"] not in sent)
        if waiting:
            games.append((episode, waiting))
    return {"count": sum(n for _, n in games), "games": games}


def _sitting(cookie: str, now: float) -> tuple[float | None, str]:
    """(when the sitting before this one ended, the cookie to set). None on a first visit."""
    last, since = None, None
    try:
        first, _, second = cookie.partition(":")
        last, since = float(first), (float(second) if second else None)
    except ValueError:
        pass
    if last is not None and now - last > SITTING_GAP:
        since = last
    return since, f"{now:.0f}:{'' if since is None else format(since, '.0f')}"


def reports(since: float | None) -> dict:
    """{total, new: reports whose file changed after `since`, newest first}."""
    rows = [r for kind in routes_reports.list_reports().values() for r in kind]
    new = []
    for row in rows:
        try:
            changed = (paths.lab_dir() / row["path"]).stat().st_mtime
        except OSError:  # removed or renamed by the agent since the list was made
            continue
        if since is not None and changed > since:
            new.append({"title": row["title"], "link": row["link"], "time": changed})
    return {"total": len(rows), "new": sorted(new, key=lambda r: r["time"], reverse=True)}


@router.get("/")
def home(request: Request):
    remembered = routes_dashboard.remembered_policy(request)
    # The index first: on a first visit it reads two small files per game, and that is quicker
    # before the two calls below have started the readers' threads.
    known = {episodes.policy_name(s["policy"]) for e in episodes.index() for s in e["seats"]}
    summary = routes_dashboard.summary(remembered)
    indexed, total = episodes.deepen()
    policy = summary["policy"] or (remembered if remembered in known else "")
    # Nothing names this policy as ours: no choice in the browser, none recorded by the agent, no upload.
    guessed = bool(policy) and remembered not in known and not routes_dashboard.lab_policy(known)
    variant = summary["variant"] if summary["headline"] and summary["variant"] != "all" else ""
    since, cookie = _sitting(request.cookies.get(VISIT_COOKIE, ""), time.time())
    response = render(
        request,
        "home.html",
        summary=summary,
        policy=policy,
        policy_guessed=guessed,
        work=worklist(policy, variant),
        variant=variant,
        recent=RECENT,
        indexed=indexed,
        games=total,
        notes=unsent_notes(),
        reports=reports(since),
        experiments=routes_experiments.running(),
        since=since,
        parity=episodes.PARITY,
        status=hooks.agent_status(),
    )
    response.set_cookie(VISIT_COOKIE, cookie, max_age=365 * 24 * 3600, samesite="lax")
    return response
