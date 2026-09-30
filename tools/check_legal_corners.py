"""Round-trip every generated candidate on scripted convoy, build and retreat boards."""

import argparse
import json
from collections import Counter

from players.api import holds, order, order_difference
from players.legal_orders import LegalOrders
from players.scenarios import play
from tools.check_episode import wait_for
from tools.player_fixture import game


def check(clients, contexts, counts):
    context = contexts[1]
    if context["game"]["phase"] == "Finished":
        return
    api = clients[1]

    def board_ready():
        board = api.file(api.context()["files"]["game"])
        return board if (board["turn"], board["phase"]) == (context["game"]["turn"], context["game"]["phase"]) else None

    board = wait_for(board_ready)
    legal = LegalOrders(api.file(context["files"]["variant"]), board)
    for country, api in clients.items():
        own = contexts[country]
        slots = own["orders"]["orders"]
        if not slots:
            continue
        if board["phase"] == "Builds":
            candidates = [[order("Wait")]]
            for item in legal.builds(country):
                candidates.append([item] + ([order("Wait")] if len(slots) > 1 else []))
        else:
            baseline = holds(own)
            candidates = []
            units = {unit["id"]: unit for unit in board["units"]}
            for index, slot in enumerate(slots):
                unit = units[slot["unitID"]]
                options = legal.retreats(unit) if board["phase"] == "Retreats" else legal.movement(unit)
                candidates.extend([*baseline[:index], item, *baseline[index + 1 :]] for item in options)
        for requested in candidates:
            saved = api.orders(own, requested, ready="No")
            diff = order_difference(requested, saved, len(slots))
            assert not any(diff.values()), (board["turn"], board["phase"], country, requested, saved, diff)
            counts.update(item["type"] for item in requested)
        api.orders(own, holds(own), ready="No")


def run(image):
    counts = Counter()
    for mode in ("tactics", "convoy", "coasts"):
        with game(image, "p4-corners-" + mode) as (clients, directory, container, sockets):
            play(mode, dict(sorted(clients.items())), lambda clients, contexts: check(clients, contexts, counts))
    assert {
        "Retreat",
        "Disband",
        "Convoy",
        "Build Army",
        "Build Fleet",
        "Wait",
        "Support move",
        "Support hold",
    } <= counts.keys()
    print(json.dumps({"candidate_orders": dict(counts), "rejected": 0}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("image")
    run(parser.parse_args().image)
