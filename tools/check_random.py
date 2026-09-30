"""Check seeded input legality against upstream saved responses through 1910."""

import argparse
import json
from collections import Counter

from players.api import order_difference
from players.random_bot import choose_orders
from players.scenarios import wait_phase
from tools.check_episode import wait_for
from tools.player_fixture import game


def run(image, seed):
    counts = Counter()
    phases = []
    with game(image, "p4-random", seed) as (clients, directory, container, sockets):
        while True:
            context = clients[1].context()
            current = (context["game"]["turn"], context["game"]["phase"])
            phases.append(current)
            if current[0] >= 20:
                break
            for country, api in clients.items():
                own = api.context()

                def choose():
                    requested = choose_orders(api, own, seed)
                    return (requested,) if requested is not None else None

                requested = wait_for(choose)[0]
                if requested:
                    saved = api.orders(own, requested, ready="No")
                    diff = order_difference(requested, saved, len(own["orders"]["orders"]))
                    assert not any(diff.values()), (seed, current, country, requested, saved, diff)
                    counts.update(item["type"] for item in requested)
            for api in clients.values():
                own = api.context()
                if own["orders"]["orders"] and (own["game"]["turn"], own["game"]["phase"]) == current:
                    api.orders(own, [], ready="Yes")
            wait_phase(clients[1], current)
        for api in clients.values():
            api.vote("Draw")
        wait_for(lambda: clients[1].context()["game"]["phase"] == "Finished")
        result = dict(seed=seed, phases=phases, orders=dict(counts), rejected=0)
        (directory / "random.json").write_text(json.dumps(result, indent=2))
        print(json.dumps(result), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("image")
    parser.add_argument("seeds", nargs="*", type=int, default=[0, 17, 42])
    args = parser.parse_args()
    for seed in args.seeds:
        run(args.image, seed)
