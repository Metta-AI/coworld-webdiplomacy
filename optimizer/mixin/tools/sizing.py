#!/usr/bin/env python3
"""How many games an A/B needs, from a standard deviation of the score.

    python3 games/webdiplomacy/tools/sizing.py --effect 0.04              # paired, press league
    python3 games/webdiplomacy/tools/sizing.py --effect 0.04 --separate   # two separate arms
    python3 games/webdiplomacy/tools/sizing.py --games 84                 # smallest effect 84 games can see
    python3 games/webdiplomacy/tools/sizing.py --games 84 --league gunboat

The lab's rule is "|z| < 2 is no result", so the question is how many games put a
true effect of a given size at z = 2 (a coin flip to reach the bar) or at z = 2.8
(about 80% chance to reach it).

Default standard deviations, per league (`--league`, default press):
- press: 0.20 for a paired difference, 0.15 per seat.
- gunboat: 0.34 for a paired difference, 0.22 per seat.
These are STARTING VALUES, not facts about the game. Each was measured once (hosted games,
2026-10-10/11, the reference policy against one or two opponent sets), and the spread
depends on your policy and your field. Replace them with your own as soon as you have a
batch, and again after a field change:

    python3 games/webdiplomacy/tools/paired.py DIR --a NAME:vN --b NAME:vM    # prints `sd` (paired)
    python3 games/webdiplomacy/tools/wd.py metrics DIR --policy NAME:vN        # per power: SE x sqrt(n) (per seat)

and pass it with `--sd`. The platform's `coworld power-analysis` assumes win/loss ratings
and does not fit this score-share game.
Standard library only.
"""

import argparse
import math

# league -> (SD of a paired difference, SD per seat). Starting values measured once; see the module docstring.
LEAGUE_SD = {"press": (0.20, 0.15), "gunboat": (0.34, 0.22)}
Z_EVEN = 2.0      # a true effect here reaches |z| >= 2 half the time
Z_POWER_80 = 2.8  # ... and here about 80% of the time (2 + 0.84)


def difference_sd(sd: float, separate: bool) -> float:
    """SD of the measured difference per sqrt(game): paired = sd; two separate arms = sd * sqrt(2)."""
    return sd * (math.sqrt(2) if separate else 1.0)


def games_needed(effect: float, sd: float, separate: bool, z: float) -> int:
    """Games (per arm when separate) that put a true `effect` at `z` standard errors."""
    # The small subtraction keeps an exact answer (128.0000000001) from rounding up a whole game.
    return math.ceil((z * difference_sd(sd, separate) / effect) ** 2 - 1e-9)


def smallest_effect(games: int, sd: float, separate: bool, z: float) -> float:
    """The effect that `games` (per arm when separate) put at `z` standard errors."""
    return z * difference_sd(sd, separate) / math.sqrt(games)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--effect", type=float, help="true score difference to detect, e.g. 0.04")
    ap.add_argument("--games", type=int, help="instead: games available (per arm for --separate)")
    ap.add_argument("--separate", action="store_true", help="two separate arms instead of paired seating")
    ap.add_argument("--league", choices=sorted(LEAGUE_SD), default="press", help="whose default SDs to use")
    ap.add_argument("--sd", type=float, help="override the standard deviation (paired difference, or per seat)")
    args = ap.parse_args(argv)
    if (args.effect is None) == (args.games is None):
        ap.error("give exactly one of --effect or --games")

    paired_sd, seat_sd = LEAGUE_SD[args.league]
    sd = args.sd or (seat_sd if args.separate else paired_sd)
    what = "games per arm (separate arms)" if args.separate else "paired games"
    if args.effect is not None:
        for z, label in ((Z_EVEN, "50% chance to reach |z| >= 2"), (Z_POWER_80, "80% chance to reach |z| >= 2")):
            print(f"effect {args.effect:+.3f}, SD {sd}: {games_needed(abs(args.effect), sd, args.separate, z)} "
                  f"{what} for a {label}")
    else:
        se = smallest_effect(args.games, sd, args.separate, 1.0)
        print(f"{args.games} {what}, SD {sd}: SE of the difference {se:.3f}; smallest effect at z = 2 is "
              f"{smallest_effect(args.games, sd, args.separate, Z_EVEN):.3f}, at 80% power "
              f"{smallest_effect(args.games, sd, args.separate, Z_POWER_80):.3f}")
    if not args.sd:
        print(f"SD {sd} is this tool's starting value for {args.league}, not your field's: "
              "pass --sd from your own batch (paired.py prints `sd`)")


if __name__ == "__main__":
    main()
