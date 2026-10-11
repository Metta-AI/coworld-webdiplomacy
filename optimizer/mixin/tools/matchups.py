#!/usr/bin/env python3
"""How one policy performs: by power, opponent, version, source and variant (the IDE dashboard's numbers).

    python3 games/webdiplomacy/tools/matchups.py DIR... --policy NAME[:vN] \\
        [--source league|xp|local|all] [--variant classic-press] [--opponent NAME] [--json]
    python3 games/webdiplomacy/tools/matchups.py DIR... --list        # which policies are in the data

The IDE dashboard and the matchup write-up skill both call this module, so there is one
implementation of the numbers. Standard library only; episodes are read through
`webdip_episodes.py` and the distributions come from `ab_stats.py`.

How the numbers are made
- **Family.** `--policy NAME` takes every version of NAME as "ours"; `NAME:vN` takes one
  version. Either way every seat of NAME (any version) is left out of the field: a sibling
  version is neither par nor an opponent. (`wd.py metrics --policy NAME:vN` counts sibling
  versions as field, so the two differ when two versions share the data.)
- **Taint first.** A game is dropped when it was cancelled, failed or timed out, or when one
  of our seats in it is tainted (see `webdip_episodes.py`). `taint` counts what was dropped,
  and `overall.raw_including_tainted` shows the raw score with those games put back.
- **Score vs par.** par = mean score at that power over the field seats (not NAME) of the
  same variant in every clean game that passes the source and variant filters (games without
  one of our seats included), as `field_par` does over the directories it is given. One observation is one of our
  seats: `score - par[variant][power]`. Press and gunboat never share a par. A seat whose
  power no field seat played has no par and is counted in `no_par_seats`.
- **SE, z, interval.** SE is clustered by game (two of our seats in one game are not
  independent); with one of our seats per game it equals sd/sqrt(n), the number `wd.py
  metrics` prints. z = mean / SE. `ci` is the 95% t interval on (games - 1) degrees of
  freedom. The SE ignores the uncertainty of par itself (`par[...].n` shows how many field
  seats each par rests on).
- **Verdict.** "above par" / "below par" only when |z| >= 2 and n >= LOW_N (16, the lab's
  floor for a per-power cell); otherwise "no result", or "too few games" below LOW_N.
  Nothing is corrected for the number of rows shown: with dozens of rows some reach
  |z| >= 2 by chance. Treat by-opponent and power-pair rows as leads to check in replays.
- **Opponents are associations.** Seats are not assigned at random across opponents, so
  "with vs without" mixes in the power draw, the date and the rest of the table.

JSON shape (`--json`, and `report()`); every `stat` is
`{n, games, mean, se, z, ci: [lo, hi], low_n, verdict}` (`mean`.. `ci` are null when unknown):

  {policy, version, family, filters: {source, variant, opponent},
   games, seats, variants: {variant: games}, mixed_variants, several_of_ours_games, no_par_seats,
   caveats: [str],
   overall: {vs_par: stat, score, raw_including_tainted: {n, score}, final_centers,
             solo|draw|eliminated|survival|top_score: {k, n, rate}},
   par: {variant: {power: {n, score, final_centers}}},
   by_power:   [{power, vs_par: stat, score, par, final_centers, eliminated: rate}],      7 rows
   by_version: [{policy, version, first, last, vs_par: stat, score}],                     oldest first
   by_source:  [{source, vs_par: stat, score}],   by_variant: [{variant, vs_par: stat, score}],
   by_segment: [{variant, source, vs_par: stat, score}],
   by_opponent: [{opponent, versions: {policy: games}, games, first, last,
                  with: stat, without: stat, difference: {diff, se, z, verdict},
                  their_score, their_vs_par: stat,
                  head_to_head: {ahead, behind, tied, rate, z, verdict},
                  paired: stat,              per game: our score vs par minus theirs
                  eliminated_with: rate, eliminated_without: rate, outgrew_us: rate,
                  by_our_power: {power: stat}, by_their_power: {power: stat},
                  pairs: [{ours, theirs, vs_par: stat}]}],            most games first
   trajectory: [{variant, years: [{year, n, ours, field, diff, se}]}],  field = same powers as ours;
                                                                        se is of diff, over our seats
   taint: {seats_seen, flags: {flag: seats}, games_dropped, games_missing_results},
   cost: {seats_with_log, llm_seats, usd_per_seat_game, usd_total, llm_calls, llm_failed},
   our_seats: [{episode, date, variant, source, policy, power, score, par, vs_par,
                final_centers, opponents: {name: [powers]}}]}

`episode` is the episode directory name (the IDE's episode id: `/replays/<episode>`).
`list_policies()` / `--list --json`: `[{name, versions, seats, seats_with_log, games, latest,
variants, sources}]`, policies that have seat logs on disk first (those are ours), newest first.

Example:
    python3 games/webdiplomacy/tools/matchups.py games/webdiplomacy/.runtime/artifacts \\
        --policy my-bot --variant classic-press
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ab_stats  # noqa: E402
from webdip_episodes import (  # noqa: E402
    EPISODE_TAINTS,
    POWERS,
    Seat,
    episode_dirs,
    episode_source,
    load_episode,
    read_json_file,
)

LOW_N = 16  # the survey binding's floor: below this a cell is directional only
MIN_ABS_Z = ab_stats.MIN_ABS_Z
SOURCES = ("league", "xp", "local")
POWER_NAMES = list(POWERS.values())


@dataclass
class Game:
    """One episode directory with what the dashboard needs beyond its seats."""

    episode: str  # the directory name: the IDE's episode id
    source: str  # league | xp | local
    variant: str  # classic-press, classic-gunboat, ... or "unknown"
    date: str | None  # episode.json created_at (ISO, UTC); None for local runs
    seats: list[Seat] = field(default_factory=list)
    missing_results: bool = False


def family_of(policy: str) -> str:
    """`name:v3` -> `name`; seating labels without a version are their own family."""
    return re.sub(r":v[^:]*$", "", policy)


def variant_of(ep_dir: Path) -> str:
    """The variant id from episode.json (`Classic press` -> `classic-press`), else from the game config."""
    path = ep_dir / "episode.json"
    episode = read_json_file(path) if path.exists() else {}
    if episode.get("variant_name"):
        return re.sub(r"[^a-z0-9]+", "-", episode["variant_name"].lower()).strip("-")
    press = (episode.get("game_config") or {}).get("press")
    return {"NoPress": "classic-gunboat", "Regular": "classic-press"}.get(press, "unknown")


def load_game(ep_dir: Path) -> Game:
    seats, status = load_episode(ep_dir)
    path = ep_dir / "episode.json"
    date = read_json_file(path).get("created_at") if path.exists() else None
    return Game(ep_dir.name, episode_source(ep_dir), variant_of(ep_dir), date, seats, "results" in status["missing"])


def load_games(roots: list[Path]) -> list[Game]:
    """Every episode below `roots`, once each (the same episode fetched twice is read once)."""
    games: dict[str, Game] = {}
    for root in roots:
        for ep in episode_dirs(root):
            if ep.name not in games:
                games[ep.name] = load_game(ep)
    return list(games.values())


# --- statistics -----------------------------------------------------------------------


def _round(x: float | None, places: int = 4) -> float | None:
    return None if x is None else round(x, places)


def t_critical(df: int, alpha: float = 0.05) -> float:
    """Two-sided critical value of Student's t (bisection on `ab_stats.t_two_sided_p`)."""
    lo, hi = 0.0, 1000.0
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if ab_stats.t_two_sided_p(mid, df) > alpha else (lo, mid)
    return hi


def verdict_of(z: float | None, n: int, positive: str = "above par", negative: str = "below par") -> str:
    if n < LOW_N:
        return "too few games"
    if z is None or abs(z) < MIN_ABS_Z:
        return "no result"
    return positive if z > 0 else negative


def stat(observations: list[tuple[str, float]]) -> dict:
    """Mean of `(game, value)` observations with a game-clustered SE, z, 95% interval and verdict."""
    n = len(observations)
    by_game: dict[str, float] = defaultdict(float)
    mean = sum(v for _, v in observations) / n if n else None
    for game, value in observations:
        by_game[game] += value - mean
    clusters = len(by_game)
    se = z = ci = None
    if clusters > 1:
        se = math.sqrt(clusters / (clusters - 1) * sum(s * s for s in by_game.values())) / n
        if se > 0:
            z = mean / se
            half = t_critical(clusters - 1) * se
            ci = [_round(mean - half), _round(mean + half)]
    return {"n": n, "games": clusters, "mean": _round(mean), "se": _round(se), "z": _round(z, 2), "ci": ci,
            "low_n": n < LOW_N, "verdict": verdict_of(z, n)}


def rate(flags) -> dict:
    flags = [bool(f) for f in flags]
    return {"k": sum(flags), "n": len(flags), "rate": _round(sum(flags) / len(flags)) if flags else None}


def _mean(values) -> float | None:
    values = [v for v in values if v is not None]
    return _round(sum(values) / len(values)) if values else None


def difference(with_stat: dict, without_stat: dict) -> dict:
    """`with - without` for two sets of games (independent, so the SEs add in quadrature)."""
    if with_stat["mean"] is None or without_stat["mean"] is None:
        return {"diff": None, "se": None, "z": None, "verdict": "no comparison"}
    diff = with_stat["mean"] - without_stat["mean"]
    if with_stat["se"] is None or without_stat["se"] is None:
        return {"diff": _round(diff), "se": None, "z": None, "verdict": "too few games"}
    se = math.hypot(with_stat["se"], without_stat["se"])
    z = diff / se if se > 0 else None
    n = min(with_stat["n"], without_stat["n"])
    return {"diff": _round(diff), "se": _round(se), "z": _round(z, 2),
            "verdict": verdict_of(z, n, "better with them", "worse with them")}


def sign_test(ahead: int, behind: int, tied: int) -> dict:
    decided = ahead + behind
    z = (ahead - behind) / math.sqrt(decided) if decided else None
    return {"ahead": ahead, "behind": behind, "tied": tied, "rate": _round(ahead / decided) if decided else None,
            "z": _round(z, 2), "verdict": verdict_of(z, decided, "we finish ahead", "they finish ahead")}


# --- the report -----------------------------------------------------------------------


@dataclass
class Ours:
    """One of our seats in a kept game, with its score against par."""

    game: Game
    seat: Seat
    par: float | None
    opponents: dict[str, list[Seat]]  # opponent family -> their seats in this game

    @property
    def vs_par(self) -> float | None:
        return None if self.par is None else self.seat.score - self.par


def _obs(rows: list[Ours]) -> list[tuple[str, float]]:
    return [(r.game.episode, r.vs_par) for r in rows if r.par is not None]


def _summary(rows: list[Ours]) -> dict:
    return {"vs_par": stat(_obs(rows)), "score": _mean(r.seat.score for r in rows)}


def field_pars(games: list[Game], family: str) -> dict[str, dict[str, dict]]:
    """variant -> power -> {n, score, final_centers, centers_by_year} over the field seats."""
    groups: dict[tuple[str, str], list[Seat]] = defaultdict(list)
    for g in games:
        for s in g.seats:
            if family_of(s.policy) != family:
                groups[(g.variant, s.power)].append(s)
    out: dict[str, dict[str, dict]] = defaultdict(dict)
    for (variant, power), seats in sorted(groups.items()):
        years: dict[int, list[int]] = defaultdict(list)
        for s in seats:
            for year, centers in s.centers_by_year.items():
                years[year].append(centers)
        out[variant][power] = {
            "n": len(seats), "score": sum(s.score for s in seats) / len(seats),
            "final_centers": _mean(s.final_centers for s in seats),
            "centers_by_year": {y: sum(v) / len(v) for y, v in years.items()},
        }
    return dict(out)


def _opponents(game: Game, family: str) -> dict[str, list[Seat]]:
    out: dict[str, list[Seat]] = defaultdict(list)
    for s in game.seats:
        if family_of(s.policy) != family:
            out[family_of(s.policy)].append(s)
    return out


def _opponent_row(name: str, rows: list[Ours], pars: dict) -> dict:
    """Everything about one opponent policy; `rows` are all our seats (with and without them)."""
    variants = {r.game.variant for r in rows if name in r.opponents}
    together = [r for r in rows if name in r.opponents]
    apart = [r for r in rows if name not in r.opponents and r.game.variant in variants]
    by_game: dict[str, list[Ours]] = defaultdict(list)
    for r in together:
        by_game[r.game.episode].append(r)

    versions, their_scores, their_obs, paired = Counter(), [], [], []
    ahead = behind = tied = 0
    outgrew = []
    for episode, ours in by_game.items():
        game, theirs = ours[0].game, ours[0].opponents[name]
        versions.update({s.policy for s in theirs})
        their_scores += [s.score for s in theirs]
        their_x = [(episode, s.score - pars[game.variant][s.power]["score"]) for s in theirs]
        their_obs += their_x
        our_score = sum(r.seat.score for r in ours) / len(ours)
        their_score = sum(s.score for s in theirs) / len(theirs)
        ahead, behind, tied = (ahead + (our_score > their_score), behind + (our_score < their_score),
                               tied + (our_score == their_score))
        our_x = [r.vs_par for r in ours if r.par is not None]
        if our_x:
            paired.append((episode, sum(our_x) / len(our_x) - sum(v for _, v in their_x) / len(their_x)))
        our_centers = _mean(r.seat.final_centers for r in ours)
        their_centers = _mean(s.final_centers for s in theirs)
        if our_centers is not None and their_centers is not None:
            outgrew.append(their_centers > our_centers)

    by_ours, by_theirs, pairs = defaultdict(list), defaultdict(list), defaultdict(list)
    for r in together:
        if r.par is None:
            continue
        ob = (r.game.episode, r.vs_par)
        by_ours[r.seat.power].append(ob)
        for their_power in {s.power for s in r.opponents[name]}:
            by_theirs[their_power].append(ob)
            pairs[(r.seat.power, their_power)].append(ob)
    with_stat, without_stat = stat(_obs(together)), stat(_obs(apart))
    dates = sorted(r.game.date for r in together if r.game.date)
    return {
        "opponent": name, "versions": dict(sorted(versions.items())), "games": len(by_game),
        "first": dates[0] if dates else None, "last": dates[-1] if dates else None,
        "with": with_stat, "without": without_stat, "difference": difference(with_stat, without_stat),
        "their_score": _mean(their_scores), "their_vs_par": stat(their_obs),
        "head_to_head": sign_test(ahead, behind, tied),
        "paired": stat(paired),
        "eliminated_with": rate(r.seat.survived is False for r in together),
        "eliminated_without": rate(r.seat.survived is False for r in apart),
        "outgrew_us": rate(outgrew),
        "by_our_power": {p: stat(by_ours[p]) for p in POWER_NAMES if by_ours[p]},
        "by_their_power": {p: stat(by_theirs[p]) for p in POWER_NAMES if by_theirs[p]},
        "pairs": [{"ours": a, "theirs": b, "vs_par": stat(v)} for (a, b), v in
                  sorted(pairs.items(), key=lambda kv: (POWER_NAMES.index(kv[0][0]), POWER_NAMES.index(kv[0][1])))],
    }


def _trajectory(rows: list[Ours], pars: dict) -> list[dict]:
    out = []
    for variant in sorted({r.game.variant for r in rows}):
        years: dict[int, list[tuple[int, float]]] = defaultdict(list)
        for r in rows:
            if r.game.variant != variant:
                continue
            field_years = pars.get(variant, {}).get(r.seat.power, {}).get("centers_by_year", {})
            for year, centers in r.seat.centers_by_year.items():
                if year in field_years:
                    years[year].append((centers, field_years[year]))
        out.append({"variant": variant, "years": [
            {"year": y, "n": len(v), "ours": _round(sum(a for a, _ in v) / len(v), 2),
             "field": _round(sum(b for _, b in v) / len(v), 2),
             "diff": _round(sum(a - b for a, b in v) / len(v), 2),
             "se": _round(statistics.stdev(a - b for a, b in v) / math.sqrt(len(v)), 2) if len(v) > 1 else None}
            for y, v in sorted(years.items())]})
    return out


def _cost(rows: list[Ours]) -> dict:
    logs = [r.seat.log for r in rows if r.seat.log]
    llm = [lg for lg in logs if lg.get("llm_calls")]
    total = sum(lg.get("llm_cost_usd", 0.0) for lg in llm)
    return {"seats_with_log": len(logs), "llm_seats": len(llm),
            "usd_per_seat_game": _round(total / len(llm)) if llm else None, "usd_total": _round(total),
            "llm_calls": sum(lg["llm_calls"] for lg in llm), "llm_failed": sum(lg.get("llm_failed", 0) for lg in llm)}


def report(games: list[Game], policy: str, source: str = "all", variant: str | None = None,
           opponent: str | None = None) -> dict:
    """The whole dashboard for `policy` (`NAME` or `NAME:vN`) over `games`; see the module docstring."""
    family = family_of(policy)
    version = policy if policy != family else None

    def ours(s: Seat) -> bool:
        return s.policy == version if version else family_of(s.policy) == family

    in_scope = [g for g in games if (source == "all" or g.source == source) and (not variant or g.variant == variant)]
    missing = sum(g.missing_results for g in in_scope)  # no seats to read, so these may or may not be ours
    clean = [g for g in in_scope
             if not any(s.taint and (ours(s) or set(s.taint) & EPISODE_TAINTS) for s in g.seats)]
    # Par rests on every clean game in scope, with or without one of our seats and whatever the
    # opponent filter says, so a seat's score vs par does not move when the view is narrowed.
    pars = field_pars(clean, family)
    games = [g for g in in_scope if any(ours(s) for s in g.seats)]
    if opponent:
        games = [g for g in games if opponent in _opponents(g, family)]

    seen = [s for g in games for s in g.seats if ours(s)]
    flags = Counter(t for s in seen for t in s.taint)
    clean_ids = {id(g) for g in clean}
    kept = [g for g in games if id(g) in clean_ids]
    rows = []
    for g in kept:
        opponents = _opponents(g, family)
        for s in g.seats:
            if ours(s):
                rows.append(Ours(g, s, pars.get(g.variant, {}).get(s.power, {}).get("score"), opponents))

    variants = Counter(g.variant for g in kept)
    our_games: dict[str, list[Ours]] = defaultdict(list)
    for r in rows:
        our_games[r.game.episode].append(r)
    several = sum(len(v) > 1 for v in our_games.values())
    no_par = sum(r.par is None for r in rows)
    top = [max(r.seat.score for r in v) >= max(s.score for s in v[0].game.seats) for v in our_games.values()]

    caveats = ["Rows are not corrected for how many are shown: with dozens of rows some reach |z| >= 2 by chance.",
               "The SE treats par as exact; a par resting on few field seats adds uncertainty that is not shown.",
               "Opponent rows are associations: the power draw, the date and the rest of the table are mixed in."]
    if len(variants) > 1:
        caveats.insert(0, "Variants are mixed (" + ", ".join(f"{v} {n}" for v, n in sorted(variants.items()))
                       + " games): each seat is scored against its own variant's par, but read them separately.")
    if several:
        caveats.insert(0, f"{several} games seat more than one of our seats (paired runs): the level there is not "
                          "what one seat gets alone.")
    if no_par:
        caveats.insert(0, f"{no_par} of our seats played a power no field seat played, so they have no par and "
                          "are left out of every score-vs-par number.")

    def grouped(key) -> dict:
        groups: dict = defaultdict(list)
        for r in rows:
            groups[key(r)].append(r)
        return groups

    by_version = []
    for name, v in grouped(lambda r: r.seat.policy).items():
        dates = sorted(r.game.date for r in v if r.game.date)
        by_version.append({"policy": name, "version": name[len(family) + 1:] or None,
                           "first": dates[0] if dates else None, "last": dates[-1] if dates else None, **_summary(v)})
    by_version.sort(key=lambda row: (row["first"] or "", _version_key(row["policy"])))

    by_power = []
    power_rows = grouped(lambda r: r.seat.power)
    for power in POWER_NAMES:
        v = power_rows.get(power, [])
        par_values = [r.par for r in v if r.par is not None]
        by_power.append({"power": power, **_summary(v), "par": _mean(par_values),
                         "final_centers": _mean(r.seat.final_centers for r in v),
                         "eliminated": rate(r.seat.survived is False for r in v)})

    opponent_names = Counter(name for v in our_games.values() for name in v[0].opponents)
    return {
        "policy": policy, "version": version, "family": family,
        "filters": {"source": source, "variant": variant, "opponent": opponent},
        "games": len(our_games), "seats": len(rows), "variants": dict(sorted(variants.items())),
        "mixed_variants": len(variants) > 1, "several_of_ours_games": several, "no_par_seats": no_par,
        "caveats": caveats,
        "overall": {
            **_summary(rows),
            "raw_including_tainted": {"n": len(seen), "score": _mean(s.score for s in seen)},
            "final_centers": _mean(r.seat.final_centers for r in rows),
            "solo": rate(r.seat.solo for r in rows),
            "draw": rate(r.seat.outcome == "drawn" and bool(r.seat.survived) for r in rows),
            "eliminated": rate(r.seat.survived is False for r in rows),
            "survival": rate(bool(r.seat.survived) for r in rows if r.seat.survived is not None),
            "top_score": rate(top),
        },
        "par": {variant: {power: {"n": p["n"], "score": _round(p["score"]), "final_centers": p["final_centers"]}
                          for power, p in sorted(by.items(), key=lambda kv: POWER_NAMES.index(kv[0]))}
                for variant, by in pars.items()},
        "by_power": by_power,
        "by_version": by_version,
        "by_source": [{"source": k, **_summary(v)} for k, v in sorted(grouped(lambda r: r.game.source).items())],
        "by_variant": [{"variant": k, **_summary(v)} for k, v in sorted(grouped(lambda r: r.game.variant).items())],
        "by_segment": [{"variant": k[0], "source": k[1], **_summary(v)}
                       for k, v in sorted(grouped(lambda r: (r.game.variant, r.game.source)).items())],
        "by_opponent": [_opponent_row(name, rows, pars) for name, _ in
                        sorted(opponent_names.items(), key=lambda kv: (-kv[1], kv[0]))],
        "trajectory": _trajectory(rows, pars),
        "taint": {"seats_seen": len(seen), "flags": dict(sorted(flags.items())),
                  "games_dropped": len(games) - len(kept), "games_missing_results": missing},
        "cost": _cost(rows),
        "our_seats": [{
            "episode": r.game.episode, "date": r.game.date, "variant": r.game.variant, "source": r.game.source,
            "policy": r.seat.policy, "power": r.seat.power, "score": _round(r.seat.score), "par": _round(r.par),
            "vs_par": _round(r.vs_par), "final_centers": r.seat.final_centers,
            "opponents": {name: [s.power for s in seats] for name, seats in sorted(r.opponents.items())},
        } for r in sorted(rows, key=lambda r: (r.game.date or "", r.game.episode, r.seat.slot))],
    }


def _version_key(policy: str):
    match = re.search(r":v(\d+)$", policy)
    return (0, int(match.group(1))) if match else (1, policy)


def list_policies(games: list[Game]) -> list[dict]:
    """Every policy family in the data; those with seat logs on disk (ours) first, newest first."""
    out: dict[str, dict] = {}
    for g in games:
        for name in {family_of(s.policy) for s in g.seats}:
            seats = [s for s in g.seats if family_of(s.policy) == name]
            row = out.setdefault(name, {"name": name, "versions": set(), "seats": 0, "seats_with_log": 0,
                                        "games": 0, "latest": None, "variants": Counter(), "sources": Counter()})
            row["versions"].update(s.policy for s in seats)
            row["seats"] += len(seats)
            row["seats_with_log"] += sum(bool(s.log) for s in seats)
            row["games"] += 1
            row["latest"] = max(row["latest"] or "", g.date or "") or None
            row["variants"][g.variant] += 1
            row["sources"][g.source] += 1
    rows = [{**r, "versions": sorted(r["versions"], key=_version_key), "variants": dict(sorted(r["variants"].items())),
             "sources": dict(sorted(r["sources"].items()))} for r in out.values()]
    # Newest first, then policies with seat logs ahead of those without, then by name.
    rows.sort(key=lambda r: r["name"])
    rows.sort(key=lambda r: r["latest"] or "", reverse=True)
    rows.sort(key=lambda r: r["seats_with_log"] == 0)
    return rows


# --- text output ----------------------------------------------------------------------


def _signed(x: float | None, places: int = 3) -> str:
    return "-" if x is None else f"{x:+.{places}f}"


def _plain(x: float | None, places: int = 3) -> str:
    return "-" if x is None else f"{x:.{places}f}"


def _stat_cells(s: dict) -> str:
    z = "-" if s["z"] is None else f"{s['z']:+.2f}"
    return f"{s['n']}{'*' if s['low_n'] and s['n'] else ''} | {_signed(s['mean'])} | {_plain(s['se'])} | {z} | " \
           f"{s['verdict'] if s['n'] else '-'}"


def _pct(r: dict) -> str:
    return "-" if r["rate"] is None else f"{r['rate'] * 100:.0f}% ({r['k']}/{r['n']})"


def render(r: dict) -> str:
    o, f = r["overall"], r["filters"]
    scope = ", ".join(f"{k} {v}" for k, v in f.items() if v and v != "all") or "all sources and variants"
    lines = [f"# {r['policy']}: {r['games']} games, {r['seats']} of our seats ({scope})", ""]
    lines += [f"> {c}" for c in r["caveats"]]
    v = o["vs_par"]
    interval = f", 95% interval {_signed(v['ci'][0])} to {_signed(v['ci'][1])}" if v["ci"] else ""
    lines += ["", f"overall: score vs par {_signed(v['mean'])} ± {_plain(v['se'])} SE, z {v['z']}, n={v['n']}"
                  f"{interval}: **{v['verdict']}**",
              f"raw score {_plain(o['score'])} (parity 0.143; with tainted games put back "
              f"{_plain(o['raw_including_tainted']['score'])}, n={o['raw_including_tainted']['n']}) | "
              f"final centres {_plain(o['final_centers'], 2)} | solo {_pct(o['solo'])} | draw {_pct(o['draw'])} | "
              f"eliminated {_pct(o['eliminated'])} | top score {_pct(o['top_score'])}",
              f"taint: {r['taint']['flags'] or 'none'}; games dropped {r['taint']['games_dropped']}, "
              f"missing results {r['taint']['games_missing_results']}"]
    c = r["cost"]
    if c["llm_seats"]:
        lines.append(f"LLM cost: ${c['usd_per_seat_game']} per seat-game over {c['llm_seats']} seats "
                     f"({c['llm_failed']} of {c['llm_calls']} calls failed)")
    head = "n | vs par | SE | z | verdict"
    rule = "---|---|---|---|---"

    def table(title, first, items, label):
        if items:
            lines.extend(["", f"## {title}", "", f"| {first} | {head} | raw score |", f"|---|{rule}|---|"])
            lines.extend(f"| {label(i)} | {_stat_cells(i['vs_par'])} | {_plain(i['score'])} |" for i in items)

    table("By power", "power", r["by_power"], lambda i: i["power"])
    table("By version", "version", r["by_version"], lambda i: i["policy"])
    table("By variant and source", "segment", r["by_segment"], lambda i: f"{i['variant']} / {i['source']}")
    if r["by_opponent"]:
        lines += ["", "## By opponent", "",
                  "| opponent | games | ours with them | z | without | with - without | z | their vs par | "
                  "ahead-behind | z | ours - theirs (paired) | z |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for p in r["by_opponent"]:
            h, d = p["head_to_head"], p["difference"]
            lines.append(
                f"| {p['opponent']} | {p['games']}{'*' if p['with']['low_n'] else ''} | {_signed(p['with']['mean'])} "
                f"| {p['with']['z']} | {_signed(p['without']['mean'])} (n={p['without']['n']}) | {_signed(d['diff'])} "
                f"| {d['z']} | {_signed(p['their_vs_par']['mean'])} | {h['ahead']}-{h['behind']} | {h['z']} "
                f"| {_signed(p['paired']['mean'])} | {p['paired']['z']} |")
    for t in r["trajectory"]:
        if t["years"]:
            lines += ["", f"## Centres by year end, {t['variant']} (ours / field at the same powers)", "",
                      " ".join(f"{y['year']}: {y['ours']}/{y['field']}" for y in t["years"])]
    lines += ["", f"\\* fewer than {LOW_N} seats: directional only. |z| < 2 is no result."]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dirs", nargs="+", help="episode directories or roots holding them")
    ap.add_argument("--policy", help="our policy: NAME (every version) or NAME:vN")
    ap.add_argument("--source", choices=(*SOURCES, "all"), default="all")
    ap.add_argument("--variant", help="for example classic-press or classic-gunboat")
    ap.add_argument("--opponent", help="only games that also seat this opponent policy (NAME)")
    ap.add_argument("--list", action="store_true", help="list the policies in the data and exit")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    games = load_games([Path(d) for d in args.dirs])
    policies = list_policies(games)
    if args.list or not args.policy:
        if not args.list:
            print("--policy is required; policies in this data:", file=sys.stderr)
        if args.json:
            print(json.dumps(policies, indent=1))
        else:
            for p in policies:
                versions = ", ".join(v[len(p["name"]) + 1:] or v for v in p["versions"])
                print(f"{p['name']}: {p['games']} games, versions {versions}, {p['seats_with_log']} of "
                      f"{p['seats']} seats with a log, latest {p['latest'] or 'local'}")
        return 0 if args.list else 2
    result = report(games, args.policy, args.source, args.variant, args.opponent)
    if not result["taint"]["seats_seen"]:
        print(json.dumps({"error": "no seats for this policy and these filters",
                          "policies": [p["name"] for p in policies]}))
        return 2
    print(json.dumps(result, indent=1) if args.json else render(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
