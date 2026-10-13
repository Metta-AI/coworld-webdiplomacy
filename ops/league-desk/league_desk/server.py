"""Synchronous, cache-only page. Collection belongs to the CLI's child process."""
import time
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .alerts import prepare_alerts
from .board_metrics import board_panels
from .dates import when
from .freshness import age_label
from .metrics import desk, money
from .panels import SECTIONS, competition_panels
from .paths import PACKAGE, runtime_dir
from .selection import RANGES, version_choices
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

    @app.post("/refresh")
    def refresh(request: Request):
        if request.headers.get("origin") != str(request.base_url).rstrip("/"):
            raise HTTPException(403, "Same-origin refresh required")
        if not store.path.exists():
            raise HTTPException(503, "Start serve to initialize the cache")
        store.request_refresh()
        return JSONResponse({"status": "queued", "message": "Collector requested; slow polls retain their deadlines."},
                            status_code=202, headers={"Cache-Control": "no-store"})

    @app.post("/alerts/{fingerprint}")
    def change_alert(request: Request, fingerprint: str, dismissed: bool = Query(...)):
        if request.headers.get("origin") != str(request.base_url).rstrip("/"):
            raise HTTPException(403, "Same-origin alert change required")
        if len(fingerprint) != 64 or any(c not in "0123456789abcdef" for c in fingerprint):
            raise HTTPException(422, "Invalid alert fingerprint")
        if not store.path.exists():
            raise HTTPException(503, "Start serve to initialize the cache")
        store.set_dismissed(fingerprint, dismissed, time.time())
        return JSONResponse({"dismissed": dismissed}, headers={"Cache-Control": "no-store"})

    @app.get("/")
    @app.get("/fragments")
    def home(request: Request, league: Literal["press", "gunboat"] = "press",
             range_key: Literal["24h", "7d", "30d", "all"] = Query("7d", alias="range"),
             version: str = Query("all", max_length=100), player: str = Query("", max_length=100)):
        now = time.time()
        snapshot = store.snapshot(include_history=True)
        versions = version_choices(snapshot)
        if version != "all" and version not in versions:
            raise HTTPException(422, "Unknown cached version")
        duration, range_label = RANGES[range_key]
        start = now - duration if duration else 0
        context = desk(snapshot, league, now)
        competition = competition_panels(snapshot, context["league"], now, start, version)
        spending = spending_panels(snapshot, context["league"], now, competition, start, version)
        competition["panel_data"].update(spending["spend_panels"])
        competition["panel_data"].update(board_panels(snapshot, context["league"], competition, now, start, version))
        standings = competition["panel_data"]["Competing players"]
        for entry_player, row in zip(standings["player_ids"], standings["rows"], strict=True):
            row[-2] = spending["player_models"].get(entry_player, "not collected")
            values = spending["player_costs"].get(entry_player)
            if values:
                row[-1] = f"{money(sum(values) / len(values))} ({len(values)} covered games)"
        standings["note"] += (" LLM/game is provider billed spend across covered completed games with every owned "
                              "seat covered; models join stable player/policy IDs in the selected creation cohort.")
        seat_panel = spending["spend_panels"]["LLM spend per seat per game"]
        standings["stale"] |= seat_panel["stale"]
        standings["sources"] += seat_panel["sources"]
        standings["age"] = max((v for v in (standings["age"], seat_panel["age"]) if v is not None), default=None)
        standings["missing"] += seat_panel["missing"]
        interval_data = standings["chart"]["data"]
        domain = [min((r["low"] for r in interval_data), default=0),
                  max((r["high"] for r in interval_data), default=1)]
        standings["cells"] = []
        for division, player_id in standings["entry_keys"]:
            points = [p for p in standings["sparks"] if (p["division_id"], p["player_id"]) == (division, player_id)]
            interval = [r for r in interval_data if (r["division_id"], r["player_id"]) == (division, player_id)]
            standings["cells"].append({"interval": {"kind": "interval-cell", "data": interval, "domain": domain},
                                       "spark": {"kind": "spark", "data": points}})
        rating_chart = competition["panel_data"]["MMR over time"]["chart"]
        players = {r["player_id"]: r["player"] for r in rating_chart["data"]}
        rating_chart["selected"] = player if player in players else ""
        standings["chart"] = None
        context["alerts"] = spending["spend_alerts"] + competition["competition_alerts"] + context["alerts"]
        competition["competition_age"] = max((p["age"] for p in competition["panel_data"].values()
                                              if p["age"] is not None), default=None)
        competition["missing_panels"] = sum(bool(p["missing"]) for p in competition["panel_data"].values())
        competition["stale_panels"] = sum(bool(p["stale"]) for p in competition["panel_data"].values())
        if any(p["stale"] for p in spending["spend_panels"].values()):
            context["alerts"].append("Spend or request sources failed or are stale; last good data is retained.")
        stale_sources = {s["name"] for p in competition["panel_data"].values() for s in p["sources"]
                         if s["stale"] or s["age"] is None}
        stale_sources.update(r["source"] for r in context["now_rows"] if r["stale"])
        rating_versions = {g["coworld_id"] for source in competition["episode_sources"].values()
                           for g in (source.get("data") or {}).get("rows", [])}
        rating_state = snapshot.get(("ratings", (context["league"] or {}).get("id", "")), {})
        rating_versions.update(d["canonical_id"] for d in [rating_state.get("data") or {},
                               *(o["data"] for o in rating_state.get("history", []))] if d.get("canonical_id"))
        context["alerts"], context["dismissed_alerts"] = prepare_alerts(
            context["alerts"], (context["league"] or {}).get("id", league), rating_versions,
            stale_sources, store.dismissals())
        ages = [value for value in (context["age"], competition["competition_age"]) if value is not None]
        context["age"] = max(ages) if ages else None
        if competition["episode_sources"]:
            counts = competition["day_games"]
            context["now_rows"][-1]["text"] = (
                f"{counts['completed']} completed, {counts['failed']} failed observed in 24 h.")
            game_row = context["now_rows"][-1]
            game_row["detail"] = competition["game_coverage"] + " Retry attempts unavailable."
            game_row["note"] = "Observed completions; retry count unavailable."
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
        return templates.TemplateResponse(
            request=request, name="fragments.html" if request.url.path == "/fragments" else "desk.html", context={
            "league_key": league, "sections": SECTIONS, **context, **competition, **spending,
            "range_key": range_key, "range_label": range_label, "ranges": RANGES, "version_key": version,
            "versions": versions, "players": players, "player_key": player, "rendered_at": now,
            "generation": max((s.get("fetched_at") or 0 for s in snapshot.values()), default=0),
        }, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                    "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'; form-action 'self'"})

    return app
