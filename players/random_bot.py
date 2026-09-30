"""Seeded random legal orders, with explicit detection of silently rejected inputs."""

import json
import os
import random
import time
from urllib.error import HTTPError, URLError

from players.api import WebDiplomacy, order_difference
from players.legal_orders import LegalOrders


def choose_orders(api, context, seed):
    board = api.file(context["files"]["game"])
    if (board["turn"], board["phase"]) != (context["game"]["turn"], context["game"]["phase"]):
        return None  # The committed phase changed while reading its public file.
    variant = api.file(context["files"]["variant"])
    rng = random.Random(f"{seed}:{api.country_id}:{board['turn']}:{board['phase']}")
    return LegalOrders(variant, board).choose(context, rng)


def submit(api, context, requested):
    saved = api.orders(context, requested)
    latest = api.context()["game"]
    if (latest["turn"], latest["phase"]) != (context["game"]["turn"], context["game"]["phase"]):
        return False
    difference = order_difference(requested, saved, len(context["orders"]["orders"]))
    if any(difference.values()):
        raise ValueError("Upstream changed random orders: " + json.dumps(difference))
    return True


def main():
    api = WebDiplomacy(
        os.environ["WEBDIP_URL"],
        os.environ["WEBDIP_API_KEY"],
        os.environ["WEBDIP_GAME_ID"],
        os.environ["WEBDIP_COUNTRY_ID"],
    )
    seed = int(os.environ.get("WEBDIP_SEED", "0"))
    previous = None
    while True:
        phase = None
        try:
            context = api.context()
            game = context["game"]
            phase = (game["turn"], game["phase"])
            if game["phase"] == "Finished":
                return
            if game["phase"] != "Pre-game" and phase != previous and context.get("orders"):
                requested = choose_orders(api, context, seed)
                if requested is not None and (not requested or submit(api, context, requested)):
                    print(
                        json.dumps(
                            {
                                "event": "orders_saved",
                                "turn": phase[0],
                                "phase": phase[1],
                                "orders": len(requested),
                                "rejected": 0,
                            }
                        ),
                        flush=True,
                    )
                    previous = phase
        except HTTPError as error:
            if error.code == 404:
                return  # Upstream erases cancelled games; the launcher retains presence and press.
            if phase is None or error.code != 400:
                raise
            latest = api.context()["game"]
            if (latest["turn"], latest["phase"]) == phase:
                raise  # A current-phase rejection is a real failure, never an implicit hold fallback.
        except (URLError, TimeoutError):
            pass
        time.sleep(0.2)


if __name__ == "__main__":
    main()
