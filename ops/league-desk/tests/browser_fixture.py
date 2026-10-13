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
from test_artifacts import replay, results
from test_competition import CompetitionTests, raw_game

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
        payload = results() if kind == 'results' else replay()
        if kind == 'results':
            payload['scores'] = [.8, .2, 0, 0, 0, 0, 0]
        yield httpx.Response(200, content=json.dumps(payload).encode())
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
    uvicorn.run(create_app(fixture.store), host="127.0.0.1", port=8661, access_log=False)
finally:
    fixture.doCleanups()
