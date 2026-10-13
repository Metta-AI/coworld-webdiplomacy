"""Synchronous, cache-only page. Collection belongs to the CLI's child process."""
import time
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .dates import when
from .freshness import age_label
from .metrics import desk, money
from .panels import SECTIONS, competition_panels
from .paths import PACKAGE, runtime_dir
from .spend_metrics import spending_panels
from .store import Store


def create_app(store=None):
    store = store or Store(runtime_dir())
    templates = Jinja2Templates(directory=PACKAGE / "templates")
    templates.env.filters["age_label"] = age_label
    templates.env.filters["when"] = when
    app = FastAPI(title="The League Desk", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]"])
    app.mount("/static", StaticFiles(directory=PACKAGE / "static"), name="static")

    @app.get("/")
    def home(request: Request, league: Literal["press", "gunboat"] = "press"):
        now = time.time()
        snapshot = store.snapshot(include_history=True)
        context = desk(snapshot, league, now)
        competition = competition_panels(snapshot, context["league"], now)
        spending = spending_panels(snapshot, context["league"], now, competition)
        competition["panel_data"].update(spending["spend_panels"])
        standings = competition["panel_data"]["Competing players"]
        for player, row in zip(standings["player_ids"], standings["rows"], strict=True):
            values = spending["player_costs"].get(player)
            if values:
                row[-1] = f"{money(sum(values) / len(values))} ({len(values)} covered games)"
        standings["note"] += (" LLM/game is estimated across games with usage for every owned seat; "
                              "model labels lack a stable identity join.")
        seat_panel = spending["spend_panels"]["LLM spend per seat per game"]
        standings["stale"] |= seat_panel["stale"]
        standings["freshness_detail"] += ". " + seat_panel["freshness_detail"]
        context["alerts"] = spending["spend_alerts"] + competition["competition_alerts"] + context["alerts"]
        competition["competition_age"] = max((p["age"] for p in competition["panel_data"].values()
                                              if p["age"] is not None), default=None)
        competition["missing_panels"] = sum(bool(p["missing"]) for p in competition["panel_data"].values())
        competition["stale_panels"] = sum(bool(p["stale"]) for p in competition["panel_data"].values())
        if any(p["stale"] for p in spending["spend_panels"].values()):
            context["alerts"].append("Spend or request sources failed or are stale; last good data is retained.")
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
            "league_key": league, "sections": SECTIONS, **context, **competition, **spending,
        }, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                    "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'; form-action 'self'"})

    return app
