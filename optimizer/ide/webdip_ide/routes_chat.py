"""The agent panel's JSON API, and the home page.

  GET  /api/chat?after=N     chat messages with seq > N, and the agent's delivery cursor
  POST /api/chat             {text, context?}: a user message for the agent
  GET  /api/cards?after=N    agent cards with seq > N
  GET  /api/agent/status     is an agent attached, is it listening, what is still undelivered
  GET  /                     home: what this is, agent status, newest cards, counts

The browser polls these every two seconds. Nothing here talks to the agent directly: a
posted message is appended to the store, and the agent side (listener, hooks, MCP; see
`hooks.py`) picks it up from there.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from . import hooks, paths, store
from .server import render

NAV = None  # the panel is on every page; home is the brand link

MAX_MESSAGE_CHARS = 20_000
LOCAL_HOSTS = ("127.0.0.1", "localhost", "[::1]")


def require_same_origin(request: Request) -> None:
    """Refuse writes that do not come from the IDE's own pages.

    Any web page the user has open can send a request to a localhost port. A browser
    always sends `Origin` on a cross-site POST, so requiring it to match `Host`, and
    `Host` to be a loopback name (which stops DNS rebinding), keeps other sites out
    without a token. Requests with no `Origin` (curl, the tests) are local programs.
    Use as `dependencies=[Depends(require_same_origin)]` on any write route.
    """
    host = request.headers.get("host", "")
    if host.rsplit(":", 1)[0] not in LOCAL_HOSTS:
        raise HTTPException(403, "the IDE only answers on localhost")
    origin = request.headers.get("origin")
    if origin and urlsplit(origin).netloc != host:
        raise HTTPException(403, "cross-site request refused")


router = APIRouter()


class ChatPost(BaseModel):
    text: str
    context: dict | None = None


@router.get("/api/chat")
def get_chat(after: int = 0):
    return {"messages": store.messages(after=after), "delivered": hooks.delivered_seq()}


@router.post("/api/chat", dependencies=[Depends(require_same_origin)])
def post_chat(post: ChatPost):
    text = post.text.strip()
    if not text:
        raise HTTPException(400, "empty message")
    if len(text) > MAX_MESSAGE_CHARS:
        raise HTTPException(400, f"message longer than {MAX_MESSAGE_CHARS} characters")
    return store.post_message("user", text, post.context or None)


@router.get("/api/cards")
def get_cards(after: int = 0):
    return {"cards": store.cards(after=after)}


@router.get("/api/agent/status")
def agent_status():
    return hooks.agent_status()


def _count_episodes() -> int:
    """The same episodes the Replays page lists."""
    from . import episodes  # imported here: it loads the lab's tools

    return len(episodes.episode_dirs())


def _count_reports() -> int:
    root = paths.reports_dir()
    return sum(1 for _ in root.rglob("*.md")) if root.is_dir() else 0


@router.get("/")
def home(request: Request):
    notes = store.all_annotations()
    return render(
        request,
        "home.html",
        episodes=_count_episodes(),
        annotations=sum(len(rows) for rows in notes.values()),
        annotated_episodes=sum(1 for rows in notes.values() if rows),
        reports=_count_reports(),
        cards=len(store.cards()),
        status=hooks.agent_status(),
    )
