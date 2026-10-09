"""Play through the real HTTP bridge and a platform-like GET-only WebSocket proxy."""

import argparse
import json
import secrets
import shlex
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from players.api import WebDiplomacy, holds, verify_orders
from tools.check_browser import free_port
from tools.check_episode import wait_for
from tools.play_proxy import PREFIX
from tools.player_fixture import game


def expect_status(action, status):
    try:
        action()
    except HTTPError as error:
        assert error.code == status, (error.code, status)
    else:
        raise AssertionError(f"Expected HTTP {status}")


def run(image):
    marker = "bridge-private-press-" + secrets.token_hex(8)
    with game(image, "bridge", phase_minutes=59) as (clients, directory, container, sockets):
        config = json.loads((directory / "config.json").read_text())
        participant = {"slot": 0, "viewer_token": secrets.token_urlsafe(24), "runtime_token": config["tokens"][0]}
        participant_path = directory / "participant.json"
        participant_path.write_text(json.dumps(participant))
        port = free_port()
        proxy_base = f"http://127.0.0.1:{port}"
        processes = []
        with (directory / "proxy.log").open("w") as proxy_log, (directory / "bridge.log").open("w") as bridge_log:
            try:
                processes.append(
                    subprocess.Popen(
                        [
                            sys.executable,
                            "-m",
                            "tools.play_proxy",
                            "--upstream",
                            clients[1].url,
                            "--port",
                            str(port),
                            "--participant-file",
                            str(participant_path),
                        ],
                        stdout=proxy_log,
                        stderr=proxy_log,
                    )
                )

                def proxy_ready():
                    try:
                        return urlopen(proxy_base + "/audit", timeout=0.5).status == 200
                    except (URLError, TimeoutError):
                        return False

                wait_for(proxy_ready)
                viewer = (
                    proxy_base
                    + PREFIX
                    + "/client/player?"
                    + urlencode({"slot": 0, "token": participant["viewer_token"]})
                )
                launch_path = directory / "launch.json"
                launch_path.write_text(json.dumps({"kind": "player", "viewer_url": viewer}))
                env_path = directory / "bot.env"
                sockets[0].close()
                sockets[0] = None
                processes.append(
                    subprocess.Popen(
                        [
                            sys.executable,
                            "-m",
                            "players.bridge",
                            "--seat-url-file",
                            str(launch_path),
                            "--env-file",
                            str(env_path),
                        ],
                        stdout=bridge_log,
                        stderr=bridge_log,
                    )
                )
                wait_for(lambda: env_path.exists() and "WEBDIP_SEED" in env_path.read_text())
                env = dict(
                    shlex.split(line.removeprefix("export "))[0].split("=", 1)
                    for line in env_path.read_text().splitlines()
                )
                api = WebDiplomacy(
                    env["WEBDIP_URL"], env["WEBDIP_API_KEY"], env["WEBDIP_GAME_ID"], env["WEBDIP_COUNTRY_ID"]
                )
                assert api.key not in config["tokens"] and api.key != participant["viewer_token"]
                context = api.context()
                requested = holds(context)
                saved = api.orders(context, requested, ready="No")
                verify_orders(requested, saved)
                verify_orders(requested, api.context()["orders"]["orders"])
                assert api.file({"url": "variants/Classic/cache/variant.json"})
                expect_status(lambda: urlopen(api.url + "/api.php?route=game/playercontext"), 401)
                expect_status(lambda: api.request("game/playercontext", gameID=api.game_id + 1), 403)
                other_country = api.country_id % 7 + 1
                wrong_seat = WebDiplomacy(api.url, api.key, api.game_id, other_country)
                expect_status(lambda: wrong_seat.orders(context, requested, ready="No"), 403)
                expect_status(lambda: api.request("sandbox/copy", body={}), 403)
                api.request(
                    "game/sendmessage",
                    body=dict(gameID=api.game_id, countryID=api.country_id, toCountryID=other_country, message=marker),
                )
                assert marker in json.dumps(clients[other_country].context())
                for country, direct in clients.items():
                    if country not in {api.country_id, other_country}:
                        assert marker not in json.dumps(direct.context())
                for country, direct in clients.items():
                    current = api if country == api.country_id else direct
                    current.orders(current.context(), holds(current.context()))
                wait_for(lambda: api.context()["game"]["turn"] != context["game"]["turn"])
                expect_status(lambda: api.orders(context, requested), 400)  # Preserve upstream's stale-turn error.
                for country, direct in clients.items():
                    (api if country == api.country_id else direct).vote("Draw")

                def finished():
                    try:
                        api.context()
                    except HTTPError as error:
                        return error.code == 410
                    return False

                wait_for(finished)
            finally:
                for process in reversed(processes):
                    process.terminate()
                    process.wait(timeout=15)
        logs = (directory / "bridge.log").read_text() + (directory / "proxy.log").read_text()
        assert all(secret not in logs for secret in [*config["tokens"], participant["viewer_token"], api.key, marker])
    assert marker not in (directory / "game.log").read_text()
    assert marker not in (directory / "replay.json").read_text()
    print("Bridge acceptance passed: saved orders, adjudication, private press, boundaries, stale error and completion")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image")
    run(parser.parse_args().image)
