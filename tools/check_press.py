"""Real upstream sender/recipient isolation in player logs and ZIPs after draw/cancel."""

import argparse
import json
import os
import subprocess
import sys
import time
import zipfile

from players.api import WebDiplomacy
from tools.player_fixture import game


def run(image, cancel):
    processes = []
    logs = []
    marker = "private-press-real-engine-sentinel"
    with game(image, "p4-press-" + ("cancel" if cancel else "draw")) as (clients, directory, container, sockets):
        config = json.loads((directory / "config.json").read_text())
        invalid = WebDiplomacy(clients[1].url, "invalid-fixture-key", clients[1].game_id, 1)
        assert invalid.request("game/playercontext", raw=True, gameID=invalid.game_id) == ""
        try:
            invalid.context()
            raise AssertionError("empty API response counted as authentication")
        except json.JSONDecodeError:
            pass
        try:
            for slot, token in enumerate(config["tokens"]):
                api = next(api for api in clients.values() if api.key == token)
                log = (directory / f"player-{api.country_id}.log").open("w")
                logs.append(log)
                env = {
                    **os.environ,
                    "COWORLD_PLAYER_WS_URL": api.url.replace("http:", "ws:") + f"/player?slot={slot}&token={token}",
                    "COWORLD_PLAYER_ARTIFACT_UPLOAD_URL": (directory / f"player-{api.country_id}.zip")
                    .resolve()
                    .as_uri(),
                }
                sockets[slot].close()
                sockets[slot] = None
                process = subprocess.Popen(
                    [sys.executable, "-m", "players.launcher", sys.executable, "-c", "import time; time.sleep(120)"],
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
                processes.append(process)
            clients[1].request(
                "game/sendmessage", body=dict(gameID=clients[1].game_id, countryID=1, toCountryID=2, message=marker)
            )
            time.sleep(4)  # Allow the periodic pre-cancel snapshot, not a claim of lossless cancellation.
            for api in clients.values():
                api.vote("Cancel" if cancel else "Draw")
            started = time.monotonic()
            for process in processes:
                assert process.wait(timeout=20) == 0
            elapsed = time.monotonic() - started
            assert elapsed < 20, elapsed
            for country in clients:
                with zipfile.ZipFile(directory / f"player-{country}.zip") as archive:
                    record = json.loads(archive.read("private-press.json"))
                assert record["complete"] == (not cancel), record
                text = (directory / f"player-{country}.log").read_text()
                assert (marker in json.dumps(record)) == (country in (1, 2))
                assert (marker in text) == (country in (1, 2))
                assert all(token not in text for token in config["tokens"])
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=20)
            for log in logs:
                log.close()
    assert marker not in (directory / "game.log").read_text()
    assert marker not in (directory / "replay.json").read_text()
    print(
        json.dumps(
            dict(
                case="cancel" if cancel else "draw",
                private_seats=[1, 2],
                game_and_replay_private_messages=0,
                completion_seconds=round(elapsed, 3),
            )
        ),
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("image")
    args = parser.parse_args()
    for cancel in (False, True):
        run(args.image, cancel)
