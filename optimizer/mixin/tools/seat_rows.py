#!/usr/bin/env python3
"""One row per seat of a policy, with what happened to it and who sat beside it.

    python3 games/webdiplomacy/tools/seat_rows.py DIR... --policy NAME[:vN] [--as POWER] [--versus OTHER]
        [--variant classic-press] [--episodes FILE] [--sort score|episode] [--limit N] [--json]

`matchups.py` and `opponent_profile.py` print tables over many games. This prints the games
themselves, one line per seat, so "our five worst games as Austria" or "every game where it
was Turkey beside our Russia" is one command and not a script:

    seat_rows.py $A --policy ours --as Austria --variant classic-press --limit 5

Each row has the episode, the version, the power, the score, the final centres and the centres
after each year, the seat's taint and whether another seat in the game is tainted (a crashed
neighbour is free centres), its first targets with the season and whether it was replying, the
year it first lost a home centre, and how many movement phases it only held at the end. Rows
are sorted by score, lowest first (`--sort episode` for a stable order); `--limit N` keeps the
first N, so the default prints the worst games.

With `--versus OTHER` (a policy name), only games that also seat OTHER are kept, and each row
adds one line per seat of OTHER: its power and version, its score and final centres, who
finished ahead, the first hostile act each way with its season, and the centres each took from
the other. A game with two seats of OTHER gives two lines. Those lines name the two policies
(`--policy` and OTHER, without versions) and never say "we" or "it": the tool is run both
ways round, with our policy as `--policy` and with an opponent as `--policy`.

Every row ends with a replay link (`/replays/<episode id>?seat=<slot>`), which opens the game
from that seat in the IDE; `opponent_profile.py --game <episode id>` prints it in the terminal.
`--episodes FILE` reads only the games of a saved `matchups.py` or `opponent_profile.py` run.
Field names are those of `opponent_profile.seat_facts` (its docstring lists them); the same
limits apply (the last autumn's captures are not in the replay; a "hostile act" can be a
bounce). Rows only: scores against par, SEs and z come from `matchups.py`. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from opponent_profile import family, load_games, mark_replies, policy_matcher, read_episode_list, seat_facts
from press_audit import turn_label
from webdip_episodes import POWERS

POWER_NAMES = tuple(POWERS.values())


def _season(turn: int | None) -> str | None:
    return turn_label(turn) if turn is not None else None


def seat_rows(games, policy: str, power: str | None = None, versus: str | None = None) -> list[dict]:
    is_policy = policy_matcher(policy)
    is_other = policy_matcher(versus) if versus else None
    rows = []
    for game in games:
        if is_other and not any(is_other(s.policy) for s in game.seats):
            continue
        if not any(is_policy(s.policy) and (power is None or s.power == power) for s in game.seats):
            continue
        facts = {seat.slot: seat_facts(game, seat) for seat in game.seats}
        mark_replies(facts)
        for seat in game.seats:
            if not is_policy(seat.policy) or (power and seat.power != power):
                continue
            mine = facts[seat.slot]
            row = {
                "episode": game.episode, "source": game.source, "policy": seat.policy, "power": seat.power,
                "slot": seat.slot, "score": seat.score, "final_centers": seat.final_centers,
                "centers_by_year": mine["centers_by_year"], "taint": mine["taint"],
                "other_seats_tainted": sorted(f"{s.power} {s.policy}: {','.join(s.taint)}"
                                              for s in game.seats if s is not seat and s.taint),
                "first_targets": {q.title(): _season(mine["first_hostile"][q]) for q in mine["first_targets"]},
                "replying_to": [q.title() for q in mine["replying_to"]],
                "home_lost_year": mine["home_lost_year"], "eliminated_year": mine["eliminated_year"],
                "held_at_end_phases": mine["idle_end"], "rival_solo": mine["rival_solo"],
                "table": mine["table"], "link": f"/replays/{game.episode}?seat={seat.slot}",
            }
            if is_other:
                me = seat.power.upper()
                row["versus"] = []
                for other in game.seats:
                    if other is seat or not is_other(other.policy):
                        continue
                    theirs, them = facts[other.slot], other.power.upper()
                    # Keys say "policy" for the --policy seat and "other" for the --versus seat: either
                    # may be ours, so none says "we" or "it".
                    row["versus"].append({
                        "policy": other.policy, "power": other.power, "score": other.score,
                        "final_centers": other.final_centers,
                        "policy_finished": "ahead" if seat.score > other.score
                        else "behind" if seat.score < other.score else "level",
                        "other_first_hostile_act_on_policy": _season(theirs["first_hostile"].get(me)),
                        "policy_first_hostile_act_on_other": _season(mine["first_hostile"].get(them)),
                        "other_took_from_policy": theirs["taken_from"].get(me, 0),
                        "policy_took_from_other": mine["taken_from"].get(them, 0),
                        "other_taint": theirs["taint"],
                    })
            rows.append(row)
    return rows


def render(rows: list[dict]) -> str:
    lines = []
    for r in rows:
        years = " ".join(str(c) for _, c in sorted(r["centers_by_year"].items()))
        targets = ", ".join(f"{q} {when}" + (" (in reply)" if q in r["replying_to"] else "")
                            for q, when in r["first_targets"].items()) or "none"
        notes = [f"taint {','.join(r['taint'])}"] if r["taint"] else []
        notes += [f"other seats tainted: {'; '.join(r['other_seats_tainted'])}"] if r["other_seats_tainted"] else []
        notes += [f"home centre first lost {r['home_lost_year']}"] if r["home_lost_year"] else []
        notes += [f"only held in its last {r['held_at_end_phases']} movement phases"] \
            if r["held_at_end_phases"] >= 4 else []
        notes += ["a rival soloed"] if r["rival_solo"] else []
        lines.append(f"{r['episode']} {r['policy']} {r['power']}: score {r['score']:.3f}, {r['final_centers']} centres "
                     f"(by year {years}); first targets: {targets}" + ("; " + "; ".join(notes) if notes else "")
                     + f" [{r['link']}]")
        for v in r.get("versus", []):
            a, b = family(r["policy"]), family(v["policy"])
            lines.append(f"    {v['policy']} {v['power']}: score {v['score']:.3f}, {v['final_centers']} centres; {a} "
                         f"finished {v['policy_finished']}; first hostile act: {b} on {a} "
                         f"{v['other_first_hostile_act_on_policy'] or 'never'}, {a} on {b} "
                         f"{v['policy_first_hostile_act_on_other'] or 'never'}; {b} took "
                         f"{v['other_took_from_policy']} from {a}, {a} took {v['policy_took_from_other']} from {b}"
                         + (f"; {b} taint {','.join(v['other_taint'])}" if v["other_taint"] else ""))
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dirs", nargs="+", metavar="DIR")
    ap.add_argument("--policy", required=True, help="NAME (every version) or NAME:vN; ours or an opponent")
    ap.add_argument("--as", dest="power", choices=POWER_NAMES, help="only its seats at this power")
    ap.add_argument("--versus", metavar="OTHER",
                    help="only games that also seat this policy, with its side of each game")
    ap.add_argument("--variant", help="only this variant, for example classic-press or classic-gunboat")
    ap.add_argument("--episodes", metavar="FILE", help="only the episode ids in FILE (a saved run, or one id per line)")
    ap.add_argument("--sort", choices=("score", "episode"), default="score", help="score: lowest first (default)")
    ap.add_argument("--limit", type=int, metavar="N", help="only the first N rows after sorting")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    only = read_episode_list(Path(args.episodes)) if args.episodes else None
    games, _ = load_games([Path(d) for d in args.dirs], args.variant, only)
    rows = seat_rows(games, args.policy, args.power, args.versus)
    if not rows:
        print(f"no seat of {args.policy} below the given directories (with these filters)", file=sys.stderr)
        return 2
    rows.sort(key=lambda r: (r["score"], r["episode"]) if args.sort == "score" else (r["episode"], r["slot"]))
    rows = rows[: args.limit] if args.limit else rows
    print(json.dumps(rows, indent=1) if args.json else render(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
