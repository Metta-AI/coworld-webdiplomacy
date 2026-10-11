"""Every fetched episode, for the replay browser and viewer.

Two things live here:

1. The index (`index()`): one row per episode directory under `paths.artifacts_dir()`.
   The episode id is the directory name. A row is built in two steps so the browser page
   stays fast with hundreds of games:
   - the basic row reads only `results.json` and `episode.json` (a few kB): seats, scores,
     final centres, outcome, variant, date, source, which seats have a log. It is cached in
     memory and rebuilt when one of those files changes.
   - the deep row needs the replay (about 10 MB) and our seat logs (1 to 3 MB each), about a
     tenth of a second a game: per-seat log taint and centres by year, which the
     `flag_episodes.py` criteria need. A background thread fills these in and saves them to
     `.runtime/ide/episode_index.json`, so the cost is paid once per episode. The parsing itself
     is `reader.each_game`: worker processes for a large batch, and one parse of a game shared
     with the dashboard.
2. The viewer's data (`load_view()`): one compact JSON object per episode (about 150 kB)
   taken from the replay's last frame, plus the chosen seat's private press and `decision`
   lines, plus the press audit when one exists. The raw replay never goes to the browser.

Parsing is the lab's: `webdip_episodes.py` (results, replay, logs), `press_audit.py`
(messages, the audit) and `flag_episodes.py` (what makes a game worth opening).
"""

from __future__ import annotations

import importlib
import json
import re
import threading
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import paths, reader, store

PARITY = 1 / 7  # the score of an average seat in a seven-seat game
PACIFIC = ZoneInfo("America/Los_Angeles")
SWING = 3  # supply centres gained or lost in one year that earn a timeline marker
PHASE_LABELS = {"Diplomacy": "Movement", "Finished": "Final"}
PHASE_ORDER = {"Pre-game": 0, "Diplomacy": 1, "Retreats": 2, "Builds": 3, "Finished": 4}
# Audit categories worth a marker on the timeline. These are `press_audit.FLAGGED`; every other
# category (there are many, and more are added) is shown on its claim and nowhere else. The words
# for all of them are the lab's: `press_report.WORDS` and `press_report.verdict`.
AUDIT_MARKERS = ("betrayed", "deceived", "doubted_wrongly", "we_broke_our_word")
# flag_episodes.py's per-game flags, with the short names the table shows.
FLAG_WORDS = {
    "crash or dropped orders": "crash or dropped orders",
    "opponent solo": "solo",
    "eliminated early": "out early",
    "swing of 3+ centres in a year": "swing",
}
DECISION_DROP = ("policy", "t", "event", "country", "turn", "phase")  # shown elsewhere or noise


def tool(name: str):
    """A module from the lab's `tools/` folder (`webdip_episodes`, `press_audit`, `flag_episodes`)."""
    paths.use_lab_tools()
    return importlib.import_module(name)


def turn_label(turn: int) -> str:
    return f"{'Spring' if turn % 2 == 0 else 'Autumn'} {1901 + turn // 2}"


def phase_label(turn: int, phase: str) -> str:
    return f"{turn_label(turn)} · {PHASE_LABELS.get(phase, phase)}"


# ---------- the index ----------

# Request handlers run in a thread pool and the deep pass in its own thread, so everything
# below that is shared is touched only under `_lock`.
_lock = threading.Lock()
_basic: dict[str, tuple[tuple, dict]] = {}  # episode dir -> (file stamp, row)
_audit_slots: dict[str, tuple[float, int | None]] = {}  # episode id -> (audit.json mtime, its slot); under `_lock`
_deep: dict[str, dict] = {}  # episode dir -> {"stamp": [...], "seats": [...]}, or {"stamp", "seats": [], "error"}
_deep_loaded_from: Path | None = None
_worker: threading.Thread | None = None
_save_lock = threading.Lock()  # one writer of the saved deep rows at a time


def _mtime(path: Path | None) -> float:
    try:
        return path.stat().st_mtime if path else 0.0
    except OSError:
        return 0.0


def _epoch(text: str | None) -> float | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _is_press(episode: dict, results: dict) -> bool | None:
    """True for a press game, False for gunboat, None when the files do not say."""
    press = (episode.get("game_config") or {}).get("press")
    if press is not None:
        return press != "NoPress"
    name = (episode.get("variant_name") or "").lower()
    if "gunboat" in name:
        return False
    return True if "press" in name else None


def _source(ep: Path, episode: dict) -> str:
    """`webdip_episodes.episode_source`'s rule, for a lab whose loader does not have it yet."""
    if not episode:
        return "local"
    if episode.get("round_id") or any(p.name.startswith("league-") for p in ep.resolve().parents):
        return "league"
    return "xp"


def _basic_row(ep: Path) -> dict:
    """One episode from `results.json` and `episode.json` only (no replay, no logs)."""
    we = tool("webdip_episodes")
    episode = we.read_json_file(ep / "episode.json") if (ep / "episode.json").exists() else {}
    results_path = we.first_existing(ep, we.RESULTS_NAMES)
    results = we.read_json_file(results_path) if results_path else {}
    outcome = results.get("outcome", "")
    status = episode.get("status", "local")
    taint = we.episode_taint(status, results)
    if not results_path:
        taint.append("no_results")

    policies = we.seat_policies(ep, episode)
    logged = we.seat_log_paths(ep)
    members = {int(m["countryID"]): m for m in results.get("members") or []}
    final_year = we.final_year_of(results)
    scores = results.get("scores") or []
    seats = []
    for slot, country in enumerate(results.get("countries") or []):
        member = members.get(int(country), {})
        finals = int(member["supplyCenterNo"]) if member.get("supplyCenterNo") is not None else None
        seat = we.Seat(
            episode_id=ep.name,
            slot=slot,
            policy=policies.get(slot, "local"),
            power=we.POWERS[int(country)],
            score=float(scores[slot]) if slot < len(scores) and scores[slot] is not None else 0.0,
            final_centers=finals,
            survived=(finals > 0) if finals is not None else None,
            solo=outcome == "won" and (finals or 0) >= we.SOLO_CENTERS,
            outcome=outcome,
            reason=results.get("reason", ""),
            final_year=final_year,
            taint=list(taint),
        )
        seats.append({**asdict(seat), "country": int(country), "has_log": slot in logged})

    relative = ep.relative_to(paths.artifacts_dir()).parts
    source = getattr(we, "episode_source", None)
    transitions = results.get("transitions") or []
    when = (
        _epoch(episode.get("completed_at") or episode.get("created_at"))
        or (transitions[-1].get("unix_time") if transitions else None)
        or _mtime(results_path or ep)
    )
    return {
        "id": ep.name,
        "dir": str(ep),
        "batch": relative[0] if len(relative) > 1 else "",
        "request": episode.get("experience_request_id") or "",
        "source": source(ep) if source else _source(ep, episode),
        "variant": episode.get("variant_name") or "local run",
        "variant_id": tool("matchups").variant_of(ep),  # the dashboard's name for it, so its links can filter here
        "press": _is_press(episode, results),
        "coworld_version": episode.get("coworld_version"),
        "status": status,
        "time": when,
        "date": datetime.fromtimestamp(when, PACIFIC).strftime("%Y-%m-%d %H:%M"),
        "outcome": outcome or ("no results" if not results_path else ""),
        "reason": results.get("reason", ""),
        "final_year": final_year,
        "taint": taint,
        "has_replay": we.first_existing(ep, we.REPLAY_NAMES) is not None,
        "seats": seats,
    }


def _basic_stamp(ep: Path) -> tuple:
    return (_mtime(ep), _mtime(ep / "results.json"), _mtime(ep / "episode.json"), _mtime(ep / "policy-logs"))


def _deep_stamp(ep: Path) -> list[list]:
    """Changes when any file the loader reads for this episode changes: `reader.fingerprint`, as JSON keeps it."""
    return [list(item) for item in reader.fingerprint(ep)]


def _deep_cache_path() -> Path:
    return paths.state_dir() / "episode_index.json"


def _load_deep_cache() -> None:
    """Read the saved deep rows once per lab directory."""
    global _deep_loaded_from
    path = _deep_cache_path()
    with _lock:
        if _deep_loaded_from == path:
            return
        _deep.clear()
        if path.exists():
            try:
                _deep.update(json.loads(path.read_text()))
            except ValueError:
                pass  # a half-written cache: rebuild it
        _deep_loaded_from = path


def _fill_deep(missing: dict[Path, list]) -> None:
    """The loader's full per-seat records for each episode (`reader` reads the replay and the seat logs)."""
    done = 0
    for ep, game, error in reader.each_game(missing):
        # The stamp from before the read: a file that changed meanwhile is then read again.
        row = {"stamp": missing[ep], "seats": [asdict(seat) for seat in game.seats] if game else []}
        if error:  # one unreadable game must not stop the index
            row["error"] = error
        with _lock:
            _deep[str(ep)] = row
        done += 1
        if done % 20 == 0:
            _save_deep()
    _save_deep()


def _save_deep() -> None:
    """Save the deep rows. A game that could not be read is left out, so the next server start tries it again."""
    with _save_lock:
        with _lock:
            text = json.dumps({key: row for key, row in _deep.items() if not row.get("error")})
        path = _deep_cache_path()
        scratch = path.with_name(path.name + ".tmp")
        scratch.write_text(text)
        scratch.replace(path)


def _deep_missing(dirs: list[Path]) -> dict[Path, list]:
    """The episodes with no deep row for their files as they are now, each with its stamp."""
    stamps = {ep: _deep_stamp(ep) for ep in dirs}
    with _lock:
        return {ep: stamp for ep, stamp in stamps.items() if (_deep.get(str(ep)) or {}).get("stamp") != stamp}


def deepen(wait: bool = False) -> tuple[int, int]:
    """Start (or, with `wait`, run) the deep pass. Returns (episodes done, episodes in all)."""
    global _worker
    dirs = episode_dirs()
    _load_deep_cache()
    missing = _deep_missing(dirs)
    if missing and wait:
        _fill_deep(missing)
        missing = {}
    elif missing:
        with _lock:  # two pages asked for at once must not start two readers
            if not (_worker and _worker.is_alive()):
                _worker = threading.Thread(target=_fill_deep, args=(missing,), daemon=True, name="episode-index")
                _worker.start()
    return len(dirs) - len(missing), len(dirs)


def episode_dirs() -> list[Path]:
    root = paths.artifacts_dir()
    return tool("webdip_episodes").episode_dirs(root) if root.is_dir() else []


def index() -> list[dict]:
    """Every episode, newest first. Rows are fresh dicts; the caller may add to them."""
    _load_deep_cache()
    notes = {episode: len(rows) for episode, rows in store.all_annotations().items()}
    press_dir = paths.press_dir()
    rows = []
    seen = set()
    for ep in episode_dirs():
        if ep.name in seen:  # the same episode fetched into two batches: keep the first
            continue
        seen.add(ep.name)
        stamp = _basic_stamp(ep)
        cached = _basic.get(str(ep))
        if cached is None or cached[0] != stamp:
            try:
                cached = (stamp, _basic_row(ep))
            except Exception as error:  # a broken directory still gets a row, so it can be found
                cached = (stamp, _broken_row(ep, error))
            _basic[str(ep)] = cached
        row = dict(cached[1])
        with _lock:
            deep = _deep.get(str(ep))
        row["indexed"] = bool(deep)
        row["index_error"] = (deep or {}).get("error")  # the replay or a seat log could not be read
        if deep and deep.get("seats"):
            row["seats"] = _merge_deep(row["seats"], deep["seats"])
        row["audit"] = (press_dir / ep.name / "audit.json").exists()
        # An audit is one seat's: in a game with two of our seats only that seat's row is "audited".
        row["audit_slot"] = audit_slot(ep.name) if row["audit"] else None
        row["annotations"] = notes.get(ep.name, 0)
        rows.append(row)
    rows.sort(key=lambda r: r["time"], reverse=True)
    return rows


def _broken_row(ep: Path, error: Exception) -> dict:
    when = _mtime(ep)
    return {
        "id": ep.name, "dir": str(ep), "batch": "", "request": "", "source": "local", "variant": "unreadable",
        "variant_id": "unknown",
        "press": None, "coworld_version": None, "status": "unreadable", "time": when,
        "date": datetime.fromtimestamp(when, PACIFIC).strftime("%Y-%m-%d %H:%M"),
        "outcome": f"unreadable: {type(error).__name__}", "reason": "", "final_year": None,
        "taint": ["unreadable"], "has_replay": False, "seats": [],
    }  # fmt: skip


def _merge_deep(basic: list[dict], deep: list[dict]) -> list[dict]:
    """The loader's seat records (log taint, centres by year) over the basic ones."""
    by_slot = {seat["slot"]: seat for seat in deep}
    merged = []
    for seat in basic:
        full = by_slot.get(seat["slot"])
        if full:
            years = {int(year): count for year, count in (full.get("centers_by_year") or {}).items()}
            seat = {**seat, **full, "centers_by_year": years}
        merged.append(seat)
    return merged


def find(episode: str) -> dict | None:
    return next((row for row in index() if row["id"] == episode), None)


def policy_name(policy: str) -> str:
    """'my-policy:v6' -> 'my-policy'."""
    return policy.rsplit(":v", 1)[0]


def matches_policy(seat_policy: str, wanted: str) -> bool:
    """`wanted` is a full label (`name:vN`) or a bare policy name (every version)."""
    return seat_policy == wanted or (":v" not in wanted and policy_name(seat_policy) == wanted)


def followed_seats(row: dict, policy: str | None = None) -> tuple[list[dict], bool]:
    """The seats this row is "about", and whether that was a guess.

    With `policy`: that policy's seats. Without: the seats that have a log (rivals' hosted logs
    are private, so a log normally marks our seat). When every seat has a log (one player owns
    the whole table) that says nothing, and the first seat's policy is followed as a guess.
    """
    seats = row["seats"]
    if policy:
        return [s for s in seats if matches_policy(s["policy"], policy)], False
    logged = [s for s in seats if s["has_log"]]
    if logged and len(logged) < len(seats):
        return logged, False
    if not seats:
        return [], False
    first = seats[0]["policy"]
    return [s for s in seats if s["policy"] == first], True


def flags(row: dict, seat: dict) -> list[str]:
    """`flag_episodes.py`'s per-game criteria for one of our seats, as short phrases."""
    found = tool("flag_episodes").seat_flags(row["seats"], seat["policy"])[2]
    mine = [f for f in found if f["power"] == seat["power"]]
    # Grouped in FLAG_WORDS order, the order the table has always shown.
    return [f"{short}: {f['detail'].replace(' -> ', '\u2192')}"
            for name, short in FLAG_WORDS.items() for f in mine if f["flag"] == name]


# ---------- the viewer's data ----------

_views: dict[tuple, tuple[tuple, dict]] = {}  # (episode dir, slot) -> (file stamp, view); guarded by `_lock`
MAX_VIEWS = 12


def audit_path(episode: str) -> Path:
    return paths.press_dir() / episode / "audit.json"


def audit_stamp(episode: str) -> float:
    """Changes when the audit appears or is rewritten; the page polls this."""
    return _mtime(audit_path(episode))


def audit_slot(episode: str) -> int | None:
    """The seat a game's press audit is for (`audit.json` records one `slot`). None without an
    audit, or with one that cannot be read. Read once per version of the file."""
    stamp = audit_stamp(episode)
    if not stamp:
        return None
    with _lock:
        cached = _audit_slots.get(episode)
    if cached and cached[0] == stamp:
        return cached[1]
    try:
        slot = int(json.loads(audit_path(episode).read_text())["slot"])
    except (ValueError, KeyError, TypeError, OSError):
        slot = None  # half-written or damaged: the viewer says so when the game is opened
    with _lock:
        _audit_slots[episode] = (stamp, slot)
    return slot


def default_seat(row: dict) -> int | None:
    """The seat the viewer follows when the link names none: the audit's, else a followed seat."""
    audited = audit_slot(row["id"])
    if audited is not None:
        return audited
    seats, _ = followed_seats(row)
    logged = [s for s in seats if s["has_log"]]
    return logged[0]["slot"] if logged else None


def load_view(row: dict, slot: int | None) -> dict:
    """Everything the viewer draws for one episode, seen from seat `slot` (None: public only)."""
    we = tool("webdip_episodes")
    ep = Path(row["dir"])
    replay_path = we.first_existing(ep, we.REPLAY_NAMES)
    log_path = we.seat_log_paths(ep).get(slot) if slot is not None else None
    stamp = (_mtime(replay_path), _mtime(log_path), audit_stamp(row["id"]), _mtime(ep / "results.json"))
    key = (row["dir"], slot)
    with _lock:
        cached = _views.get(key)
    if cached and cached[0] == stamp:
        return cached[1]
    view = _build_view(row, slot, replay_path, log_path)
    with _lock:
        _views.pop(key, None)
        if len(_views) >= MAX_VIEWS:
            _views.pop(next(iter(_views)))
        _views[key] = (stamp, view)
    return view


def _build_view(row: dict, slot: int | None, replay_path: Path | None, log_path: Path | None) -> dict:
    we, pa = tool("webdip_episodes"), tool("press_audit")
    problems = []
    replay, last, territories, phases, public = None, {}, {}, [], []
    if replay_path is None:
        problems.append("This game has no replay file.")
    else:
        # A replay is a downloaded file: it may be cut short (a gzip that ends early is an
        # EOFError), half-written, or not a replay at all. The page then says so and shows the
        # rest (results, press from the seat log, notes).
        try:
            replay = we.read_json_file(replay_path)
            if not isinstance(replay, list) or not all(isinstance(frame, dict) for frame in replay):
                raise ValueError("not a list of frames")
            last = replay[-1] if replay else {}
            territories = _territories(last.get("variant") or {}, pa.ABBREVIATION)
            supply = {tid for tid, t in territories.items() if t["supply"]}
            phases = [_phase(i, ph, supply) for i, ph in enumerate((last.get("history") or {}).get("phases") or [])]
            public = pa.public_press(replay)
        except Exception as error:  # noqa: BLE001
            problems.append(f"The replay could not be read ({type(error).__name__}).")
            replay, last, territories, phases, public = None, {}, {}, [], []
    if replay and not any(t["x"] is not None for t in territories.values()):
        problems.append("This replay has no map coordinates, so the map is not drawn. Orders are listed below.")

    finals = {seat["country"]: seat["final_centers"] for seat in row["seats"]}
    if phases and phases[-1]["phase"] == "Finished" and all(v is not None for v in finals.values()) and finals:
        # The Finished entry shows ownership from before the last autumn; results.json has the truth.
        phases[-1]["sc"] = {str(country): count for country, count in finals.items()}
        phases[-1]["stale_board"] = True

    seat = next((s for s in row["seats"] if s["slot"] == slot), None)
    rows = we.read_log(log_path) if log_path else []
    our_power = seat["power"].upper() if seat else ""
    messages = _messages(pa, public, rows, our_power, phases)
    audit = _audit(row["id"], slot, messages, phases)

    return {
        "episode": {k: row[k] for k in ("id", "batch", "request", "source", "variant", "press", "date", "status",
                                        "outcome", "reason", "final_year", "taint", "coworld_version")},
        "seats": [
            {k: s.get(k) for k in ("slot", "country", "power", "policy", "score", "final_centers", "solo",
                                   "has_log", "taint")}
            for s in row["seats"]
        ],
        "seat": slot if seat else None,
        "our_power": our_power or None,
        "powers": {str(c["countryID"]): c["name"] for c in (last.get("variant") or {}).get("countries") or []}
        or {str(k): v for k, v in we.POWERS.items()},
        "territories": {str(tid): t for tid, t in territories.items()},
        "phases": phases,
        "messages": messages,
        "decisions": _decisions(rows, phases),
        "audit": audit,
        "events": _events(phases, row) + (audit or {}).get("markers", []),
        "problems": problems,
    }  # fmt: skip


def _territories(variant: dict, abbreviation: dict) -> dict[int, dict]:
    out = {}
    for t in variant.get("territories") or []:
        out[t["id"]] = {
            "name": t["name"],
            "abbr": abbreviation.get(t["name"], t["name"][:3].upper()),
            "x": t.get("smallMapX"),
            "y": t.get("smallMapY"),
            # A coast of Spain, St. Petersburg or Bulgaria is a place for fleets, not a second centre.
            "supply": bool(t.get("supply")) and t.get("coast") != "Child",
            "parent": t.get("coastParentID") or t["id"],
            "sea": t.get("type") == "Sea",
        }
    return out


def _phase(i: int, ph: dict, supply: set[int]) -> dict:
    owners = {c["terrID"]: c["countryID"] for c in ph.get("centers") or [] if c.get("countryID")}
    counts: dict[str, int] = {}
    for tid, country in owners.items():
        if tid in supply:
            counts[str(country)] = counts.get(str(country), 0) + 1
    return {
        "i": i,
        "turn": ph["turn"],
        "phase": ph["phase"],
        "label": phase_label(ph["turn"], ph["phase"]),
        "units": [
            {"c": u["countryID"], "t": "F" if u["type"] == "Fleet" else "A", "at": u["terrID"],
             "r": bool(u.get("retreating"))}
            for u in ph.get("units") or []
        ],
        "owners": {str(tid): country for tid, country in owners.items()},
        "orders": [
            {"c": o["countryID"], "t": "F" if o.get("unitType") == "Fleet" else "A", "at": o["terrID"],
             "type": o["type"], "to": o.get("toTerrID"), "from": o.get("fromTerrID"),
             "convoy": bool(o.get("viaConvoy")), "ok": bool(o.get("success")), "dis": bool(o.get("dislodged"))}
            for o in ph.get("orders") or []
        ],
        "sc": counts,
    }  # fmt: skip


def _movement_index(phases: list[dict], turn: int) -> int | None:
    """The movement phase of `turn`; when the game ended before it, the last movement phase.

    Press is shown only on movement phases, so press sent after the last one (during the final
    retreats or builds) is listed there and not on a phase that shows no press.
    """
    last = None
    for ph in phases:
        if ph["phase"] == "Diplomacy":
            if ph["turn"] == turn:
                return ph["i"]
            last = ph["i"]
    return last if last is not None else (phases[-1]["i"] if phases else None)


def _messages(pa, public: list[dict], rows: list[dict], our_power: str, phases: list[dict]) -> list[dict]:
    """Public press, and the seat's private press, each pinned to the movement phase it is about."""
    private = pa.private_press(rows) if rows else []
    out = []
    for message in pa.ledger_messages(private, public, our_power):
        out.append({**message, "public": message["to"] == "ALL", "pi": _movement_index(phases, message["turn"]),
                    "claims": []})  # fmt: skip
    return out


def _decisions(rows: list[dict], phases: list[dict]) -> dict[str, dict]:
    """phase index -> our policy's `decision` line for that phase (what it believed and chose)."""
    where = {(ph["turn"], ph["phase"]): ph["i"] for ph in phases}
    out = {}
    for row in rows:
        if row.get("event") != "decision" or "turn" not in row:
            continue
        i = where.get((row["turn"], row.get("phase")))
        if i is not None:
            out[str(i)] = {k: v for k, v in row.items() if k not in DECISION_DROP}
    return out


def _evidence_turn(claim: dict) -> int:
    """The turn a claim was settled in: the first turn named by its evidence, else its first turn."""
    first, last = claim["window"]
    for line in claim.get("evidence") or []:
        match = re.search(r"(Spring|Autumn) (\d{4})", line)
        if match:
            turn = (int(match[2]) - 1901) * 2 + (match[1] == "Autumn")
            if first <= turn <= last:
                return turn
    return first


def _audit(episode: str, slot: int | None, messages: list[dict], phases: list[dict]) -> dict | None:
    """The press audit, joined to the messages when it is for the seat being viewed."""
    path = audit_path(episode)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except ValueError:
        return {"error": "audit.json could not be read", "slot": None, "joined": False, "markers": [], "powers": {}}
    joined = data.get("slot") == slot
    report = tool("press_report")
    markers = []
    index_of = {m["id"]: m for m in messages}
    if joined:
        for audited in data.get("messages") or []:
            message = index_of.get(audited["id"])
            if message is None:
                continue
            for claim in audited.get("claims") or []:
                settled = _movement_index(phases, _evidence_turn(claim))
                message["claims"].append({
                    **{k: claim.get(k) for k in ("kind", "quote", "outcome", "category", "relied", "evidence",
                                                 "window", "condition", "asked", "to", "context", "replaced_by",
                                                 "our_attacks_on_them")},
                    "settled": settled,
                    "verdict": report.verdict(claim, audited, data["our_power"]),
                })  # fmt: skip
                if claim.get("category") in AUDIT_MARKERS:
                    markers.append({
                        "pi": settled, "kind": claim["category"], "power": audited["from"].title(),
                        "message": audited["id"],
                        "text": f"{report.WORDS[claim['category']]}: {audited['from'].title()} "
                                f"“{claim.get('quote', '')}”",
                    })  # fmt: skip
    # An audit is one seat's view: what it relied on, who lied to it. Seen from another seat,
    # only whose audit it is goes to the page, never its counts or the quotes it flagged.
    summary = (data.get("summary") or {}) if joined else {}
    powers = {}
    for power, entry in (summary.get("powers") or {}).items():
        flagged = []
        for item in entry.get("flagged") or []:
            message = index_of.get(item["message"])
            claim = next((c for c in (message or {}).get("claims", [])
                          if c["category"] == item["category"] and c.get("quote", "") == item.get("quote", "")), None)
            flagged.append({**item, "pi": claim["settled"] if claim else _movement_index(phases, item["turn"])})
        powers[power] = {**entry, "flagged": flagged}
    return {
        "slot": data.get("slot"),
        "policy": data.get("policy"),
        "our_power": data.get("our_power"),
        "belief_logged": data.get("belief_logged"),
        "joined": joined,
        "messages": summary.get("messages"),
        "messages_with_claims": summary.get("messages_with_claims"),
        "powers": powers,
        "markers": markers,
        # The audit page's own explanation of its labels, so both read the same.
        "legend": {"lead": report.LEGEND_LEAD, "rows": report.legend(data.get("messages") or [])} if joined else None,
    }


def _events(phases: list[dict], row: dict) -> list[dict]:
    """Timeline markers from the board alone: eliminations and swings of three or more centres."""
    names = {str(seat["country"]): seat["power"] for seat in row["seats"]}
    out = []
    movement = None  # the last movement phase seen: where a later change in the count was decided
    before: dict[str, int] | None = None
    for ph in phases:
        if before is not None and movement is not None:
            for country, name in names.items():
                was, now = before.get(country, 0), ph["sc"].get(country, 0)
                if was > 0 and now == 0:
                    out.append({"pi": movement, "kind": "eliminated", "power": name,
                                "text": f"{name} lost its last {'centre' if was == 1 else f'{was} centres'}"})
                elif abs(now - was) >= SWING:
                    out.append({"pi": movement, "kind": "swing", "power": name,
                                "text": f"{name} went from {was} to {now} centres"})
        if ph["phase"] == "Diplomacy":
            movement = ph["i"]
        before = ph["sc"]
    return out
