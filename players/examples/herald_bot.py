"""Hold, announce each movement phase, ready up, and vote Draw from 1903."""

import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def call(route, body=None, **params):
    query = urlencode({"route": route, **params})
    request = Request(
        os.environ["WEBDIP_URL"].rstrip("/") + "/api.php?" + query,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + os.environ["WEBDIP_API_KEY"], "Content-Type": "application/json"},
    )
    with urlopen(request, timeout=10) as response:
        text = response.read().decode()
    return text if route == "game/setvote" else json.loads(text)


def main():
    seat = {"gameID": int(os.environ["WEBDIP_GAME_ID"]), "countryID": int(os.environ["WEBDIP_COUNTRY_ID"])}
    announced = set()
    while True:
        try:
            context = call("game/playercontext", gameID=seat["gameID"])
            game, member = context["game"], context["member"]
            turn, phase = int(game["turn"]), game["phase"]
            if phase == "Finished":
                return
            if phase != "Pre-game":
                if phase == "Diplomacy" and turn not in announced:
                    # At most one send attempt: retrying an ambiguous response can duplicate press.
                    announced.add(turn)
                    if game["pressType"] != "NoPress":
                        call("game/sendmessage", {**seat, "toCountryID": 0, "message": f"Herald holds, turn {turn}."})
                if 1901 + turn // 2 >= 1903 and "Draw" not in member["votes"]:
                    call("game/setvote", {**seat, "vote": "Draw", "voteOn": "Yes"})
                if not any(status in member["orderStatus"] for status in ("Ready", "None")):
                    # Empty orders preserve defaults; they do not erase previously saved orders.
                    call("game/orders", {**seat, "turn": turn, "phase": phase, "orders": [], "ready": "Yes"})
                    print(f"Ready: {turn} {phase}", flush=True)
        except HTTPError as error:
            if error.code == 404:  # Cancellation deletes the upstream game.
                return
            if error.code != 400:
                raise
            print("Phase changed or action rejected; refreshing context", flush=True)
        except (URLError, TimeoutError):
            print("Temporary connection failure; refreshing context", flush=True)
        time.sleep(0.5)


if __name__ == "__main__":
    main()
