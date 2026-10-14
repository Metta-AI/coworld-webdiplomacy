"""Bounded public-only ingest. Each artifact has its own persistent source ledger."""
import gzip
import hashlib
import io
import math
import re
import time
import zlib
from collections import Counter, defaultdict

from .api import ApiError, ArtifactMissing
from .config import ARTIFACT_PASS_SECONDS, ARTIFACTS_PER_PASS, MAX_ARTIFACT_DOWNLOAD_BYTES, MAX_ARTIFACT_JSON_BYTES
from .instrumentation import log_facts, result_instrumentation, supported
from .optimizer_tools import (
    POWERS,
    episode_dir,
    episode_taint,
    load_episode,
    movement_phases,
    read_json_file,
    suffix_for,
)

# Replay 2 adds the per-phase board for The board map.
PARSER_VERSIONS = {"results": 2, "replay": 2, "logs": 1}
TERMINAL = {"completed", "failed", "cancelled", "error", "canceled", "timed_out"}
# A game that ended without completing may never upload artifacts; after this long, a 404 or
# incomplete log is final rather than a pending retry.
ABSENT_AFTER_SECONDS = 3600


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
             "phases": phase_durations(results.get("transitions") or []),
             "instrumentation": result_instrumentation(results)}
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
    phases = movement_phases(replay)
    configs = {}
    for frame in replay:
        board = frame.get("game") or {}
        key = f"{board.get('turn')}:{board.get('phase')}"
        value = board.get("phaseMinutes") if board.get("phase") == "Diplomacy" else board.get("phaseMinutesRB")
        if isinstance(value, (int, float)) and math.isfinite(value) and value > 0:
            configs.setdefault(key, value * 60)
    return {"movement_phases": len(phases), "limits": configs,
            "phase_counts": dict(Counter(p["phase"] for p in last["history"]["phases"])),
            "early_finish": None, "board": board_facts(last)}


def contested_provinces(orders, province_of):
    """Provinces two or more powers fought over in one movement phase (the optimizer IDE's map rule):
    two powers moving in, or one moving in while another power's unit stays (it held, supported,
    convoyed, or its own move failed). An unopposed move and one power's own bounces do not count."""
    attackers, staying = defaultdict(set), defaultdict(set)
    for order in orders:
        moved = order["type"] == "Move"
        if moved and order.get("toTerrID") is not None:
            attackers[province_of(order["toTerrID"])].add(order["countryID"])
        if not (moved and order.get("success")):
            staying[province_of(order["terrID"])].add(order["countryID"])
    return sorted(p for p, movers in attackers.items() if len(movers | staying.get(p, set())) >= 2)


def board_facts(last):
    """Public board at the start of each movement phase, for The board map. Province IDs are replay
    territory IDs with coasts folded into their province. `held` maps a country ID to the provinces it
    holds: supply centres it owns, and other provinces where its (non-retreating) unit stands.
    `provinces` maps an ID to [name, is supply centre, home country ID or None]."""
    territories = last["variant"]["territories"]
    parent = {t["id"]: t.get("coastParentID") or t["id"] for t in territories}
    supply = {t["id"] for t in territories if t["supply"] and t.get("coast") != "Child"}

    def province_of(territory):
        return parent.get(int(territory), int(territory))

    phases, seen = [], set()
    for phase in last["history"]["phases"]:
        # The first entry of a duplicated turn wins; Retreats, Builds and the stale Finished board are skipped.
        if phase["phase"] != "Diplomacy" or phase["turn"] in seen:
            continue
        seen.add(phase["turn"])
        held = {p: int(c["countryID"]) for c in phase.get("centers") or []
                if int(c.get("countryID") or 0) and (p := province_of(c["terrID"])) in supply}
        for unit in phase.get("units") or []:
            p = province_of(unit["terrID"])
            if p not in supply and not unit.get("retreating"):
                held[p] = int(unit["countryID"])
        by_country = defaultdict(list)
        for p, country in sorted(held.items()):
            by_country[str(country)].append(p)
        phases.append({"turn": phase["turn"], "held": dict(sorted(by_country.items())),
                       "contested": contested_provinces(phase.get("orders") or [], province_of)})
    provinces = {str(t["id"]): [t["name"], t["id"] in supply,
                                int(t["homeCountryID"]) if t.get("homeCountryID") else None]
                 for t in territories if parent[t["id"]] == t["id"]}
    return {"phases": phases, "provinces": provinces}


def parser_version(kind, game):
    """Results and log parsers changed only for instrumented (0.7.12+) games; replay facts cover every game."""
    return PARSER_VERSIONS[kind] if kind == "replay" or supported(game.get("version")) else 1


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
        for kind in (("results", "replay", "logs") if supported(game.get("version")) else ("results", "replay")):
            source = snapshot.get(("artifact_" + kind, game_id), {})
            data = source.get("data") or {}
            version = parser_version(kind, game)
            if data.get("parser_version") == version and not source.get("error"):
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
        version = parser_version(kind, game)
        final = (game["status"] != "completed" and game.get("completed_at") is not None
                 and now - game["completed_at"] >= ABSENT_AFTER_SECONDS)
        try:
            if kind == "logs":
                buffer = io.BytesIO()
                collector.api.artifact(game_id, kind, buffer, MAX_ARTIFACT_DOWNLOAD_BYTES)
                facts = log_facts(buffer.getvalue())
                if facts["timing"] is None or (facts["activity"] is None and
                                               "interrupted_seconds" not in facts["timing"]):
                    if final:
                        raise ArtifactMissing("Game ended without complete instrumentation lines")
                    # Terminal status can precede the final stdout upload. Retry missing lines.
                    raise ApiError("Public instrumentation lines incomplete; retry pending")
                collector.store.success(name, game_id, {"state": "ready", "parser_version": PARSER_VERSIONS[kind],
                                        "facts": facts}, collector.clock(), cadence=0)
                continue
            # A stable episode ID isolates duplicate/reset round numbers. No user-supplied filesystem path.
            directory = episode_dir(collector.store.directory / "artifacts", {"round_number": 0}, game) / kind
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            path = directory / (kind + suffix_for("application/json"))
            staging = directory / "pending"
            staging.mkdir(exist_ok=True, mode=0o700)
            part = staging / path.name

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
            collector.store.success(name, game_id, {"state": "ready", "parser_version": version,
                                    "path": str(path.relative_to(collector.store.directory)), "sha256": digest,
                                    "facts": facts}, collector.clock(), cadence=0)
        except (ApiError, ValueError, KeyError, TypeError, IndexError, AttributeError, OSError, EOFError,
                OverflowError, RecursionError, zlib.error) as error:
            if isinstance(error, ArtifactMissing) and final:
                # Failed, cancelled or timed-out games often never produce artifacts; stop retrying.
                collector.store.success(name, game_id, {"state": "absent", "parser_version": version},
                                        collector.clock(), cadence=0)
                continue
            # Never store exception bodies, URLs, private data or local paths as an error.
            delay = min(3600, 60 * 2 ** min(source.get("failures", 0), 6))
            message = str(error) if isinstance(error, ApiError) else "Invalid artifact; retry pending"
            if isinstance(error, ApiError) and error.retry_after:
                delay = max(delay, error.retry_after)
                collector.store.defer(collector.clock() + error.retry_after)
            collector.store.failure(name, game_id, message, collector.clock(), delay)
