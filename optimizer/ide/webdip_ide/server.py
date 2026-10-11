"""The IDE's web server: `ide serve`.

One FastAPI app, server-rendered pages plus small scripts, no build step. Each feature
is one module that exports `router` (and `NAV`, its entry in the top navigation):

  routes_chat       the agent panel on every page: chat and agent cards (JSON API)
  routes_replays    replay browser, viewer, annotations, press-audit overlay
  routes_dashboard  statistics by power, opponent, version and source
  routes_reports    write-ups from the matchup and opponent-profile skills

Handlers are plain `def` (FastAPI runs them in a thread pool); the browser polls for
new chat, so nothing here is async.
"""

from __future__ import annotations

import importlib
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import paths

PACKAGE_DIR = Path(__file__).resolve().parent
FEATURES = ("routes_chat", "routes_replays", "routes_dashboard", "routes_reports")

templates = Jinja2Templates(directory=PACKAGE_DIR / "templates")


def render(request: Request, template: str, **context):
    """Render a page inside the shared layout (navigation and the agent panel)."""
    return templates.TemplateResponse(request, template, {"nav": NAV, "lab": paths.lab_dir(), **context})


NAV: list[tuple[str, str]] = []


def create_app() -> FastAPI:
    app = FastAPI(title="webDiplomacy optimizer IDE")
    app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")
    NAV.clear()
    for name in FEATURES:
        module = importlib.import_module(f"{__package__}.{name}")
        app.include_router(module.router)
        if getattr(module, "NAV", None):
            NAV.append(module.NAV)
    return app
