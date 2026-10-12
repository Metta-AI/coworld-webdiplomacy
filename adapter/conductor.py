"""Compose one resident webDiplomacy game with the Conductor native runner."""

import gzip
import json
import os
import secrets
import shutil
import time
from pathlib import Path

from adapter import boot
from adapter.config import EpisodeConfig
from adapter.participation import ParticipationServer


def main():
    os.environ["PATH"] = "/opt/.venv/bin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    root = Path(os.environ["WORLD_SCRATCH_PATH"])
    request = json.loads(Path(os.environ["WORLD_INPUT_PATH"]).read_text())
    if request["policies"] or set(request.get("seats", [])) != {f"seat-{slot}" for slot in range(7)}:
        raise ValueError("webDiplomacy requires seven external seats")
    allowed = {"phase_minutes", "retreat_build_minutes", "press", "end_year", "scoring", "countries"}
    if set(request["config"]) - allowed:
        raise ValueError("Unknown webDiplomacy configuration")
    budget = min(5910, request["deadlineAt"] / 1000 - time.time() - 15)
    config = EpisodeConfig(
        **request["config"],
        tokens=[secrets.token_hex(24) for _ in range(7)],
        seed=request["seed"],
        episode_budget_seconds=budget,
        player_connect_timeout_seconds=0.1,
        completion_timeout_seconds=0,
    )
    config_path = root / "episode.json"
    config_path.write_text(config.model_dump_json())
    os.environ.update(
        WEBDIP_HTTP_PORT="8081",
        COGAME_CONFIG_URI=config_path.as_uri(),
        COGAME_RESULTS_URI=(root / "result.json").as_uri(),
        COGAME_SAVE_REPLAY_URI=(root / "replay.json").as_uri(),
    )
    # Restore a clean database before boot. Conductor destroys this container when the attempt ends.
    for path in ("/var/lib/mysql", "/run/webdip", "/application/cache"):
        shutil.rmtree(path, ignore_errors=True)
    shutil.copytree("/opt/webdip-seed", "/var/lib/mysql")
    control = None

    def ready(episode):
        nonlocal control
        control = ParticipationServer(
            episode=episode,
            socket_path=Path(os.environ["WORLD_CONTROL_PATH"]),
            journal_path=root / "participation.sqlite",
            port=8081,
        )

    try:
        status = boot.main(on_ready=ready)
    finally:
        if control:
            control.close()
    if status:
        raise RuntimeError("webDiplomacy failed")
    result = json.loads((root / "result.json").read_text())
    with (root / "replay.json").open("rb") as source, gzip.open(root / "replay.gz", "wb") as target:
        shutil.copyfileobj(source, target)
    output = {
        "result": result,
        "artifacts": [{"name": "replay", "path": "replay.gz", "mediaType": "application/gzip"}],
    }
    path = Path(os.environ["WORLD_OUTPUT_PATH"])
    temporary = path.with_suffix(".pending")
    temporary.write_text(json.dumps(output))
    temporary.replace(path)


if __name__ == "__main__":
    main()
