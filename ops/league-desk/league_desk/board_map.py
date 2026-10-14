"""The board: the optimizer IDE's Map tab over cached public facts. No artifact I/O here.

Views and their numbers follow `games/webdiplomacy/tools/map_stats.py` in the optimizer lab, with a
win view and a player filter added. A phase is a movement phase (`S1901`, `A1901`, ...), and a game
counts toward a phase when it reached it. The report is JSON for `static/board-map.js`:

    {games, pending (route only), minimum, player, players: [{id, name, games}], powers: {country: name},
     provinces: {id: {name, supply, home}}, phases: [block], all: block}
    block = {key, label, n, score: {country: {mean, se, n}}, win: {country: {rate, wins, solos, n}},
             contest: {province: [contested, n]}, held: {province: {country: count}}}

`n` in a block counts games reaching the phase (game-phases for `all`); score and win carry their own
per-power `n`, which differs from the block's under a player filter.
"""
import math
from collections import Counter, defaultdict

from .config import MIN_SHARED_GAMES
from .game_metrics import fmt
from .optimizer_tools import POWERS

COUNTRY = {name: country for country, name in POWERS.items()}


def phase_key(turn):
    """Turn 0 -> `S1901`, turn 1 -> `A1901`, turn 2 -> `S1902`."""
    return f"{'SA'[turn % 2]}{1901 + turn // 2}"


def phase_label(key):
    return f"{'Spring' if key[0] == 'S' else 'Autumn'} {key[1:]}"


def centre_scores(held, provinces):
    """Each power's league score (centres² over the sum of squares) if the game ended with this board."""
    centres = {country: sum(provinces[str(p)][1] for p in ids) for country, ids in held.items()}
    total = sum(n * n for n in centres.values())
    return {str(c): (centres.get(str(c), 0) ** 2 / total if total else 1 / 7) for c in POWERS}


def win_shares(values):
    """One win per game: the top value takes it, and tied leaders split it equally."""
    top = max(values.values())
    leaders = [c for c, v in values.items() if abs(v - top) < 1e-9]
    return {c: (1 / len(leaders) if c in leaders else 0.0) for c in values}


def map_entries(snapshot, games):
    """Usable games: complete, untainted scores that agree with the API, and a parsed replay board.
    Returns (entries, pending): `pending` counts scored games whose replay board is not parsed yet."""
    from .board_metrics import score_facts

    entries, pending = [], 0
    for game_id, game in games.items():
        results = (snapshot.get(("artifact_results", game_id), {}).get("data") or {}).get("facts")
        accepted = score_facts(game, results) if results else []
        if not accepted:
            continue
        board = ((snapshot.get(("artifact_replay", game_id), {}).get("data") or {}).get("facts") or {}).get("board")
        if not board or not board["phases"]:
            pending += 1
            continue
        api = {s["slot"]: s for s in game["seats"]}
        seats = defaultdict(list)
        for seat in accepted:
            owner = api[seat["slot"]]
            # Fillers stand in for a missing entrant; like head-to-head, they are not the player's games.
            if owner.get("player_id") and not owner.get("filler"):
                seats[owner["player_id"]].append(str(COUNTRY[seat["power"]]))
        names = {s["player_id"]: s.get("player") or "Unnamed player" for s in game["seats"] if s.get("player_id")}
        entries.append({"game": game_id, "completed_at": game["completed_at"], "board": board, "seats": dict(seats),
                        "names": names, "final": {str(COUNTRY[s["power"]]): s["score"] for s in accepted},
                        "solo": {str(COUNTRY[s["power"]]) for s in accepted if s["solo"]}})
    return entries, pending


def mean_se(values):
    n = len(values)
    mean = sum(values) / n
    sd = math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1)) if n > 1 else None
    return {"mean": mean, "se": sd / math.sqrt(n) if sd is not None else None, "n": n}


def block(key, label, n, scores, wins, solos, contested, held):
    return {"key": key, "label": label, "n": n,
            "score": {c: mean_se(values) for c, values in sorted(scores.items()) if values},
            "win": {c: {"rate": sum(values) / len(values), "wins": sum(values), "solos": solos[c], "n": len(values)}
                    for c, values in sorted(wins.items()) if values},
            "contest": {p: [contested.get(p, 0), n] for p in sorted(contested, key=int)},
            "held": {p: dict(sorted(counts.items())) for p, counts in sorted(held.items(), key=lambda kv: int(kv[0]))}}


def map_report(entries, player=""):
    """The board's numbers for all players, or for one player: score and win only on the powers that player
    played (non-filler seats), contest and held only over games they were in."""
    players = {}
    for entry in sorted(entries, key=lambda e: e["completed_at"]):
        for player_id in entry["seats"]:
            players[player_id] = entry["names"].get(player_id, "Unnamed player")
    counts = Counter(player_id for entry in entries for player_id in entry["seats"])
    if player:
        entries = [e for e in entries if player in e["seats"]]

    def powers_of(entry):
        """The powers whose score and win count for this game: all seven, or the chosen player's."""
        return entry["seats"][player] if player else [str(c) for c in POWERS]

    provinces = {}
    for entry in entries:
        provinces.update(entry["board"]["provinces"])
    by_phase = defaultdict(list)
    for entry in entries:
        for phase in entry["board"]["phases"]:
            by_phase[phase["turn"]].append((entry, phase))
    phases, all_contested, all_held, phase_count = [], Counter(), defaultdict(Counter), 0
    for turn in sorted(by_phase):
        rows = by_phase[turn]
        scores, wins, contested, held = defaultdict(list), defaultdict(list), Counter(), defaultdict(Counter)
        for entry, phase in rows:
            values = centre_scores(phase["held"], entry["board"]["provinces"])
            shares = win_shares(values)
            for country in powers_of(entry):
                scores[country].append(values[country])
                wins[country].append(shares[country])
            contested.update(str(p) for p in phase["contested"])
            for country, ids in phase["held"].items():
                for p in ids:
                    held[str(p)][country] += 1
        key = phase_key(turn)
        phases.append(block(key, phase_label(key), len(rows), scores, wins, Counter(), contested, held))
        all_contested.update(contested)
        for p, holders in held.items():
            all_held[p].update(holders)
        phase_count += len(rows)
    finals, final_wins, solos = defaultdict(list), defaultdict(list), Counter()
    for entry in entries:
        shares = win_shares(entry["final"])
        for country in powers_of(entry):
            finals[country].append(entry["final"][country])
            final_wins[country].append(shares[country])
            solos[country] += country in entry["solo"]
    everything = block("all", "All phases", phase_count, finals, final_wins, solos, all_contested, all_held)
    everything["games"] = len(entries)
    return {"games": len(entries), "minimum": MIN_SHARED_GAMES, "player": player,
            "players": [{"id": k, "name": v, "games": counts[k]} for k, v in sorted(players.items(),
                                                                                   key=lambda kv: kv[1].lower())],
            "powers": {str(c): name for c, name in POWERS.items()},
            "provinces": {p: {"name": v[0], "supply": v[1], "home": v[2]}
                          for p, v in sorted(provinces.items(), key=lambda kv: int(kv[0]))},
            "phases": phases, "all": everything}


def board_map_panel(report, pending):
    """Server-rendered reading and table for the map widget; the widget itself fetches /board-map."""
    final = report["all"]
    if not report["games"]:
        sentence = ("No scored games with a parsed replay board in this selection."
                    + (f" {pending} scored games await a parsed replay." if pending else ""))
    else:
        names = {p: v["name"] for p, v in report["provinces"].items()}
        contest = max(final["contest"].items(), key=lambda kv: (kv[1][0], -int(kv[0])), default=None)
        eligible = {c: w for c, w in final["win"].items() if w["n"] >= MIN_SHARED_GAMES}
        sentence = f"{report['games']} scored games."
        if eligible:
            country, best = max(eligible.items(), key=lambda kv: kv[1]["rate"])
            sentence += f" {report['powers'][country]} wins most often: {best['rate']:.0%} of {best['n']} games."
        if contest and contest[1][0]:
            sentence += (f" {names[contest[0]]} is fought over most: {contest[1][0] / contest[1][1]:.0%} "
                         "of movement phases.")
    rows = [[report["powers"][c], final["score"][c]["n"], fmt(final["score"][c]["mean"]),
             f"{final['win'][c]['rate']:.0%}", f"{final['win'][c]['wins']:.1f}", final["win"][c]["solos"]]
            for c in final["score"]]
    return {"sentence": sentence, "chart": None, "games": report["games"],
            "columns": ["Power", "Games", "Mean final score", "Win rate", "Wins", "Solos"], "rows": rows,
            "note": "Views: contested provinces, win, mean score by power and who holds each province, per movement "
                    "phase or over all phases. A win is the solo, else the top final score; tied leaders split it "
                    "(two tied are ½ each). In a phase, the win goes to the power with the most supply centres "
                    "then, and the score is the league rule (centres² over the sum of squares) if the game had "
                    "ended there. Contested: two or more powers' units moving into or staying in a province in one "
                    "movement phase. Choosing a player shows score and win on the powers they played (fillers "
                    "excluded) and contest/held over their games; cells under five games are marked. "
                    + (f"{pending} scored games await a parsed replay. " if pending else "")
                    + "Games with taints or score conflicts are excluded."}
