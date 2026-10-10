"""Create and observe an episode; only upstream advances phases and applies votes."""

import json
import os
import random
import statistics
import subprocess
import threading
import time
from pathlib import Path

from adapter.artifacts import write_artifact
from adapter.config import EpisodeConfig
from adapter.maps import render_map

SOURCE_URL = "https://github.com/Metta-AI/coworld-webdiplomacy/tree/main"


def php(script, *arguments, payload=None):
    completed = subprocess.run(
        ["php", f"/opt/php/{script}.php", *map(str, arguments)],
        input=json.dumps(payload) if payload is not None else None,
        capture_output=True,
        text=True,
        timeout=15,
    )
    try:
        result = json.loads(completed.stdout)
        if completed.returncode or result.get("ok") is not True:
            raise ValueError("unsuccessful PHP result")
    except (ValueError, AttributeError):
        # PHP may exit 0 on an error, and its diagnostic body can contain secrets.
        Path("/run/webdip/logs/lifecycle-error.log").write_text(completed.stdout + completed.stderr)
        raise RuntimeError(f"{script} did not return structured success") from None
    return result


def scores(members, countries, scoring, cancelled=False):
    if cancelled:
        return [1 / 7] * 7
    by_country = {int(member["countryID"]): member for member in members}
    winners = {country for country, member in by_country.items() if member["status"] == "Won"}
    if winners:
        return [float(country in winners) for country in countries]
    weights = {}
    for country, member in by_country.items():
        surviving = member["status"] in ("Playing", "Drawn", "Survived")
        centers = int(member["supplyCenterNo"]) if surviving else 0
        weights[country] = (
            int(surviving) if scoring == "draw_size" else centers ** (2 if scoring == "sum_of_squares" else 1)
        )
    total = sum(weights.values())
    if not total:
        return [1 / 7] * 7
    return [weights[country] / total for country in countries]


def year_complete(game, end_year):
    autumn = 2 * (end_year - 1901) + 1
    return int(game["turn"]) > autumn or (int(game["turn"]) == autumn and game["phase"] == "Builds")


class Episode:
    def __init__(self, config: EpisodeConfig):
        self.config = config
        self.created_at = time.monotonic()
        self.lock = threading.Lock()
        self.connections = {}
        self.acknowledged = set()
        self.started = False
        self.finished = False
        self.start_requested = False
        self.frames = []
        self.maps = {}
        self.transitions = []
        self.public = {}
        self.result = None
        self.last_phase = None
        self.public_pending_since = None
        self.reason = None
        self.finished_at = None
        self.expected_acknowledgements = set()
        if config.countries is not None:
            self.countries = list(config.countries)
        else:
            self.countries = list(range(1, 8))
            random.Random(config.seed).shuffle(self.countries)
        created = php("wdc_create_game", payload={**config.model_dump(), "countries": self.countries})
        self.game_id = int(created["game_id"])
        self.seats = created["seats"]
        self.tick()

    def timing(self):
        path = Path("/run/webdip/logs/gamemaster-timing.log")
        calls = [line.split() for line in path.read_text().splitlines()] if path.exists() else []
        durations = [float(row[1]) for row in calls if len(row) == 3]
        return {
            "count": len(durations),
            "p50_seconds": statistics.median(durations) if durations else None,
            "max_seconds": max(durations) if durations else None,
            "http_errors": sum(int(row[2]) >= 400 for row in calls if len(row) == 3),
        }

    def tick(self):
        now = time.monotonic()
        if self.finished:
            return
        state = php("wdc_state", self.game_id)
        game = state["game"]
        if game is None:
            self.finish(state, "cancelled")
            return
        if game["processStatus"] == "Crashed":
            raise RuntimeError("upstream game crashed")
        phase = (int(game["turn"]), game["phase"], game["processStatus"])
        if phase != self.last_phase:
            self.last_phase = phase
            transition = {
                "elapsed_seconds": round(now - self.created_at, 3),
                "unix_time": time.time(),
                "turn": phase[0],
                "phase": phase[1],
                "process_status": phase[2],
            }
            self.transitions.append(transition)
            print(json.dumps({"event": "phase", **transition}), flush=True)
        # Only upstream's explicitly public files enter frames, never playercontext.
        public = {}
        consistent = True
        for name, file in state["files"].items():
            path = Path("/application") / file["url"]
            try:
                public[name] = json.loads(path.read_text())
            except FileNotFoundError:
                consistent = False
                break
            if name != "variant" and public[name]["version"] != file["version"]:
                consistent = False
        board = public.get("game", {})
        consistent = consistent and (board.get("turn"), board.get("phase")) == (phase[0], phase[1])
        if not consistent:
            if self.public_pending_since is None:
                self.public_pending_since = now
            if now - self.public_pending_since > 10:
                raise RuntimeError("public game files did not converge with committed game state")
            return
        self.public_pending_since = None
        public["lifecycle"] = {"turn": phase[0], "phase": phase[1], "process_status": phase[2]}
        public["episode"] = {"seed": self.config.seed}
        if self.config.render_maps:
            key = (phase[0], phase[1])
            if key not in self.maps:
                try:
                    self.maps[key] = render_map(self.game_id, game, public["history"])
                except (RuntimeError, subprocess.TimeoutExpired):
                    current = php("wdc_state", self.game_id)
                    if current["game"] is None:
                        self.finish(current, "cancelled")
                        return
                    if (int(current["game"]["turn"]), current["game"]["phase"]) != key:
                        return
                    raise
                # The gamemaster may commit while PHP renders; retry the public
                # snapshot instead of pairing a new image with an older phase.
                current = php("wdc_state", self.game_id)["game"]
                if current is None or (int(current["turn"]), current["phase"]) != key:
                    del self.maps[key]
                    return
            public["map"] = self.maps[key]
        with self.lock:
            self.public = public
            self.started = int(game["startTime"]) > 0
            connected = set(self.connections)
        if not self.frames or self.frames[-1].get("lifecycle") != public["lifecycle"]:
            self.frames.append(public)
        else:
            self.frames[-1] = public
        if game["phase"] == "Finished":
            self.finish(state, self.reason or game["gameOver"].lower())
            return
        if not self.start_requested and (
            len(connected) == 7 or now - self.created_at >= self.config.player_connect_timeout_seconds
        ):
            php("wdc_start", self.game_id)
            self.start_requested = True
        if now - self.created_at >= self.config.episode_budget_seconds:
            self.reason = "episode_timeout"
        elif self.started and year_complete(game, self.config.end_year):
            self.reason = "end_year"
        if self.reason:
            ended = php("wdc_end", self.game_id)
            if not ended["busy"]:
                final = php("wdc_state", self.game_id)
                if final["game"] is not None and final["game"]["phase"] != "Finished":
                    raise RuntimeError("finalization did not finish the game")
                # Read the final public files on the next observation.

    def finish(self, state, reason):
        cancelled = state["game"] is None
        result = {
            "scores": scores(state["members"], self.countries, self.config.scoring, cancelled),
            "outcome": "cancelled" if cancelled else state["game"]["gameOver"].lower(),
            "reason": reason,
            "seed": self.config.seed,
            "countries": self.countries,
            "members": state["members"],
            "final_state": state["game"],
            "transitions": self.transitions,
            "gamemaster_calls": self.timing(),
        }
        final_public = {**self.frames[-1], "ending": {"outcome": result["outcome"], "reason": reason}}
        if cancelled:
            self.frames.append(final_public)
        else:
            self.frames[-1] = final_public
        # These URIs are supplied by the runner, never by a player.
        write_artifact(
            os.environ["COGAME_SAVE_REPLAY_URI"], json.dumps(self.frames).encode(), "COGAME_SAVE_REPLAY_METHOD"
        )
        write_artifact(os.environ["COGAME_RESULTS_URI"], json.dumps(result).encode(), "COGAME_RESULTS_METHOD")
        with self.lock:
            self.public = final_public
            self.result = result
            self.finished = True
            self.finished_at = time.monotonic()
            self.expected_acknowledgements = set(self.connections)
        print(
            json.dumps(
                {
                    "event": "game_over",
                    "outcome": result["outcome"],
                    "reason": reason,
                    "gamemaster_calls": result["gamemaster_calls"],
                }
            ),
            flush=True,
        )

    def completion_ready(self):
        with self.lock:
            return self.finished and (
                self.expected_acknowledgements <= self.acknowledged
                or time.monotonic() - self.finished_at >= self.config.completion_timeout_seconds
            )
