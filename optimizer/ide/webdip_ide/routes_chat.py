"""The agent panel's JSON API.

  GET  /api/chat?after=N     chat messages with seq > N, and the agent's delivery cursor
  POST /api/chat             {text, context?}: a user message for the agent
  GET  /api/cards?after=N    agent cards with seq > N, and the status of every experiment record
                             (an idea card links to its record; see `chat.js: ideaActions`)
  GET  /api/agent/status     is an agent attached, is it listening, what is still undelivered

The browser polls these every two seconds. Nothing here talks to the agent directly: a
posted message is appended to the store, and the agent side (listener, hooks, MCP; see
`hooks.py`) picks it up from there.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from . import hooks, routes_experiments, store
from .server import require_local_host

NAV = None  # the panel is on every page

MAX_MESSAGE_CHARS = 20_000


def require_same_origin(request: Request) -> None:
    """Refuse writes that do not come from the IDE's own pages.

    Any web page the user has open can send a request to a localhost port. A browser
    always sends `Origin` on a cross-site POST, so requiring it to match `Host`, and
    `Host` to be a loopback name (`server.require_local_host`, which every route has),
    keeps other sites out without a token. Requests with no `Origin` (curl, the tests)
    are local programs. Use as `dependencies=[Depends(require_same_origin)]` on any
    write route.
    """
    require_local_host(request)
    host = request.headers.get("host", "")
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
    return {"cards": store.cards(after=after), "records": routes_experiments.statuses()}


@router.get("/api/agent/status")
def agent_status():
    return hooks.agent_status()
