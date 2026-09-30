"""Hardened real-engine lifecycle checks beyond the seven-bot happy path."""

import argparse
import json
import secrets
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import urlopen

from websockets.exceptions import InvalidStatus
from websockets.sync.client import connect

from players.api import WebDiplomacy, holds
from tools.check_boot import docker


def wait_for(probe, timeout=15):
    deadline = time.monotonic() + timeout
    while True:
        result = probe()
        if result:
            return result
        assert time.monotonic() < deadline, "condition timed out"
        time.sleep(0.1)


def run_case(image, case):
    directory = Path("tmp") / ("p2-" + case + "-" + secrets.token_hex(3))
    directory.mkdir(parents=True)
    tokens = [secrets.token_hex(24) for _ in range(7)]
    if case == "race":
        tokens[0] = "seat&" + tokens[0]
    budget = 75 if case == "missing" else 14 if case == "pause" else 40
    config = {
        "tokens": tokens,
        "seed": 17,
        "press": "Regular",
        "end_year": 2000,
        "player_connect_timeout_seconds": 2 if case == "missing" else 20,
        "episode_budget_seconds": budget,
        "completion_timeout_seconds": 3,
    }
    (directory / "config.json").write_text(json.dumps(config))
    container = docker(
        "create",
        "--platform",
        "linux/amd64",
        "--cap-drop=ALL",
        "--security-opt",
        "no-new-privileges",
        "-p",
        "127.0.0.1::8080",
        "--mount",
        f"type=bind,src={directory.resolve()},dst=/artifacts",
        "-e",
        "COGAME_CONFIG_URI=file:///artifacts/config.json",
        "-e",
        "COGAME_RESULTS_URI=file:///artifacts/results.json",
        "-e",
        "COGAME_SAVE_REPLAY_URI=file:///artifacts/replay.json",
        image,
    )
    sockets = []
    stack = ExitStack()
    try:
        docker("start", container)
        port = docker("port", container, "8080/tcp").rsplit(":", 1)[1]
        base = f"http://127.0.0.1:{port}"

        def healthy():
            try:
                with urlopen(base + "/healthz", timeout=0.5) as response:
                    return response.status == 200
            except (OSError, HTTPError):
                return False

        wait_for(healthy)
        wsbase = base.replace("http:", "ws:")
        try:
            with connect(wsbase + "/player?slot=0&token=invalid"):
                raise AssertionError("invalid token was accepted")
        except InvalidStatus as error:
            assert error.response.status_code == 403
        with connect(wsbase + "/global") as global_ws:
            assert "game" in json.loads(global_ws.recv(timeout=2))
        clients = []
        for slot in range(6 if case == "missing" else 7):
            ws = stack.enter_context(
                connect(f"{wsbase}/player?slot={slot}&token={quote(tokens[slot])}", ping_timeout=None)
            )
            sockets.append(ws)
            hello = json.loads(ws.recv(timeout=2))
            assert hello["slot"] == slot and hello["protocol"] == "webdip-coworld/1"
            webdip = hello["webdip"]
            clients.append(WebDiplomacy(webdip["base_url"], webdip["api_key"], webdip["game_id"], webdip["country_id"]))
            assert ws.ping().wait(timeout=2)
        api = clients[0]
        wait_for(lambda: api.context()["game"]["phase"] == "Diplomacy")
        if case == "failure":
            docker("exec", container, "pkill", "-KILL", "-x", "node")
            code = subprocess.check_output(["docker", "wait", container], text=True, timeout=15).strip()
            assert code == "1", code
            assert not (directory / "results.json").exists()
            print("failure: PASS; active episode service crash exits 1 without fabricated results", flush=True)
            return
        if case == "race":
            audit = docker(
                "exec",
                container,
                "mariadb",
                "--defaults-file=/opt/config/mariadb.cnf",
                "-Nse",
                "SELECT COUNT(*) FROM webdiplomacy.wD_ApiPermissions; "
                "SELECT COUNT(*) FROM webdiplomacy.wD_Users WHERE type='User'; "
                "SELECT CONCAT(potType, ':', pot, ':', playerTypes) FROM webdiplomacy.wD_Games;",
            )
            assert audit.splitlines() == ["0", "7", "Unranked:0:MemberVsBots"], audit
            own = api.context()
            try:
                api.request(
                    "game/orders",
                    body={
                        "gameID": api.game_id,
                        "countryID": clients[1].country_id,
                        "turn": own["game"]["turn"],
                        "phase": own["game"]["phase"],
                        "ready": "Yes",
                        "orders": [],
                    },
                )
                raise AssertionError("cross-seat action accepted")
            except HTTPError as error:
                assert error.code == 403

            sockets[0].close()
            sockets[0] = stack.enter_context(connect(f"{wsbase}/player?slot=0&token={quote(tokens[0])}"))
            assert json.loads(sockets[0].recv(timeout=2))["type"] == "hello"
            assert json.loads(sockets[0].recv(timeout=2))["type"] == "game_started"
            context = api.context()
            context["game"]["turn"] += 50
            try:
                api.orders(context, holds(context))
                raise AssertionError("stale action was accepted")
            except HTTPError as error:
                assert error.code == 400

            def end():
                return json.loads(docker("exec", container, "php", "/opt/php/wdc_end.php", str(api.game_id)))

            with ThreadPoolExecutor(max_workers=2) as executor:
                outcomes = list(executor.map(lambda _: end(), range(2)))
            assert sum(item["ended"] for item in outcomes) == 1, outcomes
        elif case == "missing":
            for client in clients:
                context = client.context()
                client.orders(context, holds(context))
            wait_for(lambda: int(api.context()["game"]["turn"]) >= 1, timeout=68)
            print("missing seat: natural one-minute deadline advanced; no episode failure", flush=True)
            docker("exec", container, "php", "/opt/php/wdc_end.php", str(api.game_id))
        else:
            for client in clients:
                client.vote({"cancel": "Cancel", "pause": "Pause", "draw": "Draw"}[case])
            if case == "pause":
                wait_for(
                    lambda: (
                        json.loads(docker("exec", container, "php", "/opt/php/wdc_state.php", str(api.game_id)))[
                            "game"
                        ]["processStatus"]
                        == "Paused"
                    )
                )
        for ws in sockets:
            while json.loads(ws.recv(timeout=30))["type"] != "game_over":
                pass
            ws.send(json.dumps({"type": "game_over_ack"}))
        code = subprocess.check_output(["docker", "wait", container], text=True, timeout=15).strip()
        assert code == "0", code
        result = json.loads((directory / "results.json").read_text())
        frames = json.loads((directory / "replay.json").read_text())
        assert frames and abs(sum(result["scores"]) - 1) < 1e-9
        if case == "cancel":
            assert result["outcome"] == "cancelled" and result["scores"] == [1 / 7] * 7
            assert frames[-1]["ending"]["outcome"] == "cancelled"
        if case == "pause":
            assert result["reason"] == "episode_timeout"
        logs = docker("logs", container)
        assert all(token not in logs and token not in json.dumps(frames) for token in tokens)
        print(f"{case}: PASS; outcome={result['outcome']}; calls={result['gamemaster_calls']}", flush=True)
    except Exception:
        subprocess.run(["docker", "cp", f"{container}:/run/webdip/logs", str(directory / "private-logs")], check=False)
        (directory / "game.log").write_text(docker("logs", container))
        print(f"Failure diagnostics: {directory}", flush=True)
        raise
    finally:
        stack.close()
        docker("rm", "-f", container)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("image")
    parser.add_argument("cases", nargs="*", default=["race", "cancel", "draw", "pause", "missing", "failure"])
    args = parser.parse_args()
    for case in args.cases:
        run_case(args.image, case)
