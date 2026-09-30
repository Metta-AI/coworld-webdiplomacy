"""Keep Coworld presence separate from the bot's upstream HTTP traffic."""

import json
import os
import signal
import subprocess
import sys
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect


def main():
    url = urlsplit(os.environ["COWORLD_PLAYER_WS_URL"])
    query = dict(parse_qsl(url.query))
    query["mode"] = "bot"
    address = urlunsplit(url._replace(query=urlencode(query)))
    child = None
    stop = False

    def stopping(*_):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, stopping)
    signal.signal(signal.SIGINT, stopping)
    try:
        while not stop:
            try:
                with connect(address, ping_timeout=None, open_timeout=10) as ws:
                    hello = json.loads(ws.recv(timeout=10))
                    if hello.get("protocol") != "webdip-coworld/1":
                        raise RuntimeError("unexpected game protocol")
                    webdip = hello["webdip"]
                    if child is None:
                        env = {
                            **os.environ,
                            "WEBDIP_URL": webdip["base_url"],
                            "WEBDIP_API_KEY": webdip["api_key"],
                            "WEBDIP_GAME_ID": str(webdip["game_id"]),
                            "WEBDIP_COUNTRY_ID": str(webdip["country_id"]),
                        }
                        command = sys.argv[1:] or [sys.executable, "-m", "players.hold_bot"]
                        child = subprocess.Popen(command, env=env)
                    while not stop:
                        try:
                            message = json.loads(ws.recv(timeout=0.5))
                        except TimeoutError:
                            continue
                        if message.get("type") == "game_over":
                            # Private press archive is added in the player-artifact phase.
                            ws.send(json.dumps({"type": "game_over_ack"}))
                            return 0
            except (ConnectionClosed, OSError, TimeoutError):
                if not stop:
                    time.sleep(0.2)
    finally:
        if child and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
