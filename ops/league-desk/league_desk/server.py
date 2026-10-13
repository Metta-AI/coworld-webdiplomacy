"""Synchronous, cache-only page. Collection belongs to the CLI's child process."""
import time
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .metrics import desk
from .panels import SECTIONS
from .paths import PACKAGE, runtime_dir
from .store import Store


def create_app(store=None):
    store = store or Store(runtime_dir())
    templates = Jinja2Templates(directory=PACKAGE / "templates")
    app = FastAPI(title="The League Desk", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]"])
    app.mount("/static", StaticFiles(directory=PACKAGE / "static"), name="static")

    @app.get("/")
    def home(request: Request, league: Literal["press", "gunboat"] = "press"):
        return templates.TemplateResponse(request=request, name="desk.html", context={
            "league_key": league, "sections": SECTIONS, **desk(store.snapshot(), league, time.time()),
        }, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                    "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'; form-action 'self'"})

    return app
