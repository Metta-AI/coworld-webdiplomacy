"""Create and observe an episode; only upstream advances phases and applies votes."""

import bisect
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
ORDER_PHASES = ("Diplomacy", "Retreats", "Builds")


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


class TimingProfile:
    """The container's life as consecutive stages, each timed from the end of the one before.

    Stage names end in `_seconds` and keep the order in which they ended.
    """

    def __init__(self):
        self.mark = time.monotonic()
        self.stages = {}

    def lap(self, name):
        now = time.monotonic()
        self.stages[f"{name}_seconds"] = round(now - self.mark, 3)
        self.mark = now


def year_complete(game, end_year):
    autumn = 2 * (end_year - 1901) + 1
    return int(game["turn"]) > autumn or (int(game["turn"]) == autumn and game["phase"] == "Builds")


class Episode:
    def __init__(self, config: EpisodeConfig, timing=None):
        self.config = config
        self.created_at = time.monotonic()
        self.timing = timing or TimingProfile()
        self.lock = threading.Lock()
        self.connections = {}
        self.connection_events = [[] for _ in range(7)]
        # Private during play: {(turn, phase): {"started": monotonic, "seats": {countryID: ...}}}.
        self.order_status = {}
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
        created = php(
            "wdc_create_game", payload={**config.model_dump(exclude={"players"}), "countries": self.countries}
        )
        self.game_id = int(created["game_id"])
        self.seats = created["seats"]
        self.tick()

    def gamemaster_calls(self, path=Path("/run/webdip/logs/gamemaster-timing.log")):
        # nginx logs `$msec $request_time $status`: the request's end time, duration and status.
        lines = path.read_text().splitlines() if path.exists() else []
        rows = [line.split() for line in lines]
        calls = [(float(row[0]) - float(row[1]), float(row[1]), int(row[2])) for row in rows if len(row) == 3]
        durations = [duration for _, duration, _ in calls]
        # A call belongs to the phase it started in: the call that adjudicates a
        # phase starts before the adapter observes the next one.
        phases = []
        phase_starts = []
        for transition in self.transitions:
            if not phases or (phases[-1]["turn"], phases[-1]["phase"]) != (transition["turn"], transition["phase"]):
                phases.append({"turn": transition["turn"], "phase": transition["phase"], "durations": []})
                phase_starts.append(transition["unix_time"])
        for started, duration, _ in calls:
            if phases:
                phases[max(bisect.bisect_right(phase_starts, started) - 1, 0)]["durations"].append(duration)
        return {
            "count": len(durations),
            "p50_seconds": statistics.median(durations) if durations else None,
            "max_seconds": max(durations) if durations else None,
            "http_errors": sum(status >= 400 for _, _, status in calls),
            "phases": [
                {
                    "turn": phase["turn"],
                    "phase": phase["phase"],
                    "count": len(phase["durations"]),
                    "max_seconds": max(phase["durations"]) if phase["durations"] else None,
                }
                for phase in phases
            ],
        }

    def record_connection(self, slot, connected):
        """Note a seat connecting or disconnecting; the caller holds `self.lock`."""
        events = self.connection_events[slot]
        event = "disconnect" if not connected else "reconnect" if events else "connect"
        events.append({"event": event, "elapsed_seconds": round(time.monotonic() - self.created_at, 3)})

    def sample_order_status(self, game, private_activity, now):
        """Note when each seat is first seen with orders saved, and Ready, in this phase.

        Upstream hides order status from the other players while an anonymous game
        runs, so these samples stay in memory until the game ends (`seat_activity`).
        """
        if game["phase"] not in ORDER_PHASES:
            return
        record = self.order_status.setdefault((int(game["turn"]), game["phase"]), {"started": now, "seats": {}})
        elapsed = round(now - record["started"], 3)
        for row in private_activity:
            status = set(row["order_status"].split(",")) if row["order_status"] else set()
            seat = record["seats"].setdefault(
                int(row["countryID"]), {"first_saved_seconds": None, "first_ready_seconds": None}
            )
            seat["orders_needed"] = "None" not in status
            if seat["first_saved_seconds"] is None and status & {"Saved", "Completed"}:
                seat["first_saved_seconds"] = elapsed
            if seat["first_ready_seconds"] is None and "Ready" in status:
                seat["first_ready_seconds"] = elapsed

    def seat_activity(self):
        """Per phase, each slot's first Saved and Ready times; null for a seat with no orders to give."""
        phases = []
        for (turn, phase), record in self.order_status.items():
            seats = []
            for country in self.countries:
                seat = record["seats"].get(country)
                if seat and seat["orders_needed"]:
                    seats.append({key: seat[key] for key in ("first_saved_seconds", "first_ready_seconds")})
                else:
                    seats.append(None)
            phases.append({"turn": turn, "phase": phase, "seats": seats})
        return {"event": "seat_activity", "phases": phases}

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
                "deadline_unix_time": int(game["processTime"] or 0) or None,
            }
            self.transitions.append(transition)
            print(json.dumps({"event": "phase", **transition}), flush=True)
        self.sample_order_status(game, state["private_activity"], now)
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
            self.timing.lap("player_connect_wait")
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
        self.timing.lap("play")
        cancelled = state["game"] is None
        api_requests = {int(row["countryID"]): row["api_requests"] for row in state["private_activity"]}
        with self.lock:
            connection_events = [list(events) for events in self.connection_events]
        result = {
            "scores": scores(state["members"], self.countries, self.config.scoring, cancelled),
            "outcome": "cancelled" if cancelled else state["game"]["gameOver"].lower(),
            "reason": reason,
            "seed": self.config.seed,
            "countries": self.countries,
            "members": state["members"],
            "final_state": state["game"],
            "transitions": self.transitions,
            "gamemaster_calls": self.gamemaster_calls(),
            "seat_health": [
                {"slot": slot, "connections": connection_events[slot], "api_requests": api_requests.get(country)}
                for slot, country in enumerate(self.countries)
            ],
        }
        final_public = {**self.frames[-1], "ending": {"outcome": result["outcome"], "reason": reason}}
        if cancelled:
            self.frames.append(final_public)
        else:
            self.frames[-1] = final_public
        # These URIs are supplied by the runner, never by a player.
        write_artifact(
            os.environ["COGAME_SAVE_REPLAY_URI"], json.dumps(self.saved_frames()).encode(), "COGAME_SAVE_REPLAY_METHOD"
        )
        self.timing.lap("replay_write")
        result["timing"] = dict(self.timing.stages)
        write_artifact(os.environ["COGAME_RESULTS_URI"], json.dumps(result).encode(), "COGAME_RESULTS_METHOD")
        self.timing.lap("results_write")
        with self.lock:
            self.public = final_public
            self.result = result
            self.finished = True
            self.finished_at = time.monotonic()
            self.expected_acknowledgements = set(self.connections)
        # The game is over, so order status is no longer hidden from anyone.
        print(json.dumps(self.seat_activity()), flush=True)
        calls = {key: value for key, value in result["gamemaster_calls"].items() if key != "phases"}
        summary = {"event": "game_over", "outcome": result["outcome"], "reason": reason, "gamemaster_calls": calls}
        print(json.dumps(summary), flush=True)

    def saved_frames(self):
        """Frames for the saved replay: seat names join each frame's `episode` only here.

        Names are written once the game is over, into copies, so the live `/global`
        stream (which shares these frame objects) never carries them.
        """
        if not self.config.players:
            return self.frames
        players = [
            {"slot": slot, "countryID": country, "name": player.name}
            for slot, (country, player) in enumerate(zip(self.countries, self.config.players, strict=True))
        ]
        return [{**frame, "episode": {**frame["episode"], "players": players}} for frame in self.frames]

    def completion_ready(self):
        with self.lock:
            return self.finished and (
                self.expected_acknowledgements <= self.acknowledged
                or time.monotonic() - self.finished_at >= self.config.completion_timeout_seconds
            )
