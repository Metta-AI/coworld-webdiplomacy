"""Fresh hardened Coworld games for API player acceptance checks."""

import json
import secrets
import subprocess
from contextlib import ExitStack, contextmanager
from pathlib import Path
from urllib.request import urlopen

from websockets.sync.client import connect

from adapter.config import EpisodeConfig
from players.api import WebDiplomacy
from tools.check_boot import docker
from tools.check_episode import wait_for


@contextmanager
def game(image, name, seed=0, **options):
    directory = Path("tmp") / (name + "-" + secrets.token_hex(3))
    directory.mkdir(parents=True)
    # Game root has no CAP_DAC_OVERRIDE; it can write here only if the mode allows it.
    directory.chmod(0o777)
    config = dict(
        tokens=[secrets.token_hex(24) for _ in range(7)],
        seed=seed,
        press="Regular",
        end_year=2000,
        player_connect_timeout_seconds=30,
        episode_budget_seconds=600,
        completion_timeout_seconds=20,
        **options,
    )
    config = EpisodeConfig.model_validate(config).model_dump()
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
    stack = ExitStack()
    try:
        docker("start", container)
        port = docker("port", container, "8080/tcp").rsplit(":", 1)[1]
        base = "http://127.0.0.1:" + port

        def healthy():
            try:
                return urlopen(base + "/healthz", timeout=0.5).status == 200
            except OSError:
                return False

        wait_for(healthy)
        clients, sockets = {}, []
        for slot, token in enumerate(config["tokens"]):
            ws = stack.enter_context(
                connect(base.replace("http:", "ws:") + f"/player?slot={slot}&token={token}", ping_timeout=None)
            )
            sockets.append(ws)
            hello = json.loads(ws.recv(timeout=3))["webdip"]
            country = hello["country_id"]
            clients[country] = WebDiplomacy(base, token, hello["game_id"], country)
        wait_for(lambda: clients[1].context()["game"]["phase"] == "Diplomacy")
        yield clients, directory, container, sockets
        for ws in sockets:
            if ws is None:
                continue
            while json.loads(ws.recv(timeout=20))["type"] != "game_over":
                pass
            ws.send(json.dumps({"type": "game_over_ack"}))
        assert subprocess.check_output(["docker", "wait", container], text=True, timeout=20).strip() == "0"
    finally:
        (directory / "game.log").write_text(docker("logs", container))
        stack.close()
        docker("rm", "-f", container)
