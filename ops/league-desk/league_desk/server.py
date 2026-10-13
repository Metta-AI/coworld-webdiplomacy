"""Synchronous, cache-only page. Collection belongs to the CLI's child process."""
import time
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .metrics import desk
from .panels import SECTIONS, competition_panels
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
        now = time.time()
        snapshot = store.snapshot(include_history=True)
        context = desk(snapshot, league, now)
        competition = competition_panels(snapshot, context["league"], now)
        context["alerts"] = competition["competition_alerts"] + context["alerts"]
        ages = [value for value in (context["age"], competition["competition_age"]) if value is not None]
        context["age"] = max(ages) if ages else None
        if competition["episode_sources"]:
            counts = competition["day_games"]
            context["now_rows"][-1]["text"] = (
                f"{counts['completed']} completed, {counts['failed']} failed observed in 24 h.")
            game_row = context["now_rows"][-1]
            game_row["note"] = competition["game_coverage"] + " Retry attempts unavailable."
            game_row["age"] = competition["panel_data"]["Game duration"]["age"]
            game_row["stale"] = competition["panel_data"]["Game duration"]["stale"]
            game_row["error"] = ("Incomplete game coverage"
                                 if competition["panel_data"]["Game duration"]["missing"] else None)
            latest = (snapshot.get(("round", context["league"]["id"]), {}).get("data") or {}).get("rounds", [])
            full_rounds = (snapshot.get(("rounds", context["league"]["id"]), {}).get("data") or {}).get("rows", [])
            current = next((r for r in full_rounds if latest and r["number"] == latest[0]["number"] and
                            r["created_at"] == latest[0]["created_at"]), None)
            source = competition["episode_sources"].get(current["id"]) if current else None
            if source:
                games = source["data"]["rows"]
                running = sum(g["status"] == "running" for g in games)
                context["now_rows"][0]["note"] = f"{running}/{len(games)} listed games running; due time unknown."
        return templates.TemplateResponse(request=request, name="desk.html", context={
            "league_key": league, "sections": SECTIONS, **context, **competition,
        }, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                    "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'; form-action 'self'"})

    return app
