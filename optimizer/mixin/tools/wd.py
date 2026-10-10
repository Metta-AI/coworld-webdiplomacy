#!/usr/bin/env python3
"""webDiplomacy lab entry point: batch metrics, seat rows, LLM costs, and local runs.

Standard-library Python 3.12+. Run from the optimizer root (planted lab) or the mixin root:

    python3 games/webdiplomacy/tools/wd.py metrics DIR... [--policy NAME:vN | --slot K] [--keep-tainted] [--json]
    python3 games/webdiplomacy/tools/wd.py seats DIR... [--policy NAME:vN]
    python3 games/webdiplomacy/tools/wd.py costs DIR... [--json]
    python3 games/webdiplomacy/tools/wd.py local --image IMG [--episodes N] [--variant V] --out DIR
    python3 games/webdiplomacy/tools/wd.py arena --image IMG [--candidate-env K=V]... [--field-env K=V]... --out DIR
    python3 games/webdiplomacy/tools/wd.py slim DIR...

DIR is any directory holding episodes: a hosted batch from the seed's
`fetch-artifacts` (`.runtime/artifacts/<xreq>/`), one episode, or local run output.
See `webdip_episodes.py` for the layouts it reads and the taint flags.

metrics
    Per-power results of the target seats next to the same-batch FIELD PAR (mean score
    of every non-target seat at that power in the same directories), plus coverage and
    our telemetry (rejected orders, exceptions, failing LLM calls). Episodes whose
    target seat is tainted, and cancelled or failed episodes, are dropped before any
    mean and counted; `--keep-tainted` keeps them. Target = `--policy NAME:vN`
    (hosted), a local seating label (`candidate`), or `--slot K`. Without either,
    every seat is pooled. Exit 0 = parsed, 2 = no target seats.
    Example: wd.py metrics .runtime/artifacts/xreq_abc --policy my-bot:v3

seats
    One JSON line per seat: episode, slot, policy, power, score, final_centers,
    survived, solo, outcome, centers_by_year (supply centres after each autumn; the
    final year from results.json), order stats, our log telemetry, taint.

costs
    LLM spend from our seats' `llm_call` events: per seat and game, per movement
    phase, and the projected cost of a full classic-press game (16 movement phases)
    with 1 or 7 LLM seats. Exit 2 when no llm_call events are found.

local   (needs Docker and the coworld CLI)
    N local episodes with IMG in every seat. Self-play: for debugging and activation
    checks only, never for verdicts. `--use-llm` forwards the host's
    COWORLD_LLM_ENDPOINT into the seats; run `llm_sidecar_local.py` first and set
    COWORLD_LLM_ENDPOINT=http://host.docker.internal:<port>.

arena   (needs Docker and the coworld CLI)
    Local screening: slot 0 plays the candidate, slots 1-6 play the field. Each seat
    is configured separately through an episode request file (`players[slot]` with
    its own image, run argv and public env), so the policy needs no seat dispatch.
    The two sides can use different images (`--field-image`), argv (`--candidate-run`,
    `--field-run`) and public env (`--candidate-env`, `--field-env`), or the field can
    be a player bundled with the game (`--field-player random`). With no field
    options the field is six copies of `--image` with CASTLEREAGH_POLICY=search, the
    reference policy's default mode. Countries are reshuffled every episode, so slot
    0 samples every power; `--country France` pins slot 0's power instead (needs a
    published coworld whose config accepts `countries`). Read the batch with
    `metrics OUT --policy candidate`; parity is 1/7 = 0.143. Local results do not
    transfer to the hosted field.
    Example (reference policy, press mode vs a search field):
        wd.py arena --image webdip-castlereagh-search:exp12 \\
            --candidate-env CASTLEREAGH_POLICY=press --use-llm \\
            --episodes 8 --parallel 4 --out .runtime/local/exp12-arena

    How local runs find the game manifest, most explicit first:
      1. `--manifest PATH` to a coworld_manifest.json;
      2. otherwise `coworld download <--coworld, default webdiplomacy> -o <--cache>`
         (default cache `.runtime/coworld` under the current directory). The download
         is cached and restores pruned game images; the manifest path and game version
         are recorded in OUT/run.json. Pass `--coworld cow_<id>` to pin one version
         for a whole campaign.
    The CLI is `$COWORLD_CMD` when set (e.g. "uv run coworld"), else `coworld` on PATH.

    Robustness: one image tag per experiment (rebuilding a tag mid-run silently
    switches later episodes to new code; the image ID is recorded in run.json); each
    episode is retried up to `--attempts` times when it leaves no results.json;
    Ctrl-C or SIGTERM stops the batch and removes its game and player containers;
    replays are written without map PNGs unless `--maps`.

slim
    Drop map PNGs from every replay under DIRs (hosted replays can carry one per
    phase). Keeps gzip compression when the file had it.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import shlex
import shutil
import signal
import statistics
import subprocess
import sys
import threading
import uuid
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from webdip_episodes import (  # noqa: E402
    POWERS,
    REPLAY_NAMES,
    drop_tainted_episodes,
    episode_dirs,
    field_par,
    llm_call_cost,
    llm_call_failed,
    load_dirs,
    read_log,
    seat_log_paths,
)

CLASSIC_PRESS_MOVEMENT_PHASES = 16  # Spring and Autumn of 1901-1908
# Default arena field: copies of the reference policy in its default (search) mode.
DEFAULT_FIELD_ENV = {"CASTLEREAGH_POLICY": "search"}
COUNTRY_IDS = {name.lower(): cid for cid, name in POWERS.items()}


def _mean(xs):
    xs = list(xs)
    return round(statistics.mean(xs), 4) if xs else None


# --- metrics / seats ------------------------------------------------------------------


def per_power(seats):
    groups = defaultdict(list)
    for s in seats:
        groups[s.power].append(s)
    out = {}
    for power in POWERS.values():
        g = groups.get(power, [])
        out[power] = {
            "n": len(g),
            "score": _mean(s.score for s in g),
            "final_centers": _mean(s.final_centers for s in g if s.final_centers is not None),
            "survival": _mean(float(s.survived) for s in g if s.survived is not None),
            "solo": _mean(float(s.solo) for s in g),
        }
    return out


def target_predicate(policy, slot):
    if slot is not None:
        return lambda s: s.slot == slot
    if policy is not None:
        return lambda s: s.policy == policy
    return lambda s: True


def metrics_report(seats, statuses, policy=None, slot=None, keep_tainted=False):
    is_target = target_predicate(policy, slot)
    all_target = [s for s in seats if is_target(s)]
    taint_counts = Counter(t for s in all_target for t in s.taint)
    dropped = set()
    if not keep_tainted:
        seats, dropped = drop_tainted_episodes(seats, is_target)
    target = [s for s in seats if is_target(s)]
    pooled = policy is None and slot is None
    field = [] if pooled else [s for s in seats if not is_target(s)]
    par = field_par(seats, is_target) if field else {}
    rel = [s.score - par[s.power] for s in target if s.power in par]
    logs = [s.log for s in target if s.log]
    versions = sorted({st["coworld_version"] for st in statuses if st.get("coworld_version")})
    return {
        "policy": policy or (f"slot {slot}" if slot is not None else "all seats"),
        "coworld_versions": versions,
        "episodes": len(statuses),
        "coverage": {
            "missing_results": [st["dir"] for st in statuses if "results" in st["missing"]],
            "missing_replay": [st["dir"] for st in statuses if "replay" in st["missing"]],
            "target_seats": len(all_target),
            "target_seats_without_log": sum(not s.log for s in all_target),
        },
        "taint": {
            "target_seat_flags": dict(sorted(taint_counts.items())),
            "episodes_dropped": len(dropped),
            "kept_tainted": keep_tainted,
        },
        "overall": {
            "n": len(target),
            "score": _mean(s.score for s in target),
            "score_minus_field_par": _mean(rel),
            "final_centers": _mean(s.final_centers for s in target if s.final_centers is not None),
            "survival": _mean(float(s.survived) for s in target if s.survived is not None),
            "solo": _mean(float(s.solo) for s in target),
            "failed_order_rate": _mean(s.orders_failed / s.orders for s in target if s.orders),
            "outcomes": dict(sorted(Counter(f"{s.outcome}/{s.reason}" for s in target).items())),
        },
        "per_power": per_power(target),
        "field_par_per_power": per_power(field) if field else {},
        "telemetry": {
            "seats_with_log": len(logs),
            "rejected_orders": sum(lg.get("rejected", 0) for lg in logs),
            "exceptions": sum(lg.get("exceptions", 0) for lg in logs),
            "http_errors": sum(lg.get("http_errors", 0) for lg in logs),
            "llm_calls": sum(lg.get("llm_calls", 0) for lg in logs),
            "llm_failed_calls": sum(lg.get("llm_failed", 0) for lg in logs),
            "llm_cost_usd": round(sum(lg.get("llm_cost_usd", 0.0) for lg in logs), 4),
            "max_compute_ms": max((lg["max_compute_ms"] for lg in logs if lg.get("max_compute_ms")), default=None),
            "trace": dict(sorted(sum((Counter(lg.get("trace") or {}) for lg in logs), Counter()).items())),
        },
    }


def render_metrics(r):
    o, c, t, tel = r["overall"], r["coverage"], r["taint"], r["telemetry"]
    rel = o["score_minus_field_par"]
    lines = [
        f"# {r['policy']}: {r['episodes']} episodes (webdiplomacy {', '.join(r['coworld_versions']) or 'local'})",
        f"coverage: missing results {len(c['missing_results'])}, missing replay {len(c['missing_replay'])}; "
        f"target seats {c['target_seats']}, without our log {c['target_seats_without_log']}",
        f"taint: {t['target_seat_flags'] or 'none'}; episodes dropped {t['episodes_dropped']}"
        + (" (kept: --keep-tainted)" if t["kept_tainted"] else ""),
        f"overall n={o['n']}: score {o['score']}"
        + (f" (vs field par {rel:+.4f})" if rel is not None else "")
        + f" | final SCs {o['final_centers']} | survival {o['survival']} | solo {o['solo']}",
        f"failed-order rate {o['failed_order_rate']} | outcomes {o['outcomes']}",
        "",
        "| power | n | score | par score | final SCs | par SCs | survival |",
        "|---|---|---|---|---|---|---|",
    ]
    for power, v in r["per_power"].items():
        p = r["field_par_per_power"].get(power, {})
        lines.append(f"| {power} | {v['n']} | {v['score']} | {p.get('score')} | {v['final_centers']} "
                     f"| {p.get('final_centers')} | {v['survival']} |")
    lines += ["", f"telemetry ({tel['seats_with_log']} seat logs): rejected {tel['rejected_orders']}, "
                  f"exceptions {tel['exceptions']}, http errors {tel['http_errors']}, llm calls {tel['llm_calls']} "
                  f"({tel['llm_failed_calls']} failed, ${tel['llm_cost_usd']}), max compute {tel['max_compute_ms']} ms",
              f"trace: {tel['trace']}"]
    return "\n".join(lines)


def cmd_metrics(args):
    seats, statuses = load_dirs([Path(p) for p in args.dirs])
    report = metrics_report(seats, statuses, args.policy, args.slot, args.keep_tainted)
    if not report["coverage"]["target_seats"]:
        print(json.dumps({"error": "no target seats", "policies": sorted({s.policy for s in seats})}))
        return 2
    print(json.dumps(report, indent=1) if args.json else render_metrics(report))
    return 0


def cmd_seats(args):
    seats, _ = load_dirs([Path(p) for p in args.dirs])
    for s in seats:
        if args.policy is None or s.policy == args.policy:
            print(json.dumps(asdict(s)))
    return 0


# --- costs ------------------------------------------------------------------------------


def seat_costs(ep: Path) -> list[dict]:
    seats = []
    for slot, path in sorted(seat_log_paths(ep).items()):
        rows = read_log(path)
        calls = [r for r in rows if r.get("event") == "llm_call"]
        if not calls:
            continue
        movement = {r.get("turn") for r in rows if r.get("event") == "decision" and r.get("phase") == "Diplomacy"}
        wakes = [r for r in rows if r.get("event") == "wake"]

        def tokens(call, key):
            return call.get(key) or (call.get("usage") or {}).get(key) or 0

        seats.append({
            "slot": slot,
            "policy": next((r.get("policy") for r in rows if r.get("policy")), None),
            "calls": len(calls),
            "failed_calls": sum(llm_call_failed(c) for c in calls),
            "prompt_tokens": sum(tokens(c, "prompt_tokens") for c in calls),
            "completion_tokens": sum(tokens(c, "completion_tokens") for c in calls),
            "reasoning_tokens": sum(c.get("reasoning_tokens") or 0 for c in calls),
            "cost_usd": round(sum(llm_call_cost(c) for c in calls), 6),
            "movement_phases": len(movement),
            "wakes": len(wakes),
            "wake_status": dict(sorted(Counter(str(w.get("status")) for w in wakes).items())),
        })
    return seats


def costs_report(dirs: list[Path]) -> dict | None:
    games = []
    for root in dirs:
        for ep in episode_dirs(root):
            seats = seat_costs(ep)
            if seats:
                total = round(sum(x["cost_usd"] for x in seats), 6)
                games.append({"episode": str(ep), "seats": seats, "cost_usd": total})
    if not games:
        return None
    seat_rows = [x for g in games for x in g["seats"]]
    with_phases = [x for x in seat_rows if x["movement_phases"]]
    per_phase = statistics.mean(x["cost_usd"] / x["movement_phases"] for x in with_phases) if with_phases else 0.0
    summary = {
        "games": len(games),
        "llm_seats": len(seat_rows),
        "total_cost_usd": round(sum(g["cost_usd"] for g in games), 4),
        "failed_calls": sum(x["failed_calls"] for x in seat_rows),
        "cost_per_seat_movement_phase_usd": round(per_phase, 5),
        "calls_per_seat_movement_phase": round(statistics.mean(
            x["calls"] / x["movement_phases"] for x in with_phases), 1) if with_phases else None,
        "projected_classic_press_game_usd": {
            "1_llm_seat": round(per_phase * CLASSIC_PRESS_MOVEMENT_PHASES, 4),
            "7_llm_seats": round(7 * per_phase * CLASSIC_PRESS_MOVEMENT_PHASES, 4),
        },
    }
    return {"summary": summary, "games": games}


def cmd_costs(args):
    report = costs_report([Path(d) for d in args.dirs])
    if report is None:
        print("no llm_call events found", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, indent=1))
        return 0
    for g in report["games"]:
        print(g["episode"], f"${g['cost_usd']:.4f}")
        for x in g["seats"]:
            print(f"  slot {x['slot']} {x['policy']}: ${x['cost_usd']:.4f}, {x['calls']} calls "
                  f"({x['failed_calls']} failed), {x['movement_phases']} movement phases, "
                  f"tokens in/out/reasoning {x['prompt_tokens']}/{x['completion_tokens']}/{x['reasoning_tokens']}, "
                  f"wakes {x['wake_status']}")
    print(json.dumps(report["summary"], indent=1))
    return 0


# --- slim -------------------------------------------------------------------------------


def slim_replay(path: Path) -> int:
    """Remove `map` PNGs from every frame; return bytes saved (0 when nothing changed)."""
    raw = path.read_bytes()
    compressed = raw[:2] == b"\x1f\x8b"
    try:
        frames = json.loads(gzip.decompress(raw) if compressed else raw)
    except (ValueError, OSError):
        return 0
    if not isinstance(frames, list) or not any(isinstance(f, dict) and "map" in f for f in frames):
        return 0
    for f in frames:
        if isinstance(f, dict):
            f.pop("map", None)
    data = json.dumps(frames).encode()
    data = gzip.compress(data) if compressed else data
    path.write_bytes(data)
    return len(raw) - len(data)


def cmd_slim(args):
    saved = files = 0
    for root in args.dirs:
        for ep in episode_dirs(Path(root)):
            for name in REPLAY_NAMES:
                if (ep / name).is_file():
                    delta = slim_replay(ep / name)
                    files += delta > 0
                    saved += delta
    print(json.dumps({"replays_slimmed": files, "bytes_saved": saved}))
    return 0


# --- local runs -------------------------------------------------------------------------


class SetupError(Exception):
    pass


def coworld_command() -> list[str]:
    if os.environ.get("COWORLD_CMD"):
        return shlex.split(os.environ["COWORLD_CMD"])
    if shutil.which("coworld"):
        return ["coworld"]
    raise SetupError(
        "the `coworld` CLI is not on PATH. Install it with:\n"
        "    uv tool install coworld\n"
        "    uv tool install softmax-cli\n"
        "or point COWORLD_CMD at a project-local copy, e.g. COWORLD_CMD='uv run coworld'.")


def require_docker():
    if not shutil.which("docker"):
        raise SetupError("Docker is required for local runs and `docker` is not on PATH.")
    if subprocess.call(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL):
        raise SetupError("Docker is installed but the daemon is not reachable (`docker info` failed).")


def image_id(image: str) -> str:
    """Local image ID; fails fast when the tag is missing (another session's prune deletes tags)."""
    result = subprocess.run(["docker", "image", "inspect", "--format", "{{.Id}}", image],
                            capture_output=True, text=True)
    if result.returncode:
        raise SetupError(f"image {image} is not present locally; build or pull it first")
    return result.stdout.strip()


def resolve_manifest(args, cli: list[str]) -> Path:
    if args.manifest:
        path = Path(args.manifest)
        if not path.is_file():
            raise SetupError(f"--manifest {path} does not exist")
        return path.resolve()
    cache = Path(args.cache)
    cache.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([*cli, "download", args.coworld, "--output-dir", str(cache)],
                            capture_output=True, text=True)
    if result.returncode:
        raise SetupError(f"`coworld download {args.coworld}` failed:\n{result.stdout[-2000:]}{result.stderr[-2000:]}")
    for line in result.stdout.splitlines():
        if line.startswith("Manifest:"):
            return Path(line.split(":", 1)[1].strip()).resolve()
    found = sorted(cache.glob("cow_*/coworld_manifest.json"), key=lambda p: p.stat().st_mtime)
    if not found:
        raise SetupError(f"`coworld download` did not leave a manifest under {cache}")
    return found[-1].resolve()


def parse_pairs(pairs: list[str] | None, flag: str) -> dict[str, str]:
    out = {}
    for item in pairs or []:
        key, sep, value = item.partition("=")
        if not sep or not key:
            raise SetupError(f"{flag} expects KEY=VALUE, got {item!r}")
        out[key] = value
    return out


def parse_config(pairs: list[str] | None) -> dict:
    """--config KEY=VALUE; VALUE is parsed as JSON when it parses (numbers, lists, booleans)."""
    out = {}
    for key, value in parse_pairs(pairs, "--config").items():
        try:
            out[key] = json.loads(value)
        except ValueError:
            out[key] = value
    return out


def game_config(manifest: dict, args) -> dict:
    variants = {v["id"]: v for v in manifest["variants"]}
    if args.variant not in variants:
        raise SetupError(f"unknown variant {args.variant!r}; the manifest has {sorted(variants)}")
    config = dict(variants[args.variant]["game_config"])
    config.setdefault("render_maps", bool(args.maps))
    config.update(parse_config(args.config))
    config.pop("seed", None)  # the game draws a fresh random seed per episode; results.json records it
    country = getattr(args, "country", None)
    if country:
        if "countries" not in manifest["game"].get("config_schema", {}).get("properties", {}):
            raise SetupError("--country needs a coworld whose episode config accepts `countries`; "
                             f"{manifest['game'].get('version', 'this version')} does not")
        if country.lower() not in COUNTRY_IDS:
            raise SetupError(f"--country must be one of {sorted(POWERS.values())}")
        first = COUNTRY_IDS[country.lower()]
        # Slots 1-6 are one field policy, so their fixed order does not matter.
        config["countries"] = [first] + [cid for cid in POWERS if cid != first]
    return config


def player_spec(image: str, run: str | None, env: dict[str, str]) -> dict:
    """One seat of the episode request. `run` is a shell-quoted argv string; empty = image entrypoint."""
    return {"type": "player", "image": image, "run": shlex.split(run) if run else [], "env": env}


def bundled_player(manifest: dict, player_id: str) -> dict:
    for p in manifest.get("player") or []:
        if p.get("id") == player_id:
            return {"type": "player", "image": p["image"], "run": p.get("run") or [], "env": p.get("env") or {}}
    known = [p.get("id") for p in manifest.get("player") or []]
    raise SetupError(f"no bundled player {player_id!r}; the manifest has {known}")


class Batch:
    """Runs episodes as `coworld run-episode <manifest> <request.json>` subprocesses, with cleanup."""

    def __init__(self, cli: list[str], manifest_path: Path, out: Path, args):
        self.cli, self.manifest_path, self.out, self.args = cli, manifest_path, out.resolve(), args
        self.processes: set[subprocess.Popen] = set()
        self.lock = threading.Lock()
        self.stopping = threading.Event()

    def run_one(self, request_path: Path, episode_dir: Path, seating: list[str]) -> int:
        cmd = [*self.cli, "run-episode", str(self.manifest_path), str(request_path),
               "--output-dir", str(episode_dir), "--timeout-seconds", str(self.args.timeout_seconds)]
        if self.args.use_llm:
            cmd.append("--use-llm")
        cmd += [f"--secret-env={kv}" for kv in self.args.secret_env or []]
        env = {**os.environ, "DOCKER_DEFAULT_PLATFORM": "linux/amd64"}
        code = 1
        for attempt in range(self.args.attempts):
            if self.stopping.is_set():
                return 130
            if episode_dir.exists():
                shutil.rmtree(episode_dir)
            episode_dir.mkdir(parents=True)
            (episode_dir / "seating.json").write_text(json.dumps(seating))
            with open(episode_dir.parent / f"{episode_dir.name}.run.log", "w") as log:
                process = subprocess.Popen(cmd, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                with self.lock:
                    self.processes.add(process)
                code = process.wait()
                with self.lock:
                    self.processes.discard(process)
            if (episode_dir / "results.json").exists():
                return code
            if self.stopping.is_set():
                return 130
            print(f"{episode_dir.name}: no results.json (exit {code}), attempt {attempt + 1}/{self.args.attempts}",
                  file=sys.stderr)
        return code or 1

    def stop(self):
        """Interrupt every running episode, then remove containers still bound to this batch."""
        self.stopping.set()
        with self.lock:
            running = list(self.processes)
        for process in running:
            try:
                os.killpg(process.pid, signal.SIGINT)  # the CLI removes its own containers on SIGINT
            except ProcessLookupError:
                pass
        for process in running:
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
        remove_batch_containers(self.out)


def remove_batch_containers(out: Path) -> int:
    """Remove game and player containers of episodes whose workspace is under `out`.

    `coworld run-episode` names containers `coworld-run-game-<run_id>` and
    `coworld-run-player-<run_id>-<slot>` and bind-mounts the episode directory into
    the game container, so the mount source identifies which run IDs are ours."""
    listing = subprocess.run(["docker", "ps", "-a", "--filter", "name=coworld-run-game-", "--format", "{{.Names}}"],
                             capture_output=True, text=True).stdout.split()
    removed = 0
    for name in listing:
        mounts = subprocess.run(["docker", "inspect", "--format", "{{range .Mounts}}{{.Source}}\n{{end}}", name],
                                capture_output=True, text=True).stdout.split()
        if not any(Path(m).resolve().is_relative_to(out) for m in mounts if m):
            continue
        run_id = name.removeprefix("coworld-run-game-")
        ids = subprocess.run(["docker", "ps", "-aq", "--filter", f"name={run_id}"],
                             capture_output=True, text=True).stdout.split()
        if ids:
            subprocess.call(["docker", "rm", "-f", *ids], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            removed += len(ids)
    if removed:
        print(f"removed {removed} leftover containers", file=sys.stderr)
    return removed


def raise_keyboard_interrupt(signum, frame):
    """Treat SIGTERM like Ctrl-C so the batch cleans up its containers."""
    raise KeyboardInterrupt


def run_batch(args, players: list[dict], seating: list[str], images: list[str]) -> int:
    cli = coworld_command()
    require_docker()
    image_ids = {image: image_id(image) for image in dict.fromkeys(images)}
    manifest_path = resolve_manifest(args, cli)
    manifest = json.loads(manifest_path.read_text())
    config = game_config(manifest, args)
    if args.use_llm and not (os.environ.get("COWORLD_LLM_ENDPOINT") or os.environ.get("OPENROUTER_API_KEY")):
        raise SetupError("--use-llm needs COWORLD_LLM_ENDPOINT (run llm_sidecar_local.py) in the environment")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    request_path = out / "episode_request.json"
    request_path.write_text(json.dumps({"manifest": manifest, "game_config": config, "players": players}))
    (out / "run.json").write_text(json.dumps({
        "manifest": str(manifest_path), "coworld_version": manifest.get("game", {}).get("version"),
        "variant": args.variant, "game_config": config, "seating": seating, "image_ids": image_ids,
        "players": [{k: v for k, v in p.items() if k != "env"} | {"env_keys": sorted(p["env"])} for p in players],
    }, indent=1))

    batch = Batch(cli, manifest_path, out, args)
    dirs = [out / f"ep-{uuid.uuid4().hex[:10]}" for _ in range(args.episodes)]
    previous = signal.signal(signal.SIGTERM, raise_keyboard_interrupt)
    pool = ThreadPoolExecutor(args.parallel)
    try:
        codes = list(pool.map(lambda d: batch.run_one(request_path, d, seating), dirs))
    except KeyboardInterrupt:
        print("interrupted: stopping episodes and removing their containers", file=sys.stderr)
        batch.stop()
        pool.shutdown(wait=True, cancel_futures=True)
        return 130
    finally:
        signal.signal(signal.SIGTERM, previous)
    pool.shutdown()
    failed = sum(not (d / "results.json").exists() for d in dirs)
    print(json.dumps({"out": str(out), "episodes": len(dirs), "failed": failed,
                      "exit_codes": dict(Counter(codes))}))
    return 0 if not failed else 1


def cmd_local(args):
    players = [player_spec(args.image, args.run, parse_pairs(args.env, "--env"))] * 7
    return run_batch(args, players, [args.label] * 7, [args.image])


def cmd_arena(args):
    candidate = player_spec(args.image, args.candidate_run, parse_pairs(args.candidate_env, "--candidate-env"))
    images = [args.image]
    if args.field_player:
        if args.field_image or args.field_run or args.field_env:
            raise SetupError("--field-player cannot be combined with --field-image/--field-run/--field-env")
        field = None  # resolved from the manifest inside run_batch's manifest load below
    else:
        field_image = args.field_image or args.image
        images.append(field_image)
        field_env = parse_pairs(args.field_env, "--field-env")
        if not (args.field_image or args.field_run or args.field_env):
            field_env = dict(DEFAULT_FIELD_ENV)
        field = player_spec(field_image, args.field_run, field_env)
    if field is None:
        cli = coworld_command()
        args.manifest = str(resolve_manifest(args, cli))
        field = bundled_player(json.loads(Path(args.manifest).read_text()), args.field_player)
    return run_batch(args, [candidate] + [field] * 6, [args.candidate_label] + [args.field_label] * 6, images)


def add_run_options(p):
    p.add_argument("--variant", default="classic-gunboat", help="manifest variant id (default classic-gunboat)")
    p.add_argument("--episodes", type=int, default=1)
    p.add_argument("--parallel", type=int, default=2, help="episodes run at once (each is 8 containers)")
    p.add_argument("--out", required=True, help="output directory; one ep-<id>/ per episode")
    p.add_argument("--config", action="append", metavar="KEY=VALUE",
                   help="game_config override, JSON-parsed value (e.g. end_year=1904)")
    p.add_argument("--maps", action="store_true", help="render map PNGs into the replay (large)")
    p.add_argument("--use-llm", action="store_true", help="forward the host's COWORLD_LLM_ENDPOINT into the seats")
    p.add_argument("--secret-env", action="append", metavar="KEY=VALUE", help="secret env for every seat")
    p.add_argument("--attempts", type=int, default=3, help="tries per episode when no results.json appears")
    p.add_argument("--timeout-seconds", type=float, default=6000)
    p.add_argument("--manifest", help="coworld_manifest.json to use instead of downloading")
    p.add_argument("--coworld", default="webdiplomacy",
                   help="coworld name or cow_<id> to download (default webdiplomacy)")
    p.add_argument("--cache", default=os.environ.get("WEBDIP_COWORLD_CACHE", ".runtime/coworld"),
                   help="download cache (default .runtime/coworld, or $WEBDIP_COWORLD_CACHE)")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("metrics", help="per-power score vs same-batch field par, coverage, telemetry")
    m.add_argument("dirs", nargs="+")
    m.add_argument("--policy", help="target policy NAME:vN (hosted) or seating label (local)")
    m.add_argument("--slot", type=int, help="target slot instead of a policy")
    m.add_argument("--keep-tainted", action="store_true", help="do not drop tainted episodes")
    m.add_argument("--json", action="store_true")
    m.set_defaults(func=cmd_metrics)

    s = sub.add_parser("seats", help="one JSON row per seat")
    s.add_argument("dirs", nargs="+")
    s.add_argument("--policy")
    s.set_defaults(func=cmd_seats)

    c = sub.add_parser("costs", help="LLM spend from our seat logs")
    c.add_argument("dirs", nargs="+")
    c.add_argument("--json", action="store_true")
    c.set_defaults(func=cmd_costs)

    lo = sub.add_parser("local", help="local episodes, one image in every seat (needs Docker)")
    lo.add_argument("--image", required=True)
    lo.add_argument("--run", metavar="ARGV", help="shell-quoted argv for every seat (default: image entrypoint)")
    lo.add_argument("--env", action="append", metavar="KEY=VALUE", help="public env for every seat")
    lo.add_argument("--label", default="local", help="seating label for every seat (default local)")
    add_run_options(lo)
    lo.set_defaults(func=cmd_local)

    ar = sub.add_parser("arena", help="slot 0 candidate vs a six-seat field (needs Docker)")
    ar.add_argument("--image", required=True, help="candidate image (and the field's unless --field-image)")
    ar.add_argument("--candidate-run", metavar="ARGV", help="candidate argv, shell-quoted (default: image entrypoint)")
    ar.add_argument("--candidate-env", action="append", metavar="KEY=VALUE", help="candidate public env")
    ar.add_argument("--candidate-label", default="candidate")
    ar.add_argument("--field-image", help="field image (default: --image)")
    ar.add_argument("--field-run", metavar="ARGV", help="field argv, shell-quoted (default: image entrypoint)")
    ar.add_argument("--field-env", action="append", metavar="KEY=VALUE",
                    help="field public env (default with no field options: CASTLEREAGH_POLICY=search)")
    ar.add_argument("--field-player", help="use a player bundled with the game as the field (e.g. random, hold)")
    ar.add_argument("--field-label", default="field")
    ar.add_argument("--country", help="pin slot 0 to this power (e.g. France); default: shuffled per episode")
    add_run_options(ar)
    ar.set_defaults(func=cmd_arena, episodes=8)

    sl = sub.add_parser("slim", help="drop map PNGs from replays under DIRs")
    sl.add_argument("dirs", nargs="+")
    sl.set_defaults(func=cmd_slim)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except SetupError as error:
        print(f"wd.py {args.cmd}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
