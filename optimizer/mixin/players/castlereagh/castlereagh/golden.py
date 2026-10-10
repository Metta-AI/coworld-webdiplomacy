"""Golden behaviour contract for the search.

Records the exact orders the search chooses on a fixed set of real positions with fixed
seeds and no time budget, and checks that the current code reproduces them bit for bit.
Any refactor of the search must pass `check` unchanged; a deliberate behaviour change
must re-record the corpus and say so in VERSION_LOG.md.

    python -m castlereagh.golden check tests/golden.json        # from players/castlereagh
    python -m castlereagh.golden record REPLAY_ROOT tests/golden.json   # (re)create

`REPLAY_ROOT/*/*/replay` are local `coworld run-episode` replays. The corpus (recorded in
the lab at commit 1c2d81fa) covers movement phases (several turns, powers, unit counts),
three opponent-belief states (empty prior, all-competent, all-random) and winter builds,
for two configurations: "kissinger" (the default config) and "machiavelli" (level-0
opponents). 167 cases x 2 = 334 decisions.
"""

import glob
import json
import random
import sys

# Golden policy name -> config overrides on top of the defaults (names kept from the lab corpus).
POLICIES = {"kissinger": {}, "machiavelli": {"OPP_MODEL_LEVEL": 0}}
BELIEFS = {
    "prior": None,
    "competent": 8.0,
    "random": -8.0,
}


def _board(variant, units, centers):
    parent = {t["id"]: t["coastParentID"] for t in variant["territories"]}
    unit_at = {parent[u["terrID"]]: u["id"] for u in units}
    owner = {c["terrID"]: c["countryID"] for c in centers}
    terrs = [
        {"terrID": t["id"], "ownerCountryID": owner.get(t["id"], 0), "unitID": unit_at.get(t["id"]),
         "standoff": False, "occupiedFromTerrID": None}
        for t in variant["territories"] if t["coast"] != "Child"
    ]
    return {"units": units, "territories": terrs}


_DEFAULTS = None


def choose(policy, variant, case):
    from castlereagh import config
    from castlereagh.search import SearchBot

    global _DEFAULTS
    if _DEFAULTS is None:
        _DEFAULTS = {k: v for k, v in vars(config).items() if k.isupper()}
    for k, v in _DEFAULTS.items():  # reset per case: overrides mutate the config module
        setattr(config, k, list(v) if isinstance(v, list) else v)
    for k, v in POLICIES[policy].items():
        setattr(config, k, v)
    config.SEARCH_TIME_BUDGET_S = 1e9  # determinism: never stop on wall clock
    board = _board(variant, case["units"], case["centers"])
    rng = random.Random(case["seed"])
    bot = SearchBot(variant, board, case["country"], case["phase"], case["turn"], rng)
    lo = BELIEFS[case["belief"]]
    bot.memory = {"logodds": {str(c): lo for c in range(1, 8)} if lo is not None else {}, "pending": None}
    return bot.choose(case["slots"])


def signature(orders):
    return [[o["type"], o.get("terrID"), o.get("toTerrID"), o.get("fromTerrID"), str(o.get("viaConvoy"))]
            for o in orders]


def _cases(root):
    paths = sorted(glob.glob(f"{root}/*/*/replay"))
    picked = [paths[i] for i in range(0, len(paths), max(1, len(paths) // 4))][:4]
    variant = None
    cases = []
    for k, path in enumerate(picked):
        with open(path) as f:
            frames = json.load(f)
        variant = frames[-1]["variant"]
        phases = frames[-1]["history"]["phases"]
        movement = [p for p in phases if p["phase"] == "Diplomacy" and p["units"]]
        for ph in [movement[i] for i in (0, 3, 8, 13) if i < len(movement)]:
            units = [{"id": i + 1, "countryID": u["countryID"], "type": u["type"], "terrID": u["terrID"],
                      "retreating": False} for i, u in enumerate(ph["units"]) if not u.get("retreating")]
            countries = sorted({u["countryID"] for u in units})
            for country in countries[k % 2::3]:
                slots = [{"unitID": u["id"]} for u in units if u["countryID"] == country]
                for belief in BELIEFS:
                    cases.append({"kind": "movement", "phase": "Diplomacy", "turn": ph["turn"], "country": country,
                                  "units": units, "centers": ph["centers"], "slots": slots, "belief": belief,
                                  "seed": 1000 * k + ph["turn"] * 10 + country})
        builds = [p for p in phases if p["phase"] == "Builds" and p["units"]]
        for ph in builds[:2]:
            units = [{"id": i + 1, "countryID": u["countryID"], "type": u["type"], "terrID": u["terrID"],
                      "retreating": False} for i, u in enumerate(ph["units"]) if not u.get("retreating")]
            for country in range(1, 8):
                n_units = sum(u["countryID"] == country for u in units)
                n_centers = sum(c["countryID"] == country for c in ph["centers"])
                delta = n_centers - n_units
                if delta:
                    cases.append({"kind": "builds", "phase": "Builds", "turn": ph["turn"], "country": country,
                                  "units": units, "centers": ph["centers"], "belief": "prior",
                                  "slots": [{"unitID": None}] * min(abs(delta), 3), "seed": 7 * country + ph["turn"]})
    return variant, cases


def record(root, out):
    variant, cases = _cases(root)
    for case in cases:
        case["expected"] = {p: signature(choose(p, variant, case)) for p in POLICIES}
    with open(out, "w") as f:
        json.dump({"variant": variant, "policies": list(POLICIES), "cases": cases}, f)
    print(json.dumps({"recorded": len(cases), "out": out}))


def check(path, case_filter=None):
    """Return (checked, mismatch descriptions). `case_filter(index)` limits the cases run."""
    with open(path) as f:
        data = json.load(f)
    checked, bad = 0, []
    for i, case in enumerate(data["cases"]):
        if case_filter is not None and not case_filter(i):
            continue
        for p in data["policies"]:
            checked += 1
            if signature(choose(p, data["variant"], case)) != case["expected"][p]:
                bad.append(f"case {i} ({case['kind']} t{case['turn']} c{case['country']} {case['belief']}) {p}")
    return checked, bad


if __name__ == "__main__":
    if sys.argv[1] == "record":
        record(sys.argv[2], sys.argv[3])
    else:
        n, mismatches = check(sys.argv[2])
        for line in mismatches[:5]:
            print("MISMATCH", line)
        print(json.dumps({"checked": n, "mismatches": len(mismatches)}))
        sys.exit(1 if mismatches else 0)
