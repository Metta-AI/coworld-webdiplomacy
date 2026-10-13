"""Bounded public-only ingest. Each artifact has its own persistent source ledger."""
import gzip
import hashlib
import math
import re
import time
import zlib
from collections import Counter

from .api import ApiError
from .config import ARTIFACT_PASS_SECONDS, ARTIFACTS_PER_PASS, MAX_ARTIFACT_DOWNLOAD_BYTES, MAX_ARTIFACT_JSON_BYTES
from .optimizer_tools import (
    ABBREVIATION,
    POWERS,
    episode_dir,
    episode_taint,
    load_episode,
    movement_phases,
    province,
    read_json_file,
    suffix_for,
)

PARSER_VERSION = 1
TERMINAL = {"completed", "failed", "cancelled", "error", "canceled", "timed_out"}


def unpack(path):
    """Bound decompression before calling the shared JSON reader."""
    with path.open("rb") as handle:
        magic = handle.read(2)
    if magic == b"\x1f\x8b":
        with gzip.open(path, "rb") as handle:
            decoded = handle.read(MAX_ARTIFACT_JSON_BYTES + 1)
        if len(decoded) > MAX_ARTIFACT_JSON_BYTES:
            raise ValueError("expanded artifact too large")
        path.write_bytes(decoded)
    elif path.stat().st_size > MAX_ARTIFACT_JSON_BYTES:
        raise ValueError("artifact too large")
    return read_json_file(path)


def phase_durations(transitions):
    """First observation of each turn/phase; processing-state changes are not phases."""
    unique = []
    previous_elapsed = None
    for row in transitions:
        key = (row["turn"], row["phase"])
        elapsed = float(row["elapsed_seconds"])
        if not math.isfinite(elapsed) or elapsed < 0 or (
                previous_elapsed is not None and elapsed < previous_elapsed):
            raise ValueError("invalid transition clock")
        previous_elapsed = elapsed
        if not unique or key != (unique[-1]["turn"], unique[-1]["phase"]):
            unique.append({"turn": row["turn"], "phase": row["phase"], "elapsed_seconds": elapsed})
    durations = []
    for a, b in zip(unique, unique[1:]):
        if a["phase"] in ("Diplomacy", "Retreats", "Builds"):
            durations.append({"turn": a["turn"], "phase": a["phase"],
                              "seconds": b["elapsed_seconds"] - a["elapsed_seconds"]})
    return durations


def result_facts(directory, results, game):
    if not isinstance(results, dict) or not isinstance(results.get("outcome"), str):
        raise ValueError("invalid results")
    facts = {"outcome": results["outcome"], "reason": results.get("reason") or "unknown",
             "taints": episode_taint(game["status"], results), "seats": [], "score_issue": None,
             "phases": phase_durations(results.get("transitions") or [])}
    calls = results.get("gamemaster_calls") or {}
    facts["gamemaster"] = {k: calls[k] for k in ("count", "p50_seconds", "max_seconds", "http_errors")
                           if isinstance(calls.get(k), (int, float)) and math.isfinite(calls[k])}
    countries, scores = results.get("countries"), results.get("scores")
    valid = (isinstance(countries, list) and len(countries) == 7 and
             {str(c) for c in countries} == {str(c) for c in POWERS} and
             isinstance(scores, list) and len(scores) == 7 and
             all(isinstance(s, (int, float)) and not isinstance(s, bool) and math.isfinite(s) and 0 <= s <= 1
                 for s in scores))
    if not valid:
        facts["score_issue"] = "Missing or invalid seven-seat scores/countries; scores quarantined"
        return facts
    # Separate kind directories mean a missing/corrupt replay cannot stop valid results metrics.
    seats, _ = load_episode(directory)
    facts["draw_survivors"] = sum(s.survived is True for s in seats) if facts["outcome"] == "drawn" else None
    facts["seats"] = [{"slot": s.slot, "power": s.power, "score": s.score,
                       "final_centers": s.final_centers, "survived": s.survived, "solo": s.solo} for s in seats]
    return facts


def replay_facts(replay):
    if not isinstance(replay, list) or not replay:
        raise ValueError("invalid replay")
    last = replay[-1]
    territories = last["variant"]["territories"]
    # Reuse exactly the board_counts input normalization (including coast children).
    phases = movement_phases(replay)
    counts = {province(ABBREVIATION[t["name"]]): {"failed_moves": 0, "owner_changes": 0} for t in territories}
    seen = set()
    for phase in phases:
        if phase["turn"] in seen:
            continue
        seen.add(phase["turn"])
        for order in phase["orders"]:
            if order["type"] == "move" and order["success"] is False:
                counts[order["to"]]["failed_moves"] += 1
    # Compare all known owned territories (not just supply centers), never the stale Finished board.
    names = {t["id"]: province(ABBREVIATION[t["name"]]) for t in territories}
    previous, compared, seen = None, 0, set()
    for phase in last["history"]["phases"]:
        key = (phase["turn"], phase["phase"])
        if key in seen or phase["phase"] in ("Finished", "Pre-game"):
            continue
        seen.add(key)
        if phase.get("centers") is None:
            previous = None
            continue
        current = {names[c["terrID"]]: c["countryID"] for c in phase["centers"]}
        if previous is not None:
            compared += 1
            for name in current.keys() & previous.keys():
                if current[name] != previous[name]:
                    counts[name]["owner_changes"] += 1
        previous = current
    configs = {}
    for frame in replay:
        board = frame.get("game") or {}
        key = f"{board.get('turn')}:{board.get('phase')}"
        value = board.get("phaseMinutes") if board.get("phase") == "Diplomacy" else board.get("phaseMinutesRB")
        if isinstance(value, (int, float)) and math.isfinite(value) and value > 0:
            configs.setdefault(key, value * 60)
    return {"provinces": counts, "movement_phases": len(phases), "board_comparisons": compared,
            "limits": configs, "phase_counts": dict(Counter(p["phase"] for p in last["history"]["phases"])),
            "early_finish": None}


def collect_artifacts(collector):
    """Four artifact attempts or twenty seconds between attempts, after all API poll groups."""
    snapshot = collector.store.snapshot()
    games = {g["id"]: (g, source["data"]["round_id"]) for (name, _), source in snapshot.items()
             if name == "episodes" and source.get("data") for g in source["data"]["rows"]
             if g["status"] in TERMINAL}
    candidates = []
    for game_id, (game, round_id) in games.items():
        if not re.fullmatch(r"ereq_[A-Za-z0-9-]+", game_id):
            continue
        for kind in ("results", "replay"):
            source = snapshot.get(("artifact_" + kind, game_id), {})
            data = source.get("data") or {}
            if data.get("parser_version") == PARSER_VERSION and not source.get("error"):
                continue
            if collector.clock() >= source.get("next_due", 0):
                candidates.append((source.get("attempted_at") or 0, game_id, kind, game, round_id, source))
    deadline = time.monotonic() + ARTIFACT_PASS_SECONDS
    for _, game_id, kind, game, round_id, source in sorted(candidates, key=lambda r: r[:3])[:ARTIFACTS_PER_PASS]:
        if time.monotonic() >= deadline or collector.clock() < collector.store.retry_not_before():
            break
        name = "artifact_" + kind
        now = collector.clock()
        collector.store.reserve(name, game_id, now, 60)
        # A stable episode ID isolates duplicate/reset round numbers. No user-supplied filesystem path.
        directory = episode_dir(collector.store.directory / "artifacts", {"round_number": 0}, game) / kind
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = directory / (kind + suffix_for("application/json"))
        staging = directory / "pending"
        staging.mkdir(exist_ok=True, mode=0o700)
        part = staging / path.name
        try:
            old = source.get("data") or {}
            if path.exists() and old and not source.get("error"):
                if hashlib.sha256(path.read_bytes()).hexdigest() != old["sha256"]:
                    raise ValueError("local artifact hash mismatch")
                payload = unpack(path)
                parse_directory = directory
            else:
                collector.api.artifact(game_id, kind, part, MAX_ARTIFACT_DOWNLOAD_BYTES)
                payload = unpack(part)
                parse_directory = staging
            facts = result_facts(parse_directory, payload, game) if kind == "results" else replay_facts(payload)
            if parse_directory == staging:
                part.replace(path)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            collector.store.success(name, game_id, {"state": "ready", "parser_version": PARSER_VERSION,
                                    "path": str(path.relative_to(collector.store.directory)), "sha256": digest,
                                    "facts": facts}, collector.clock(), cadence=0)
        except (ApiError, ValueError, KeyError, TypeError, IndexError, AttributeError, OSError, EOFError,
                OverflowError, RecursionError, zlib.error) as error:
            # Never store exception bodies, URLs, private data or local paths as an error.
            delay = min(3600, 60 * 2 ** min(source.get("failures", 0), 6))
            message = str(error) if isinstance(error, ApiError) else "Invalid artifact; retry pending"
            if isinstance(error, ApiError) and error.retry_after:
                delay = max(delay, error.retry_after)
                collector.store.defer(collector.clock() + error.retry_after)
            collector.store.failure(name, game_id, message, collector.clock(), delay)
