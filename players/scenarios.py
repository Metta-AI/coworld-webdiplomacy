"""Regression players exercise the real HTTP API and wait for upstream processing."""

import json
import os
import sys
import time
from contextlib import ExitStack
from pathlib import Path
from urllib.request import urlopen

from websockets.sync.client import connect

from players.api import WebDiplomacy, holds, order


def public(context):
    result = {}
    for name, file in context["files"].items():
        with urlopen("http://127.0.0.1:8080/" + file["url"], timeout=10) as response:
            result[name] = json.load(response)
    return result


def wait_phase(api, previous=None):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        context = api.context()
        phase = (int(context["game"]["turn"]), context["game"]["phase"])
        if phase[1] != "Pre-game" and phase != previous:
            return context
        time.sleep(0.1)
    raise RuntimeError("upstream phase did not advance")


def verify_orders(sent, applied):
    for requested in sent:
        keys = ["type"]
        kind = requested["type"]
        if kind in ("Build Army", "Build Fleet", "Destroy"):
            keys += ["toTerrID"]
        elif kind != "Wait":
            keys += ["terrID"]
            if kind != "Hold" and kind != "Disband":
                keys += ["toTerrID"]
            if kind in ("Support move", "Convoy"):
                keys += ["fromTerrID"]
            if kind == "Move":
                keys += ["viaConvoy"]
        assert any(all(actual.get(key) == requested[key] for key in keys) for actual in applied), requested


def play(mode, clients):
    first = wait_phase(clients[1])
    territories = {item["name"]: int(item["id"]) for item in public(first)["variant"]["territories"]}
    if mode == "smoke":
        marker = "private-sentinel-coworld"
        clients[1].request(
            "game/sendmessage", body={"gameID": clients[1].game_id, "countryID": 1, "toCountryID": 2, "message": marker}
        )
        assert marker in json.dumps(clients[2].context())
        assert marker not in json.dumps(clients[3].context())
        assert marker not in json.dumps(public(first))
        steps = [{}, {}, {}]
    elif mode == "tactics":
        steps = [
            {
                "Paris": ("Move", "Burgundy"),
                "Munich": ("Move", "Ruhr"),
                "Berlin": ("Move", "Kiel"),
                "Kiel": ("Move", "Baltic Sea"),
            },
            {"Burgundy": ("Move", "Belgium"), "Ruhr": ("Move", "Holland"), "Kiel": ("Move", "Ruhr")},
            {},
            {"Holland": ("Move", "Belgium"), "Ruhr": ("Support move", "Belgium", "Holland")},
            {"Belgium": ("Retreat", "Picardy")},
        ]
    else:
        steps = [{}, {}]
    phases = []
    for index, overrides in enumerate(steps):
        contexts = {country: api.context() for country, api in clients.items()}
        current = contexts[1]["game"]
        phase = current["phase"]
        phases.append(phase)
        for country, api in clients.items():
            context = contexts[country]
            submitted = holds(context)
            if mode == "tactics" and phase == "Builds" and (context.get("orders") or {}).get("orders"):
                home = territories["Paris" if country == 2 else "Munich"]
                submitted = [order("Build Army", home, home)]
            for item in submitted:
                for name, change in overrides.items():
                    if item["terrID"] == territories[name]:
                        item.update(type=change[0], toTerrID=territories[change[1]])
                        if len(change) == 3:
                            item["fromTerrID"] = territories[change[2]]
                if mode == "convoy":
                    origin = item["terrID"]
                    if index == 0:
                        moves = {
                            territories["Brest"]: "English Channel",
                            territories["Paris"]: "Brest",
                            territories["London"]: "North Sea",
                        }
                        if origin in moves:
                            item.update(type="Move", toTerrID=territories[moves[origin]])
                    elif country == 2 and origin in (territories["Brest"], territories["English Channel"]):
                        item.update(
                            type="Move" if origin == territories["Brest"] else "Convoy",
                            toTerrID=territories["London"],
                            fromTerrID=territories["Brest"],
                            viaConvoy="Yes" if origin == territories["Brest"] else "No",
                            convoyPath=[territories["Brest"], territories["English Channel"]],
                        )
            if (context.get("orders") or {}).get("orders"):
                verify_orders(submitted, api.orders(context, submitted))
        latest = wait_phase(clients[1], (int(current["turn"]), phase))
        print(
            json.dumps(
                {"scenario": mode, "step": index, "phase": latest["game"]["phase"], "turn": latest["game"]["turn"]}
            ),
            flush=True,
        )
    final = public(latest)
    if mode == "tactics":
        assert phases == ["Diplomacy", "Diplomacy", "Builds", "Diplomacy", "Retreats"], phases
        units = final["history"]["phases"][-1]["units"]
        assert any(u["countryID"] == 2 and u["terrID"] == territories["Picardy"] for u in units)
        assert any(u["countryID"] == 4 and u["terrID"] == territories["Belgium"] for u in units)
    if mode == "convoy":
        assert any(
            u["countryID"] == 2 and u["terrID"] == territories["London"]
            for u in final["history"]["phases"][-1]["units"]
        )
    for api in clients.values():
        api.vote("Draw")
    deadline = time.monotonic() + 20
    while clients[1].context()["game"]["gameOver"] != "Drawn":
        assert time.monotonic() < deadline, "unanimous draw did not apply"
        time.sleep(0.1)
    print(f"PASS: {mode}, upstream phase progression and unanimous draw", flush=True)


def main():
    config = json.loads(Path(os.environ["COGAME_CONFIG_URI"].removeprefix("file://")).read_text())
    sockets = []
    stack = ExitStack()
    clients = {}
    try:
        for slot, token in enumerate(config["tokens"]):
            ws = stack.enter_context(
                connect(f"ws://127.0.0.1:8080/player?slot={slot}&token={token}", ping_timeout=None)
            )
            sockets.append(ws)
            hello = json.loads(ws.recv(timeout=10))["webdip"]
            clients[hello["country_id"]] = WebDiplomacy(
                hello["base_url"], hello["api_key"], hello["game_id"], hello["country_id"]
            )
        play(sys.argv[1], clients)
        for ws in sockets:
            while json.loads(ws.recv(timeout=20))["type"] != "game_over":
                pass
            ws.send(json.dumps({"type": "game_over_ack"}))
    finally:
        stack.close()


if __name__ == "__main__":
    main()
