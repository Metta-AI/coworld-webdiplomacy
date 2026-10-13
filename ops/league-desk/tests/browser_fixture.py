"""Invented, network-denied cache for the optional browser acceptance check."""
import copy
import json
import sys
import time
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
import uvicorn
from helpers import DeskTest
from test_artifacts import replay
from test_competition import CompetitionTests, raw_game
from test_instrumentation import instrumented_results, log_bytes

from league_desk.server import create_app

fixture = DeskTest()
fixture.setUp()
try:
    fixture.now = time.time() - 600
    CompetitionTests.enrich(fixture)
    member = fixture.responses["/v2/league-policy-memberships"][0]
    second = copy.deepcopy(member)
    second.update(id="member_second", player={"id": "Bert", "name": "Bert"})
    second["policy_version"]["id"] = "pv_Bert"
    fixture.responses["/v2/league-policy-memberships"].append(second)
    ratings = fixture.responses["/v2/divisions/div_demo/leaderboards"]["views"][0]["rows"]
    second = copy.deepcopy(ratings[0])
    second.update(subject_id="Bert", subject_name="Bert", policy_version_ids=["pv_Bert"])
    second["values"].update(mu=25, sigma=4, rating=13)
    ratings.append(second)
    games = []
    for i in range(5):
        game = raw_game(fixture.now, f"ereq_00000000-0000-0000-0000-{i + 1:012d}")
        for slot in range(2, 7):
            game['participants'].append({'position':slot,'player_id':None,'player_name':None,
                                         'policy_version_id':'pv_Field','is_filler':True,'is_seed':False})
            game['participant_scores'].append({'position':slot,'score':0})
        games.append(game)
        fixture.responses["/v2/episode-requests/" + game["id"]] = {
            **game, "cost_usd": 1, "experience_request_id": None}
    fixture.responses["/v2/rounds/round_demo/episodes"]["entries"] = games
    @contextmanager
    def stream(method, path):
        kind = path.rsplit('/',1)[-1]
        payload = instrumented_results() if kind == 'results' else replay()
        if kind == 'results':
            payload['scores'] = [.8, .2, 0, 0, 0, 0, 0]
        yield httpx.Response(200, content=log_bytes() if kind == "logs" else json.dumps(payload).encode())
    fixture.api.stream = stream
    fixture.collector.once()
    for _ in range(2):
        fixture.now += 300
        for row in ratings:
            row["values"]["mu"] += 1
            row["values"]["rating"] += 1
            row["values"]["rounds_played"] += 1
        fixture.collector.once()
    fixture.store.success("versions", "all", {"rows": [
        {"id": "cow_demo", "version": "9.9.1", "created_at": fixture.now - 86400},
        {"id": "cow_old", "version": "9.9.0", "created_at": fixture.now - 86400 * 30},
    ]}, fixture.now)
    from league_desk.artifacts import collect_artifacts
    for _ in range(3):
        collect_artifacts(fixture.collector)
    from league_desk.game_metrics import day
    daily_rows = []
    for offset in (2, 1, 0):
        for source, factor in (("tournament", 1), ("xp_request", 3)):
            daily_rows.append({"league_id": "league_demo", "source": source, "day": day(fixture.now-offset*86400),
                               "compute": factor*(3-offset), "llm": factor*2,
                               "week_compute": factor*(3-offset), "week_llm": factor*2})
    fixture.store.success("daily_spend", "league_demo", {"rows": daily_rows}, fixture.now)
    fixture.store.success("costs", "league_demo", {"rows": [
        {"source": source, "compute_cost_usd": factor*6, "llm_estimated_cost_usd": factor*6,
         "combined_estimated_cost_usd": factor*12} for source, factor in (("tournament", 1), ("xp_request", 3))
    ]}, fixture.now)
    provider_rows, attempt_rows = [], []
    for game in games:
        for slot, player in enumerate(("Ada", "Bert")):
            provider_rows.append({"episode": game["id"], "slot": slot, "player_id": player, "player": player,
                "policy_version_id": "pv_"+player, "policy_id": "pol_"+player, "policy": "Invented "+player,
                "version": 1, "coworld_id": "cow_demo", "created_at": fixture.now-100,
                "model": "invented/model-"+player, "calls": 25, "failed": 1, "usd": .1*(slot+1),
                "failure_day": day(fixture.now)})
    attempt_rows = [{"policy_version_id": "pv_"+player, "model": "invented/requested-"+player,
                     "attempts": 30*len(games), "not_ok": 5*len(games), "refused": len(games),
                     "failure_day": day(fixture.now)} for player in ("Ada", "Bert")]
    fixture.store.success("seat_models", "league_demo", {"rows": provider_rows}, fixture.now)
    fixture.store.success("attempts", "league_demo", {"rows": attempt_rows}, fixture.now)
    uvicorn.run(create_app(fixture.store), host="127.0.0.1", port=8661, access_log=False)
finally:
    fixture.doCleanups()
