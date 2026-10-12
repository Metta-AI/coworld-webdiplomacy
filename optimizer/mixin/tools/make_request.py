#!/usr/bin/env python3
"""Write a hosted eval request body from a named field set.

One help screen serves both kinds: `paired --help` and `field --help` print this same text.
Each option's help says which kind it applies to.

    python3 games/webdiplomacy/tools/make_request.py paired --a NAME:vN --b NAME:vM \\
        --field-set <paired set> -n 16 --note "experiment id" --out .runtime/requests/x.json
    python3 games/webdiplomacy/tools/make_request.py field --a NAME:vN \\
        --field-set <field set> -n 16 --out .runtime/requests/y.json

`paired` seats A and B in the same games plus five field seats (the lab's
default A/B design; analyze with tools/paired.py). `field` seats A alone plus
six field seats (analyze with tools/wd.py metrics).

`--balanced` pins powers with `game_config_overrides.countries` and fixed roster slots and
rotates the assignment by one power per body, so every roster seat plays every power
exactly `-n` times and no result depends on which powers a policy happened to draw (shuffled
powers can give one policy a power 3 times and another 18 times in 80 games). For a
field eval that is seven bodies (`-r0` .. `-r6`). **For a paired A/B it is fourteen**: each
rotation is written twice, once with A in seat 0 and B in seat 1 (`-r0` ..) and once with
the two swapped (`-r0m` ..). The swap is required, not optional: under a cyclic rotation
seat 0 always holds the power "before" seat 1 on the board (England/France, France/Italy,
...), and seat 0's other neighbour is a field bot while seat 1's is our own second seat.
Identical code in the two seats can read as a real difference in that unmirrored
design. Mirroring gives each of A and B both positions equally. `-n` is
the episode count per body (paired total = 14 x n; field total = 7 x n).
The field seats are put in a different order in each rotation (a fixed shuffle seeded
by the rotation number, so two arms built with the same field set get the same orders).
Without that, a cyclic rotation gives every seat the same two roster neighbours, and
therefore the same two board neighbours, in every game.
`--no-maps` sets `render_maps: false`. Measured 2026-10-10: this only trims a gunboat
replay from about 12 MB to about 10 MB, because the bulk is the cumulative `history` and
the `variant` map repeated in every frame, not the PNGs.

`--config KEY=VALUE` (repeatable) puts any other episode setting into `game_config_overrides`,
on top of the variant's own. The platform checks the keys and values against the game's
config schema. The settings that shorten a game are `end_year` (1901 or later),
`phase_minutes` (movement phases) and `retreat_build_minutes`, in whole minutes from 1:

    ... --config end_year=1903 --config phase_minutes=2

A press game lasts about 2 x phase_minutes for each year played, plus its retreat and build
phases. A game with changed settings is not the league's game: read it for health and
behaviour, not for score (the eval-design binding, "Faster first reads").

`--pin-a POWER` (field kind only) is the role-pinned probe: A plays POWER in every game.
It writes SIX bodies (`-p0` .. `-p5`), rotating the six field seats through the other six
powers, so the field's power draw is balanced too. `-n` is episodes per rotation (total =
6 x n). Run it once per arm for a separate-arms A/B on one power (analyze with
tools/compare.py).

Field sets live in `games/webdiplomacy/field_sets.json`: a name mapped to a
league key, a variant, and a list of {label, policy_ref}. Keeping them in one
file is what makes "same opponent set across a campaign" checkable: the set's
name goes into the request notes and the experiment record. Then dry-run and
create with skills/run-eval/scripts/eval_request.py. The version ids in a field set go
stale when the league's fillers change; a stale id fails at create time (the dry run
only checks the body's shape), so regenerate the set with tools/field.py when that happens. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

LAB = Path(__file__).resolve().parent.parent
LEAGUES = {
    "press": "league_1bccc63d-cd0a-47d7-92d7-e762797b5f1c",
    "gunboat": "league_428e91e5-ee25-4f9c-be5e-a4fc4f993f17",
}
FIELD_SEATS = {"paired": 5, "field": 6}
# Per-episode cap, split evenly over the seven seats. It is a cap, not a charge: `wd.py costs`
# prints what the seats spent.
PRESS_LLM_BUDGET_USD = 14.0
POWERS = ["England", "France", "Italy", "Germany", "Austria", "Turkey", "Russia"]  # upstream ids 1..7


def default_llm_budget(field: dict) -> float:
    """A press game with a zero budget gives every LLM seat no model access: each then plays
    its fallback with no error. So press sets get a budget unless one is given."""
    return PRESS_LLM_BUDGET_USD if field["league"] == "press" else 0.0


def load_field_sets(path: Path | None = None) -> dict:
    """Named opponent sets; keys starting with "_" (such as "_note") are comments."""
    data = json.loads((path or LAB / "field_sets.json").read_text())
    return {name: value for name, value in data.items() if not name.startswith("_")}


def parse_config(pairs: list[str]) -> dict:
    """`KEY=VALUE` pairs as a dict; a value is read as JSON, or kept as text when it is not JSON."""
    config = {}
    for pair in pairs:
        key, separator, value = pair.partition("=")
        if not key or not separator:
            raise ValueError(f"--config takes KEY=VALUE, not {pair!r}")
        try:
            config[key] = json.loads(value)
        except json.JSONDecodeError:
            config[key] = value
    return config


def build_bodies(kind: str, a: str, b: str | None, field: dict, field_set: str, episodes: int, note: str = "",
                 llm_budget_usd: float = 0.0, balanced: bool = False, pin_a: str | None = None,
                 no_maps: bool = False, config: dict | None = None) -> list[tuple[str, dict]]:
    """The request bodies for one eval, as (file-name suffix, body) pairs. Raises ValueError on a bad combination."""
    if any(seat["policy_ref"].startswith("<") for seat in field["seats"]):
        raise ValueError(f"set {field_set!r} still has placeholder ids; list the field with tools/field.py and "
                         "fill field_sets.json with real policy version ids")
    if len(field["seats"]) != FIELD_SEATS[kind]:
        raise ValueError(f"{kind} needs {FIELD_SEATS[kind]} field seats; set {field_set!r} has {len(field['seats'])}")
    if (kind == "paired") != bool(b):
        raise ValueError("--b is required for paired and not allowed for field")
    if pin_a and (kind != "field" or balanced):
        raise ValueError("--pin-a needs the field kind and excludes --balanced")

    ours = [a] + ([b] if b else [])
    what = f"paired A/B {a} vs {b}" if b else f"field eval {a}"
    if balanced:
        # (rotation, mirrored): a paired A/B needs both seat orders (see the module docstring).
        plans = [(r, m) for r in range(7) for m in ((False, True) if b else (False,))]
    elif pin_a:
        plans = [(r, False) for r in range(6)]
    else:
        plans = [(None, False)]

    bodies = []
    for rotation, mirrored in plans:
        field_refs = [seat["policy_ref"] for seat in field["seats"]]
        if rotation is not None:
            # Same seed for the same rotation, so the mirrored body and the other arm match.
            random.Random(rotation).shuffle(field_refs)
        order = (list(reversed(ours)) if mirrored else ours) + field_refs
        body = {
            "private": True,
            "target": {"league_id": LEAGUES[field["league"]], "variant_id": field["variant"]},
            "num_episodes": episodes,
            "episode_player_llm_spend_limit_usd": llm_budget_usd,
            "roster": [{"player": {"policy_ref": ref}, "slot": -1} for ref in order],
            "notes": f"{what}, field set {field_set}" + (f", {note}" if note else ""),
        }
        overrides: dict = {"render_maps": False} if no_maps else {}
        suffix = ""
        if rotation is not None:
            # countries[slot] = upstream country id (1..7) for that roster slot; slots are fixed
            # so the pin means something.
            for slot, seat in enumerate(body["roster"]):
                seat["slot"] = slot
        if pin_a:
            mine = POWERS.index(pin_a) + 1
            others = [c for c in range(1, 8) if c != mine]
            overrides["countries"] = [mine] + [others[(i + rotation) % 6] for i in range(6)]
            body["notes"] += f", A pinned to {pin_a}, field rotation {rotation}/6"
            suffix = f"-p{rotation}"
        elif rotation is not None:
            # Rotation r gives seat i the power (i + r) % 7 + 1.
            overrides["countries"] = [(slot + rotation) % 7 + 1 for slot in range(7)]
            body["notes"] += f", balanced rotation {rotation}/7" + (", seats mirrored" if mirrored else "")
            suffix = f"-r{rotation}{'m' if mirrored else ''}"
        if config:
            if set(config) & set(overrides):
                raise ValueError(f"--config repeats a setting another option already sets: "
                                 f"{sorted(set(config) & set(overrides))}")
            overrides.update(config)
            body["notes"] += ", config " + " ".join(f"{key}={json.dumps(value)}" for key, value in config.items())
        if overrides:
            body["game_config_overrides"] = overrides
        bodies.append((suffix, body))
    return bodies


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kind", choices=sorted(FIELD_SEATS),
                    help="paired: A and B in the same games plus five field seats; field: A alone plus six")
    ap.add_argument("--a", required=True, help="both kinds: the candidate, NAME:vN")
    ap.add_argument("--b", help="paired only (required there): the baseline, NAME:vM")
    ap.add_argument("--field-set", required=True,
                    help="both kinds: a set name from field_sets.json, with five seats for paired and six for field")
    ap.add_argument("-n", "--episodes", type=int, required=True,
                    help="both kinds: games per body (one body, or one per rotation with --balanced or --pin-a)")
    ap.add_argument("--note", default="", help="both kinds: text added to the request notes, e.g. the experiment id")
    ap.add_argument("--llm-budget-usd", type=float,
                    help=f"both kinds: per-episode LLM budget split over seven seats (0 = no LLM access). Default: "
                         f"{PRESS_LLM_BUDGET_USD:g} for a press set, 0 for a gunboat set")
    ap.add_argument("--balanced", action="store_true",
                    help="both kinds: pinned, rotated powers: 7 bodies (field) or 14 mirrored bodies (paired); "
                         "-n is per body")
    ap.add_argument("--pin-a", choices=POWERS,
                    help="field only: A always plays this power; six bodies; not with --balanced")
    ap.add_argument("--no-maps", action="store_true", help="both kinds: game_config_overrides.render_maps = false")
    ap.add_argument("--config", action="append", default=[], metavar="KEY=VALUE",
                    help="both kinds: another game_config_overrides setting, JSON-parsed value; "
                         "end_year=1903 and phase_minutes=2 give a shorter game (no score read)")
    ap.add_argument("--variant", help="both kinds: use this variant instead of the field set's, e.g. "
                                      "classic-press-short for a one-game health check")
    ap.add_argument("--out", required=True,
                    help="both kinds: the body's path; with several bodies a suffix goes before .json "
                         "(-r0, -r0m, -p0)")
    args = ap.parse_args(argv)

    sets = load_field_sets()
    if args.field_set not in sets:
        sys.exit(f"unknown field set {args.field_set!r}; known: {sorted(sets)}")
    field = sets[args.field_set]
    if args.variant:
        field = {**field, "variant": args.variant}
    try:
        config = parse_config(args.config)
        bodies = build_bodies(args.kind, args.a, args.b, field, args.field_set, args.episodes, args.note,
                              default_llm_budget(field) if args.llm_budget_usd is None else args.llm_budget_usd,
                              args.balanced, args.pin_a, args.no_maps, config)
    except ValueError as error:
        sys.exit(str(error))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    for suffix, body in bodies:
        path = out.with_name(f"{out.stem}{suffix}{out.suffix}")
        path.write_text(json.dumps(body, indent=1) + "\n")
        print(f"wrote {path}: n={args.episodes}, field {[s['label'] for s in field['seats']]}")


if __name__ == "__main__":
    main()
