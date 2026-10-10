"""Castlereagh: the launcher's child process (`python -m castlereagh`).

Mode, from env CASTLEREAGH_POLICY (baked at build time by `--build-arg POLICY=...`):
- `search` (default): the Default search (the lab's Kissinger), no press. Every phase:
  read context and public files, choose, save with Ready, diff the saved orders against
  the request (upstream silently drops invalid ones), and print one `decision` line.
- `press`: the same search core plus the optional press layer (press/player.py).
Any other value is an error.

Every log line is one JSON object on stdout with `policy` and `event` fields. The seat
log's schema (decision, exception, llm_call, tool_call, wake, workspace, ...) is what the
lab's analysis tools parse; keep field names stable.
"""

import json
import os
import random
import time
import traceback
from urllib.error import HTTPError, URLError

from castlereagh import config
from castlereagh.search import SearchBot
from castlereagh.webdip_api import WebDiplomacy, order_difference

MODES = ("search", "press")


def policy_mode():
    mode = os.environ.get("CASTLEREAGH_POLICY", "search").strip() or "search"
    if mode not in MODES:
        raise SystemExit(f"CASTLEREAGH_POLICY={mode!r} is not a mode; use one of: {', '.join(MODES)}")
    return mode


def apply_overrides(text):
    """`KEY=VAL,KEY=VAL` config overrides (CASTLEREAGH_OVERRIDES), for local experiments.

    Values convert to the existing value's type; list values are JSON (one list per override)."""
    for item in filter(None, (part.strip() for part in text.split(","))):
        key, value = item.split("=", 1)
        current = getattr(config, key)  # AttributeError = unknown knob: fail loudly
        if current is None or isinstance(current, str):
            value = None if value == "None" else value
        elif isinstance(current, list):
            value = json.loads(value)
        else:
            value = type(current)(value)
        setattr(config, key, value)


def phase_rng_key(seed, country, turn, phase):
    """The per-phase RNG seed string. The press floor reuses it so it plays exactly like `search`."""
    return f"{seed}:{country}:{turn}:{phase}"


def make_logger(policy):
    def log(**fields):
        print(json.dumps({"policy": policy, "t": round(time.time(), 1), **fields}), flush=True)
    return log


def play_phase(api, context, seed, policy, cls, state, log):
    """Gunboat path for one phase. Returns False if the phase changed while reading it."""
    game = context["game"]
    board = api.file(context["files"]["game"])
    if (board["turn"], board["phase"]) != (game["turn"], game["phase"]):
        return False  # The phase changed while reading its public file.
    variant = state.get("variant") or api.file(context["files"]["variant"])
    state["variant"] = variant
    started = time.monotonic()
    rng = random.Random(phase_rng_key(seed, api.country_id, game["turn"], game["phase"]))
    bot = cls(variant, board, api.country_id, game["phase"], int(game["turn"]), rng)
    bot.observe(api, context, state)
    slots = context["orders"]["orders"]
    requested = bot.choose(slots)
    compute_ms = round((time.monotonic() - started) * 1000, 1)
    saved = api.orders(context, requested) if requested else []
    latest = api.context()["game"]
    if (latest["turn"], latest["phase"]) != (game["turn"], game["phase"]):
        return True  # Phase advanced already; our saved orders were adjudicated.
    try:
        difference = order_difference(requested, saved, len(slots)) if requested else {"missing": [], "unexpected": []}
    except (TypeError, ValueError, KeyError):
        # Upstream can echo a saved build/destroy with a null territory; the orders are saved,
        # only the comparison fails. Record it instead of losing the decision log.
        difference = {"missing": [], "unexpected": [], "diff_error": True}
    log(
        event="decision",
        turn=int(game["turn"]),
        phase=game["phase"],
        country=api.country_id,
        units=len(slots),
        centers=bot.b.centers[api.country_id],
        compute_ms=compute_ms,
        trace=dict(bot.trace),
        rejected=len(difference["missing"]),
        difference=difference if any(difference.values()) else None,
    )
    # Snapshot every phase: the launcher kills the bot at game end, so nothing is written later.
    memory = state.get("search", {})
    log(event="workspace", turn=int(game["turn"]), phase=game["phase"],
        beliefs={k: round(v, 2) for k, v in memory.get("logodds", {}).items()},
        hostility={k: round(v, 2) for k, v in memory.get("hostility", {}).items()})
    return True


class GunboatPlayer:
    """CASTLEREAGH_POLICY=search: the Default search in every phase."""

    def __init__(self, policy, api, seed, log):
        self.policy, self.api, self.seed, self.log = policy, api, seed, log
        self.state = {}

    def play(self, context, play_phase):
        return play_phase(self.api, context, self.seed, self.policy, SearchBot, self.state, self.log)

    def finish(self):
        pass


def main():
    mode = policy_mode()
    apply_overrides(os.environ.get("CASTLEREAGH_OVERRIDES", ""))
    policy = f"castlereagh-{mode}"
    log = make_logger(policy)
    api = WebDiplomacy(
        os.environ["WEBDIP_URL"],
        os.environ["WEBDIP_API_KEY"],
        os.environ["WEBDIP_GAME_ID"],
        os.environ["WEBDIP_COUNTRY_ID"],
    )
    seed = int(os.environ.get("WEBDIP_SEED", "0"))
    log(event="start", mode=mode, country=api.country_id, seed=seed,
        end_year=os.environ.get("WEBDIP_END_YEAR"), scoring=os.environ.get("WEBDIP_SCORING"),
        overrides=os.environ.get("CASTLEREAGH_OVERRIDES") or None)
    if mode == "press":
        from castlereagh.press.player import PressPlayer

        player = PressPlayer(policy, api, seed, log)
    else:
        player = GunboatPlayer(policy, api, seed, log)
    previous = None
    while True:
        phase = None
        try:
            context = api.context()
            game = context["game"]
            phase = (game["turn"], game["phase"])
            if game["phase"] == "Finished":
                player.finish()
                log(event="finished")
                return
            if game["phase"] != "Pre-game" and phase != previous and context.get("orders"):
                if player.play(context, play_phase):
                    previous = phase
        except HTTPError as error:
            if error.code == 404:
                player.finish()
                return  # Upstream erases cancelled games.
            log(event="http_error", code=error.code)
        except (URLError, TimeoutError):
            pass
        except Exception as error:  # A crashed child leaves the seat silent for the rest of the game.
            log(event="exception", error=repr(error)[:300], where=traceback.format_exc()[-1200:])
            previous = phase
        time.sleep(0.2)
