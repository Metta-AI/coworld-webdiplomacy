"""Dashboard: how one of our policies performs, by power, opponent, version and source.

Pages:
  /dashboard?policy=NAME&version=vN&source=league|xp|local&variant=classic-press&opponent=NAME&alone=1
      Every parameter is optional, so a card can link straight to a view. Without `policy`
      the page shows the policy picked last time, else the policy this lab shipped last
      (press first), from players/*/VERSION_LOG.md
      on disk (those are ours). Without `variant` it shows the league's variant (`classic-press`)
      when the policy has a game there, else the variant it has most games in, because press and
      gunboat are never pooled silently; `variant=all` pools them. Without `version` it shows the
      newest version with enough games in the view (`matchups.LOW_N`), because versions are not
      pooled silently either; `version=all` pools them, and so does a view where no version has
      enough yet (the page then says so).
      `alone=1` keeps only the games that seat one seat of the policy (`matchups.py --alone`).
      `refresh=1` forgets everything read so far and reads the artifacts again.

JSON:
  GET /api/dashboard?...   same parameters (no `refresh`) -> {filters, reading, policies, report}.
                           `report` is the object documented at the top of the lab's
                           `tools/matchups.py`, or null when there is no policy to show;
                           `reading` is how many games are still to be read; `filters` is what
                           was shown after the defaults were filled in. It does not read the cookie.

Every number comes from `tools/matchups.py` (the write-up skill uses the same module). This
file only reads episodes once, keeps them, and turns the report into chart geometry.

Speed: parsing an episode costs about 0.1 s (the replay), so each one is parsed once and kept,
in memory and in `.runtime/ide/dashboard_games.pickle`, until a file in its directory changes.
A background thread collects the games, which `reader.each_game` parses (in worker processes
when there are many); a page asked for meanwhile shows what is read so far and reloads itself.
"""

from __future__ import annotations

import importlib
import math
import pickle
import re
import threading
import time
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from . import dates, paths, reader, store
from .server import render

router = APIRouter()
NAV = ("Dashboard", "/dashboard")

PARITY = 1 / 7
CACHE_FORMAT = 1  # bump when Game or Seat changes shape
WAIT_SECONDS = 0.5  # how long a page waits for the reader before showing a partial view
SMALL_BATCH_WAIT = 0.4  # every page waits this long for a batch small enough to be read in a server thread
SOURCE_LABELS = {"all": "all sources", "league": "league matches", "xp": "experience requests", "local": "local runs"}
SCALE_MIN_N = 8  # rows with fewer seats do not stretch a chart's axis
MIN_CELL = 3  # a heatmap cell or power pair with fewer games than this stays blank
HEATMAP_MIN_GAMES = 8  # an opponent needs this many shared games for a heatmap row
LEAGUE_VARIANT = "classic-press"  # the variant shown first, whenever the policy has a game in it
SHORT_SUFFIX = "-short"  # a variant with a low turn limit (`classic-press-short`): the lab's health games
COOKIE = "dashboard_policy"
COOKIE_AT = "dashboard_policy_at"  # when COOKIE was set, in seconds since 1970: see `remembered_policy`


def matchups():
    """The lab's `tools/matchups.py`."""
    paths.use_lab_tools()
    return importlib.import_module("matchups")


# --- reading episodes once ------------------------------------------------------------


class GameCache:
    """Parsed episodes by directory, kept until the directory changes."""

    def __init__(self):
        self.lock = threading.Lock()
        self.games: dict[str, tuple[tuple, object]] = {}  # episode directory -> (fingerprint, Game)
        self.generation = 0  # goes up whenever `games` changes: the key for computed reports
        self.reports: dict[tuple, dict] = {}
        self.thread: threading.Thread | None = None
        self.root: Path | None = None
        self.pending = 0
        self.read_at: float | None = None

    def _file(self) -> Path:
        return paths.state_dir() / "dashboard_games.pickle"

    def _restore(self, root: Path) -> None:
        self.games, self.reports, self.root = {}, {}, root
        self.generation += 1
        try:
            saved = pickle.loads(self._file().read_bytes())
            if saved.get("format") == CACHE_FORMAT and saved.get("root") == str(root):
                self.games = saved["games"]
        except Exception:  # noqa: BLE001  the file is only a cache: any unreadable one is rebuilt
            pass

    def _save(self) -> None:
        with self.lock:
            data = pickle.dumps({"format": CACHE_FORMAT, "root": str(self.root), "games": self.games})
        temporary = self._file().with_suffix(".tmp")
        temporary.write_bytes(data)
        temporary.replace(self._file())

    def _read(self, todo: dict[Path, tuple]) -> None:
        mu = matchups()
        for index, (ep, game, _) in enumerate(reader.each_game(todo)):
            if game is None:  # one unreadable episode must not hide the rest
                game = mu.Game(ep.name, "local", "unknown", None, [], True)
            with self.lock:
                self.games[str(ep)] = (todo[ep], game)
                self.pending = len(todo) - index - 1
                # Every change is a new generation, so a report made from part of a batch is never
                # served once more games are in (`sync()` hands out games and generation together).
                self.generation += 1
                self.reports = {}
                if index % 25 == 24 or self.pending == 0:
                    self.read_at = time.time()
        self._save()

    def sync(self, wait: float = WAIT_SECONDS) -> tuple[list, int, int]:
        """Start reading whatever is new and return (games read so far, episodes still to read,
        the generation those games belong to: the key `report()` files its result under)."""
        by_directory, pending, generation = self.sync_by_directory(wait)
        return list(by_directory.values()), pending, generation

    def sync_by_directory(self, wait: float = WAIT_SECONDS) -> tuple[dict[str, object], int, int]:
        """`sync()`, with each game under its episode directory (for a page about one batch's games)."""
        mu = matchups()
        root = paths.artifacts_dir()
        with self.lock:
            if self.root != root:
                self._restore(root)
            if self.thread is None or not self.thread.is_alive():
                found: dict[str, Path] = {}
                for ep in mu.episode_dirs(root) if root.is_dir() else []:
                    found.setdefault(ep.name, ep)  # the same episode fetched twice counts once
                current = {str(ep): reader.fingerprint(ep) for ep in found.values()}
                gone = set(self.games) - set(current)
                for key in gone:
                    del self.games[key]
                todo = {Path(key): fp for key, fp in current.items()
                        if key not in self.games or self.games[key][0] != fp}
                if gone:
                    self.generation += 1
                    self.reports = {}
                self.pending = len(todo)
                if todo:
                    self.thread = threading.Thread(target=self._read, args=(todo,), daemon=True)
                    self.thread.start()
                elif self.read_at is None:
                    self.read_at = time.time()
            thread = self.thread
            if self.pending and self.pending < reader.POOL_MIN:
                # A few games fetched while the server runs are read in a blink. Waiting for them
                # is quicker than a page that says "1 to go" and reloads itself four seconds later.
                wait = max(wait, SMALL_BATCH_WAIT)
        if thread is not None:
            thread.join(wait)
        with self.lock:
            return {key: game for key, (_, game) in self.games.items()}, self.pending, self.generation

    def report(self, games: list, generation: int, key: tuple) -> dict:
        """`matchups.report` for `games`, the snapshot `sync()` returned with `generation`."""
        with self.lock:
            cached = self.reports.get((generation, *key))
        if cached is None:
            cached = matchups().report(games, *key)
            with self.lock:
                if generation == self.generation:
                    self.reports[(generation, *key)] = cached
        return cached

    def forget(self) -> None:
        with self.lock:
            self.root = None
        reader.forget()
        self._file().unlink(missing_ok=True)


CACHE = GameCache()


# --- choosing what to show ------------------------------------------------------------


VERSION_LOG_ROW = re.compile(r"^\| *([\w.-]+):v\d+ *\|", re.M)


def remembered_policy(request: Request) -> str:
    """The policy the user picked in this browser, or "" when there is none or it no longer counts.

    The newer of the two choices wins: a pick in the browser stays until the agent records a
    policy after it (`ide/ide follow NAME`, which the agent runs when the user says "my policy
    is X"), and that stays until the user picks again. The pick's time is the second cookie; a
    pick without one (made before the time was kept) loses to any recorded policy.
    """
    name = request.cookies.get(COOKIE, "")
    try:
        picked = float(request.cookies.get(COOKIE_AT, ""))
    except ValueError:
        picked = 0.0
    return name if name and picked >= store.followed_at() else ""


def remember_policy(response, name: str) -> None:
    """Record in the browser that the user picked this policy now."""
    for cookie, value in ((COOKIE, name), (COOKIE_AT, f"{time.time():.3f}")):
        response.set_cookie(cookie, value, max_age=365 * 24 * 3600, samesite="lax")


def shipped_policies() -> list[str]:
    """Policy names this lab uploaded, newest first: the rows `tools/ship.py` adds to `players/*/VERSION_LOG.md`."""
    names = []
    for log in sorted((paths.lab_dir() / "players").glob("*/VERSION_LOG.md")):
        names += VERSION_LOG_ROW.findall(log.read_text())
    return list(dict.fromkeys(reversed(names)))


def lab_policy(known: set[str]) -> str:
    """The policy this lab can name as ours without guessing, among the policies in the fetched
    games: the one the agent recorded (`ide/ide follow NAME`), else the newest upload. "" when
    the lab has neither."""
    recorded = store.followed_policy()
    if recorded in known:
        return recorded
    return next((name for name in shipped_policies() if name in known), "")


def _default_policy(policies: list[dict]) -> dict | None:
    """The policy to show before the user has picked one.

    A seat log does not mark a policy as ours (a team's lab can read every field bot's log),
    so first the policy the agent recorded as the user's (`ide/ide follow NAME`), then what
    this lab shipped: a press policy first, because the press league is the main one, then
    the newest upload. Without either, the first policy listed, which is a guess.
    """
    by_name = {p["name"]: p for p in policies}
    if store.followed_policy() in by_name:
        return by_name[store.followed_policy()]
    shipped = [by_name[name] for name in shipped_policies() if name in by_name]
    press = [p for p in shipped if any("press" in variant for variant in p["variants"])]
    return (press or shipped or policies or [None])[0]


def _choose(policies: list[dict], policy: str, version: str, source: str, variant: str, remembered: str) -> dict:
    """Fill in the filters the request left out. Returns the names the page and the report use."""
    by_name = {p["name"]: p for p in policies}
    if ":v" in policy and not version:  # a card may link with policy=name:v3
        policy, _, version = policy.rpartition(":")
    chosen = by_name.get(policy) or by_name.get(remembered) or _default_policy(policies)
    unknown = policy if policy and policy not in by_name else ""
    if chosen is None:
        return {"policy": "", "version": "", "version_default": True, "version_note": "", "source": "all",
                "variant": "all", "unknown": unknown, "row": None}
    if version != "all" and f'{chosen["name"]}:{version}' not in chosen["versions"]:
        version = ""  # none asked for: `_load` picks the newest with enough games
    if source not in ("league", "xp", "local"):
        source = "all"
    if not variant and LEAGUE_VARIANT in chosen["variants"]:
        # A few short health games on a first evening must not be the headline.
        variant = LEAGUE_VARIANT
    elif not variant:  # most games first; ties go to the name that sorts first
        variant = sorted(chosen["variants"].items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    return {"policy": chosen["name"], "version": version, "version_default": not version, "version_note": "",
            "source": source, "variant": variant, "unknown": unknown, "row": chosen}


def _default_version(pooled: dict) -> tuple[str, str]:
    """(the version to lead with when the request names none, a sentence that says why).

    `pooled` is the view's report for every version together. The newest version with enough
    games for a reading (`matchups.LOW_N`, the floor behind "too few games") is shown by itself:
    a number pooled over versions describes no policy that exists. "" when no version has enough
    yet; the view then stays pooled and the sentence names what is in it.
    """
    low = report_low_n()
    rows = [v for v in pooled["by_version"] if v["version"]]  # oldest first
    counts = [f"{v['version']} ({v['vs_par']['games']} game{'' if v['vs_par']['games'] == 1 else 's'})" for v in rows]
    enough = [i for i, v in enumerate(rows) if not v["vs_par"]["low_n"]]
    if not enough:
        if len(rows) < 2:
            return "", ""
        return "", f"No version has {low} games in this view yet, so all {len(rows)} are pooled: {', '.join(counts)}."
    note = f"{rows[enough[-1]]['version']} is the newest version with at least {low} games in this view."
    if counts[enough[-1] + 1:]:
        note += f" Newer, with too few games so far: {', '.join(counts[enough[-1] + 1:])}."
    return rows[enough[-1]]["version"], note


def _short_games(filters: dict) -> list[dict]:
    """The policy's games in short variants other than the one shown: [{variant, games, link}].

    They are health games (does this version run?), cut off after a few years, so they get a
    line of their own and are never part of the headline of another variant.
    """
    if filters["variant"] == "all":
        return []
    return [{"variant": name, "games": games, "link": _link(filters, variant=name)}
            for name, games in filters["row"]["variants"].items()
            if name.endswith(SHORT_SUFFIX) and name != filters["variant"]]


def _link(filters: dict, **changes) -> str:
    """The dashboard URL for `filters` with some of them changed (empty values are left out)."""
    query = {k: filters.get(k, "") for k in ("policy", "version", "source", "variant", "opponent", "alone")}
    if filters.get("version_default"):
        query["version"] = ""  # the page chose it, so a link keeps "the newest with enough games" and does not pin it
    query |= changes
    query = {k: v for k, v in query.items() if v and not (k == "source" and v == "all")}
    return "/dashboard?" + urlencode(query)


# --- words and numbers ----------------------------------------------------------------


def signed(x: float | None, places: int = 3) -> str:
    if x is None:
        return "–"
    if round(x, places) == 0:
        return f"{0:.{places}f}"  # never "+0.00" or "−0.00"
    return f"{x:+.{places}f}".replace("-", "−")


def plain(x: float | None, places: int = 3) -> str:
    return "–" if x is None else f"{x:.{places}f}".replace("-", "−")


def share(r: dict) -> str:
    """A rate with its counts: '7 of 105 (7%)'."""
    return "none yet" if not r["n"] else f'{r["k"]} of {r["n"]} ({r["rate"] * 100:.0f}%)'


def stat_tip(label: str, s: dict) -> str:
    if not s["n"]:
        return f"{label}: no games"
    text = f"{label}: {signed(s['mean'])} vs par over {s['n']} seats"
    if s["se"] is not None:
        text += f" · SE {plain(s['se'])} · z {signed(s['z'], 2)}"
    if s["ci"]:
        text += f" · 95% interval {signed(s['ci'][0])} to {signed(s['ci'][1])}"
    return f"{text} · {matchups().reading(s)}"


def few_tip(s: dict) -> str:
    """Why a row below the lab's floor has no verdict, and what its lean is worth."""
    low = report_low_n()
    text = (f"{s['games']} games, and the lab calls nothing a result on fewer than {low}: one or two unusual games "
            "move so small a sample, and among many rows some reach |z| ≥ 2 by chance.")
    if s.get("lean"):
        text += (f" This row leans {s['lean']} (z {signed(s['z'], 2)}, and its 95% interval stays on one side of "
                 "par): a lead to play more games for, not a result.")
    return text


def _cover(report: dict, alone: dict | None, filters: dict) -> dict:
    """What the headline number covers, in a few words, and the alone-runs figure to put beside it.

    The lab manual has the agent quote alone runs for "how good is this version" (a second seat of
    ours in the game changes the score level), so a page that leads with every game says so and
    shows the other number too. `alone` is the same report with `alone=True`, or None when the
    view has no paired games or is the alone view already.
    """
    paired = report["paired_games"]
    runs = "a paired run" if paired == 1 else "paired runs"
    text = f"{report['games']} game{'' if report['games'] == 1 else 's'}"
    if filters["alone"]:
        text += ", alone runs only" + (f" ({paired} paired run{'' if paired == 1 else 's'} left out)" if paired else "")
    elif paired:
        text += f", {paired} of them {runs}"
    beside = None
    if alone is not None and alone["overall"]["vs_par"]["n"]:
        s = alone["overall"]["vs_par"]
        beside = {"stat": s, "mean": signed(s["mean"]), "score": plain(alone["overall"]["score"]),
                  "reading": matchups().reading(s), "link": _link(filters, alone="1"),
                  "tone": {"above par": "ok", "below par": "err"}.get(s["verdict"], "")}  # fmt: skip
    return {"text": text, "paired": paired, "alone": beside,
            "tip": "A paired run seats two or more seats of this policy in one game (an A/B). Its score level "
                   "is not what one seat gets alone."}  # fmt: skip


def _headline(report: dict) -> dict:
    """The one-sentence reading of the overall number."""
    s = report["overall"]["vs_par"]
    if not s["n"]:
        return {"lead": "No clean games yet for this view.", "reading": "", "tone": ""}
    direction = "above" if s["mean"] > 0 else "below"
    lead = f"{signed(s['mean'])} per game against par" if s["mean"] else "Exactly at par"
    if s["verdict"] == "too few games":
        reading = (f"Too few games to say: {s['games']}, and the lab reads nothing from fewer than "
                   f"{report_low_n()}. The sign is a lead, not a result.")
    elif s["verdict"] == "no result":
        reading = (f"No result. With z = {signed(s['z'], 2)} the interval includes par, so this policy is not "
                   f"shown to be {direction} the field. That is not evidence that it is equal.")
    elif s["ci"][0] <= 0 <= s["ci"][1]:
        # |z| >= 2 is the lab's rule, but with few games the t interval is wider than 2 SE.
        reading = (f"{direction.capitalize()} par by the lab's rule (z = {signed(s['z'], 2)}), but only just: with "
                   f"{s['games']} games the 95% interval ({signed(s['ci'][0])} to {signed(s['ci'][1])}) still "
                   "reaches zero. Treat it as borderline.")
    else:
        reading = (f"{direction.capitalize()} par. z = {signed(s['z'], 2)}, and the 95% interval "
                   f"({signed(s['ci'][0])} to {signed(s['ci'][1])}) stays {direction} zero.")
    return {"lead": lead, "reading": reading,
            "tone": {"above par": "ok", "below par": "err"}.get(s["verdict"], "")}


def report_low_n() -> int:
    return matchups().LOW_N


# --- chart geometry -------------------------------------------------------------------


def _nice_step(span: float, target: int = 5) -> float:
    raw = span / target
    magnitude = 10 ** math.floor(math.log10(raw))
    return next(m * magnitude for m in (1, 2, 5, 10) if m * magnitude >= raw)


class Scale:
    """A horizontal value axis for interval cells: values to x pixels, with ticks."""

    def __init__(self, stats: list[dict], width: int = 300, pad: int = 12, cap: float = 0.5):
        known = [s for s in stats if s.get("mean") is not None]
        # Rows with enough games set the range, so one three-game row cannot flatten the rest;
        # a whisker that does not fit is cut at the edge and drawn with an arrowhead.
        sizing = [s for s in known if s["n"] >= SCALE_MIN_N] or known
        reach = max([0.02] + [max(abs(v) for v in (s["ci"] or [s["mean"]])) for s in sizing])
        step = _nice_step(2 * min(reach, cap), 4)
        self.limit = math.ceil(min(reach, cap) / step - 1e-9) * step
        self.width, self.pad = width, pad
        count = round(self.limit / step)
        labelled = (lambda i: True) if width >= 280 else (lambda i: i == 0 or abs(i) == count)
        self.ticks = [{"value": i * step, "x": self.x(i * step),
                       "label": ("par" if i == 0 else signed(i * step, 2)) if labelled(i) else "",
                       "anchor": "start" if i == -count else "end" if i == count else "middle"}
                      for i in range(-count, count + 1)]
        self.zero = self.x(0.0)

    def x(self, value: float) -> float:
        inner = self.width - 2 * self.pad
        clamped = max(-self.limit, min(self.limit, value))
        return round(self.pad + (clamped + self.limit) / (2 * self.limit) * inner, 1)

    def mark(self, s: dict) -> dict | None:
        """Where to draw one stat: dot, whisker ends, and whether an end is cut off."""
        if s.get("mean") is None:
            return None
        out = {"x": self.x(s["mean"]), "off": abs(s["mean"]) > self.limit, "lo": None, "hi": None,
               "cut_lo": False, "cut_hi": False,
               "kind": "low" if s.get("low_n") else ("sure" if s.get("verdict") not in ("no result", None) else "open")}
        if s.get("ci"):
            out.update(lo=self.x(s["ci"][0]), hi=self.x(s["ci"][1]),
                       cut_lo=s["ci"][0] < -self.limit, cut_hi=s["ci"][1] > self.limit)
        return out


NEUTRAL, ABOVE, BELOW = (236, 231, 218), (26, 56, 117), (148, 86, 55)  # paper-grey, navy, terracotta


def _cell_colour(value: float, limit: float) -> tuple[str, str]:
    """(background, text colour) on a diverging scale centred on par."""
    t = max(-1.0, min(1.0, value / limit)) if limit else 0.0
    pole = ABOVE if t > 0 else BELOW
    weight = 0.10 + 0.80 * abs(t) if t else 0.0
    rgb = [round(n + (p - n) * weight) for n, p in zip(NEUTRAL, pole)]
    luminance = (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]) / 255
    return "#%02x%02x%02x" % tuple(rgb), ("#fffdf4" if luminance < 0.42 else "#1b1a17")


def _heatmap(report: dict, key: str) -> dict | None:
    """Opponent rows by power columns of our score vs par; `key` is by_their_power or by_our_power."""
    rows = [o for o in report["by_opponent"] if o["games"] >= HEATMAP_MIN_GAMES
            and any(s["n"] >= MIN_CELL for s in o[key].values())]
    if key == "by_our_power":
        # An opponent seated in every one of our games would only repeat the By power table.
        rows = [o for o in rows if o["games"] < report["games"]]
    values = [s["mean"] for o in rows for s in o[key].values() if s["n"] >= MIN_CELL]
    if not values:
        return None
    # Never tighter than 0.15: a tighter scale would paint the noise of an eight-game cell in
    # the darkest colours.
    # Cells with enough games set the scale; a three-game cell at +0.4 just saturates.
    solid = [s["mean"] for o in rows for s in o[key].values() if not s["low_n"]]
    limit = max(0.15, min(0.3, max((abs(v) for v in solid), default=0.0)))
    powers = matchups().POWER_NAMES
    out = []
    for o in rows:
        cells = []
        for power in powers:
            s = o[key].get(power)
            if s is None or s["n"] < MIN_CELL:
                cells.append({"n": s["n"] if s else 0, "blank": True,
                              "tip": f"{o['opponent']}, {power}: {s['n'] if s else 0} games, too few to show"})
                continue
            background, colour = _cell_colour(s["mean"], limit)
            cells.append({"n": s["n"], "blank": False, "value": signed(s["mean"], 2), "background": background,
                          "colour": colour if not s["low_n"] else "#1b1a17", "low": s["low_n"],
                          "tip": stat_tip(f"{o['opponent']}, {power}", s)})
        out.append({"opponent": o["opponent"], "games": o["games"], "cells": cells})
    legend = [{"label": signed(limit * t, 2) if t else "par", "background": _cell_colour(limit * t, limit)[0]}
              for t in (-1, -0.5, 0, 0.5, 1)]
    return {"powers": powers, "rows": out, "legend": legend, "limit": limit}


def _trajectory(series: dict, width: int = 560, height: int = 220) -> dict | None:
    years = series["years"]
    if len(years) < 2:
        return None
    left, right, top, bottom = 34, 96, 12, 26
    values = [v for y in years for v in (y["ours"], y["field"], y["ours"] + 2 * (y["se"] or 0),
                                         y["ours"] - 2 * (y["se"] or 0))]
    # A line chart shows change, so the axis fits the data instead of starting at zero.
    step = _nice_step(max(max(values) - min(values), 1.0), 4)
    y_min = math.floor(min(values) / step) * step
    y_max = max(math.ceil(max(values) / step) * step, y_min + step)

    def px(index: int) -> float:
        return round(left + index / (len(years) - 1) * (width - left - right), 1)

    def py(value: float) -> float:
        return round(top + (1 - (value - y_min) / (y_max - y_min)) * (height - top - bottom), 1)

    points = [{"year": y["year"], "n": y["n"], "x": px(i), "ours": py(y["ours"]), "field": py(y["field"]),
               "tip": f"End of {y['year']}: ours {plain(y['ours'], 2)} centres, field at the same powers "
                      f"{plain(y['field'], 2)}; difference {signed(y['diff'], 2)}"
                      + (f" ± {plain(y['se'], 2)} SE" if y["se"] is not None else "") + f", {y['n']} seats"}
              for i, y in enumerate(years)]
    # The band is two SEs of (ours minus field) around our line: where it covers the field line,
    # that year shows no difference.
    upper = [f"{px(i)},{py(min(y_max, y['ours'] + 2 * y['se']))}" for i, y in enumerate(years) if y["se"] is not None]
    lower = [f"{px(i)},{py(max(y_min, y['ours'] - 2 * y['se']))}" for i, y in enumerate(years) if y["se"] is not None]
    last = years[-1]
    ours_label, field_label = points[-1]["ours"], points[-1]["field"]
    if abs(ours_label - field_label) < 14:  # keep the two end labels from sitting on each other
        up = ours_label <= field_label
        ours_label, field_label = (ours_label - 7, field_label + 7) if up else (ours_label + 7, field_label - 7)
    return {
        "variant": series["variant"], "width": width, "height": height, "left": left, "plot_right": width - right,
        "base": py(y_min), "points": points,
        "ours": " ".join(f"{p['x']},{p['ours']}" for p in points),
        "field": " ".join(f"{p['x']},{p['field']}" for p in points),
        "band": " ".join(upper + lower[::-1]) if len(upper) > 1 else "",
        "y_ticks": [{"y": py(y_min + i * step), "label": f"{y_min + i * step:g}"}
                    for i in range(round((y_max - y_min) / step) + 1)],
        "x_ticks": [p for i, p in enumerate(points) if len(points) <= 6 or i % 2 == 0 or i == len(points) - 1],
        "end": {"ours": plain(last["ours"], 1), "field": plain(last["field"], 1),
                "ours_y": ours_label, "field_y": field_label},
        "n_first": years[0]["n"], "n_last": last["n"],
    }


def _view(report: dict, filters: dict) -> dict:
    """Everything the template draws, as plain values and pixel positions."""
    mu = matchups()
    overall = report["overall"]["vs_par"]
    power_scale = Scale([overall] + [p["vs_par"] for p in report["by_power"]])
    powers = [{"label": "All powers", "all": True, "row": {"vs_par": overall, "score": report["overall"]["score"],
                                                            "par": None}}]
    powers += [{"label": p["power"], "all": False, "row": p} for p in report["by_power"]]
    for p in powers:
        p["mark"] = power_scale.mark(p["row"]["vs_par"])
        p["tip"] = stat_tip(p["label"], p["row"]["vs_par"])

    version_scale = Scale([v["vs_par"] for v in report["by_version"]])
    versions = [{**v, "mark": version_scale.mark(v["vs_par"]), "tip": stat_tip(v["policy"], v["vs_par"]),
                 "link": _link(filters, version=v["version"] or "")} for v in report["by_version"]]

    segments = {(s["variant"], s["source"]): s for s in report["by_segment"]}
    variants = sorted({s["variant"] for s in report["by_segment"]})
    segment_scale = Scale([s["vs_par"] for s in report["by_segment"]])
    sources = []
    for variant in variants:
        for source in ("league", "xp", "local"):
            s = segments.get((variant, source))
            if s is None and source == "local":
                continue  # league and experience requests always get a row; local runs only when present
            label = f"{SOURCE_LABELS[source].capitalize()}"
            sources.append({"variant": variant, "source": source, "label": label, "row": s,
                            "mark": segment_scale.mark(s["vs_par"]) if s else None,
                            "tip": stat_tip(f"{variant}, {SOURCE_LABELS[source]}", s["vs_par"]) if s else ""})

    paired_scale = Scale([o["paired"] for o in report["by_opponent"]], width=200, pad=8)
    # The replay browser takes the same source and variant values, so the link opens the same games.
    scope = {k: filters[k] for k in ("source", "variant") if filters[k] != "all"}
    opponents = []
    for o in report["by_opponent"]:
        h = o["head_to_head"]
        decided = h["ahead"] + h["behind"]
        opponents.append({
            **o, "mark": paired_scale.mark(o["paired"]), "tip": stat_tip(f"Ours minus {o['opponent']}", o["paired"]),
            "ahead_width": round(60 * h["ahead"] / decided) if decided else 0,
            "behind_width": round(60 * h["behind"] / decided) if decided else 0,
            "replays": "/replays?" + urlencode({"policy": report["policy"], "opponent": o["opponent"], **scope}),
            "focus": _link(filters, opponent=o["opponent"]),
        })
    # The opponent that finishes furthest ahead of us comes first: the page's question is "who beats us".
    opponents.sort(key=lambda o: (o["paired"]["mean"] is None, o["paired"]["mean"] or 0.0))

    return {
        "headline": _headline(report), "power_scale": power_scale, "powers": powers,
        "version_scale": version_scale, "versions": versions,
        "segment_scale": segment_scale, "sources": sources, "source_variants": variants,
        "paired_scale": paired_scale, "opponents": opponents,
        "heat_theirs": _heatmap(report, "by_their_power"), "heat_ours": _heatmap(report, "by_our_power"),
        "trajectories": [t for t in (_trajectory(s) for s in report["trajectory"]) if t],
        "low_n": mu.LOW_N, "min_cell": MIN_CELL, "heatmap_min_games": HEATMAP_MIN_GAMES,
    }


# --- routes ---------------------------------------------------------------------------


def _load(policy: str, version: str, source: str, variant: str, opponent: str, remembered: str = "",
          wait: float = WAIT_SECONDS, alone: int = 0):
    games, pending, generation = CACHE.sync(wait)
    policies = matchups().list_policies(games)
    filters = _choose(policies, policy, version, source, variant, remembered)
    filters["opponent"] = opponent
    filters["alone"] = "1" if alone else ""  # only games that seat one seat of the policy (matchups.py --alone)
    filters["short"] = _short_games(filters) if filters["row"] else []
    report = cover = None
    if filters["row"]:
        scope = (filters["source"], None if filters["variant"] == "all" else filters["variant"], opponent or None)
        if filters["version_default"]:
            pooled = CACHE.report(games, generation, (filters["policy"], *scope, bool(alone)))
            filters["version"], filters["version_note"] = _default_version(pooled)
        name = filters["policy"] + (f':{filters["version"]}' if filters["version"] not in ("", "all") else "")
        key = (name, *scope)
        report = CACHE.report(games, generation, (*key, bool(alone)))
        # The same view without the paired games, for the figure beside the headline (cached like the first).
        apart = CACHE.report(games, generation, (*key, True)) if report["paired_games"] and not alone else None
        cover = _cover(report, apart, filters)
    return games, pending, policies, filters, report, cover


def summary(remembered: str = "", wait: float = 0.0) -> dict:
    """What `/dashboard` with no parameters would lead with, for the home page.

    The same choice of policy (the one remembered in the cookie, else what this lab shipped last),
    of variant and of version, the same cached report and the same sentence. With `wait` 0 it does not wait
    for a large read (a handful of new games is waited for, `SMALL_BATCH_WAIT`): `pending` says
    how many games are still to be read, and the numbers cover the rest.
    """
    games, pending, _, filters, report, cover = _load("", "", "", "", "", remembered, wait)
    return {
        "policy": filters["policy"], "variant": filters["variant"], "pending": pending, "games_on_disk": len(games),
        "version": filters["version"], "version_note": filters["version_note"], "short": filters["short"],
        "stat": report["overall"]["vs_par"] if report else None,
        "headline": _headline(report) if report else None,
        "cover": cover,
        "link": _link(filters) if report else "/dashboard",
        "pooled_link": _link(filters, version="all"),
    }  # fmt: skip


@router.get("/dashboard")
def dashboard(request: Request, policy: str = "", version: str = "", source: str = "", variant: str = "",
              opponent: str = "", alone: int = 0, refresh: int = 0):
    if refresh:
        CACHE.forget()
        query = {k: v for k, v in request.query_params.items() if k != "refresh"}
        return RedirectResponse("/dashboard" + (f"?{urlencode(query)}" if query else ""), status_code=303)
    games, pending, policies, filters, report, cover = _load(policy, version, source, variant, opponent,
                                                             remembered_policy(request), alone=alone)
    response = render(
        request, "dashboard.html", report=report, view=_view(report, filters) if report else None,
        policies=policies, filters=filters, games_on_disk=len(games), pending=pending,
        read_at=dates.when(CACHE.read_at, zone=True),
        source_labels=SOURCE_LABELS, parity=PARITY, link=lambda **changes: _link(filters, **changes),
        signed=signed, plain=plain, share=share, cover=cover, few_tip=few_tip,
    )
    if policy and filters["policy"] == policy.partition(":v")[0]:
        remember_policy(response, filters["policy"])
    return response


@router.get("/api/dashboard")
def dashboard_json(policy: str = "", version: str = "", source: str = "", variant: str = "", opponent: str = "",
                   alone: int = 0):
    _, pending, policies, filters, report, _ = _load(policy, version, source, variant, opponent, alone=alone)
    return {"filters": {k: filters[k] for k in ("policy", "version", "source", "variant", "opponent", "alone")},
            "reading": pending, "policies": policies, "report": report}
