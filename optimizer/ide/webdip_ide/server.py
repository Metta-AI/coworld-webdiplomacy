"""The IDE's web server: `ide serve`.

One FastAPI app, server-rendered pages plus small scripts, no build step. Each feature
is one module that exports `router` (and `NAV`, its entry in the top navigation):

  routes_chat       the agent panel on every page: chat and agent cards (JSON API)
  routes_home       the home page: the followed policy's headline and the games worth opening
  routes_replays    replay browser, viewer, annotations, press-audit overlay
  routes_dashboard  statistics by power, opponent, version and source
  routes_experiments  the lab's experiment records, each with its paired result so far
  routes_reports    write-ups from the matchup and opponent-profile skills

Handlers are plain `def` (FastAPI runs them in a thread pool); the browser polls for
new chat, so nothing here is async.
"""

from __future__ import annotations

import importlib
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import dates, paths

PACKAGE_DIR = Path(__file__).resolve().parent
FEATURES = ("routes_chat", "routes_home", "routes_replays", "routes_dashboard", "routes_experiments", "routes_reports")

templates = Jinja2Templates(directory=PACKAGE_DIR / "templates")
# Every date on every page goes through these two: `{{ row.time | when }}`, `{{ report.date | day }}`.
templates.env.filters["when"] = dates.when
templates.env.filters["day"] = dates.day


def render(request: Request, template: str, **context):
    """Render a page inside the shared layout (navigation and the agent panel)."""
    return templates.TemplateResponse(request, template, {"nav": NAV, "lab": paths.lab_dir(), **context})


NAV: list[tuple[str, str]] = []

# "testserver" is the name Starlette's test client sends; no browser reaches the IDE under it.
LOCAL_HOSTS = ("127.0.0.1", "localhost", "[::1]", "testserver")


def require_local_host(request: Request) -> None:
    """Answer only when the browser asked for a loopback name.

    The server binds to 127.0.0.1, but another web site can point its own host name at
    127.0.0.1 (DNS rebinding) and then read the IDE's pages, private press included, as
    if they were its own. Such a request still carries the other site's name in `Host`,
    so every route refuses any name that is not loopback.
    """
    if request.headers.get("host", "").rsplit(":", 1)[0] not in LOCAL_HOSTS:
        raise HTTPException(403, "the IDE only answers on localhost")


class FreshStaticFiles(StaticFiles):
    """Static files the browser checks before reusing.

    Without a `Cache-Control` header a browser may keep a stylesheet or script for hours on a
    guess. After the IDE is updated that shows new pages with old styles: the agent panel's
    hidden context chip was seen as an empty box this way. `no-cache` still lets the browser
    keep its copy; it asks first, and an unchanged file costs one short 304 answer.
    """

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


def create_app() -> FastAPI:
    app = FastAPI(title="webDiplomacy optimizer IDE", dependencies=[Depends(require_local_host)])
    app.mount("/static", FreshStaticFiles(directory=PACKAGE_DIR / "static"), name="static")
    NAV.clear()
    for name in FEATURES:
        module = importlib.import_module(f"{__package__}.{name}")
        app.include_router(module.router)
        if getattr(module, "NAV", None):
            NAV.append(module.NAV)
    return app
