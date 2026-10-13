"""Selected public instrumentation facts; game logs are parsed in memory, never retained."""
import gzip
import io
import json
import math
import re

from .config import MAX_ARTIFACT_JSON_BYTES

ORDER_PHASES = {"Diplomacy", "Retreats", "Builds"}
STAGES = ("storage", "game_creation", "services", "player_connect_wait", "play", "replay_write",
          "results_write", "acknowledgement_wait", "shutdown", "total", "interrupted")


def supported(version):
    if not isinstance(version, str):
        return False
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version or "")
    return bool(match and tuple(map(int, match.groups())) >= (0, 7, 12))


def seconds(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError("invalid instrumentation number")
    return value


def phase_key(row):
    if type(row["turn"]) is not int or row["turn"] < 0 or row["phase"] not in ORDER_PHASES:
        raise ValueError("invalid instrumentation phase")
    return row["turn"], row["phase"]


def timing(row):
    return {key + "_seconds": seconds(row[key + "_seconds"]) for key in STAGES if key + "_seconds" in row}


def log_facts(blob):
    if blob.startswith(b"\x1f\x8b"):
        with gzip.GzipFile(fileobj=io.BytesIO(blob)) as stream:
            blob = stream.read(MAX_ARTIFACT_JSON_BYTES + 1)
    if len(blob) > MAX_ARTIFACT_JSON_BYTES:
        raise ValueError("expanded log too large")
    facts = {"activity": None, "timing": None}
    for line in blob.decode("utf-8").splitlines():
        # Other service/status lines and JSON event types never enter the cache.
        if not line.lstrip().startswith("{"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            if re.search(r'"event"\s*:\s*"(seat_activity|timing)"', line):
                raise ValueError("truncated instrumentation event") from None
            continue
        if not isinstance(row, dict) or row.get("event") not in ("seat_activity", "timing"):
            continue
        key = "activity" if row["event"] == "seat_activity" else "timing"
        if facts[key] is not None:
            raise ValueError("duplicate instrumentation event")
        if key == "timing":
            facts[key] = timing(row)
            if facts[key].get("total_seconds") is None:
                raise ValueError("missing final log clock")
            continue
        phases, seen = [], set()
        for phase in row["phases"]:
            identity = phase_key(phase)
            if identity in seen or not isinstance(phase["seats"], list) or len(phase["seats"]) != 7:
                raise ValueError("invalid activity seats")
            seen.add(identity)
            phases.append({"turn": identity[0], "phase": identity[1], "seats": [
                None if seat is None else {k: seconds(seat[k]) for k in ("first_saved_seconds", "first_ready_seconds")}
                for seat in phase["seats"]]})
        facts[key] = phases
    return facts


def result_instrumentation(results):
    health = None
    if "seat_health" in results:
        health = []
        if len(results["seat_health"]) != 7:
            raise ValueError("invalid health seats")
        for slot, row in enumerate(results["seat_health"]):
            if row["slot"] != slot:
                raise ValueError("health slot mismatch")
            events = []
            for event in row["connections"]:
                elapsed = seconds(event["elapsed_seconds"])
                if event["event"] not in ("connect", "reconnect", "disconnect") or elapsed is None or (
                        events and elapsed < events[-1]["elapsed_seconds"]):
                    raise ValueError("invalid connection event")
                events.append({"event": event["event"], "elapsed_seconds": elapsed})
            count = row["api_requests"]
            if count is not None and (type(count) is not int or count < 0):
                raise ValueError("invalid API count")
            health.append({"slot": slot, "connections": events, "api_requests": count})
    unique = []
    for row in results.get("transitions", []):
        elapsed = seconds(row["elapsed_seconds"])
        if elapsed is None or unique and elapsed < unique[-1]["elapsed_seconds"]:
            raise ValueError("invalid transition time")
        key = (row["turn"], row["phase"])
        deadline = seconds(row.get("deadline_unix_time"))
        if unique and key == (unique[-1]["turn"], unique[-1]["phase"]):
            if deadline is not None:
                unique[-1]["deadline"] = deadline
            continue
        unique.append({"turn": row["turn"], "phase": row["phase"], "elapsed_seconds": elapsed,
                       "unix_time": seconds(row.get("unix_time")), "deadline": deadline})
    calls = {}
    for row in (results.get("gamemaster_calls") or {}).get("phases", []):
        key = phase_key(row) if row["phase"] in ORDER_PHASES else None
        if key is not None:
            if key in calls:
                raise ValueError("duplicate phase calls")
            calls[key] = seconds(row["max_seconds"])
    phases = []
    for index, row in enumerate(unique):
        if row["phase"] not in ORDER_PHASES:
            continue
        next_row = unique[index+1] if index+1 < len(unique) else None
        natural = bool(next_row and next_row["phase"] in ORDER_PHASES)
        length = (row["deadline"] - row["unix_time"]
                  if row["deadline"] is not None and row["unix_time"] is not None else None)
        early = (next_row["unix_time"] < row["deadline"] if natural and
                 next_row["unix_time"] is not None and row["deadline"] is not None else None)
        phases.append({"turn": row["turn"], "phase": row["phase"], "natural_end": natural,
                       "length": length if length is not None and length > 0 else None,
                       "seconds": next_row["elapsed_seconds"]-row["elapsed_seconds"] if next_row else None,
                       "early": early, "adjudication": calls.get((row["turn"], row["phase"]))})
    return {"health": health, "timing": timing(results.get("timing") or {}), "phases": phases,
            "first_phase_seconds": next((r["elapsed_seconds"] for r in unique if r["phase"] in ORDER_PHASES), None)}
