"""Capture public adjudication PNGs through the unchanged upstream map.php."""

import base64
import subprocess


def render_map(game_id, game, history):
    # map.php exposes only completed seasons during Diplomacy. Retreats/Builds
    # include this season's adjudication; draft orders and private press never enter it.
    turn = int(game["turn"]) - (game["phase"] == "Diplomacy")
    if game["phase"] == "Pre-game":
        turn = -1
    elif game["phase"] == "Finished":
        turn = max((phase["turn"] for phase in history["phases"]), default=-1)
    result = subprocess.run(["php", "/opt/php/wdc_map.php", str(game_id), str(turn)], capture_output=True, timeout=15)
    if result.returncode or not result.stdout.startswith(b"\x89PNG\r\n\x1a\n"):
        raise RuntimeError("public map renderer did not return a PNG")
    return {"turn": turn, "png": "data:image/png;base64," + base64.b64encode(result.stdout).decode()}
