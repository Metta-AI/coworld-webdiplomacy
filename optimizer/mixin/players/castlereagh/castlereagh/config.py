"""Live tunables for DumbBot, the search and the press layer.

Defaults are the lab's Kissinger personality (`OPP_MODEL_LEVEL = 1`, everything else at
the search defaults), which is what `CASTLEREAGH_POLICY=search` plays. Override any value
at runtime with `CASTLEREAGH_OVERRIDES="KEY=VAL,KEY=VAL"` (see bot.apply_overrides).
Config is a live module: components read it on every decision.
"""

import os

PROXIMITY_DEPTHS = 10

# Power size = a*n^2 + b*n + c, n = supply centres owned.
SIZE_SQUARE = 1.0
SIZE_LINEAR = 4.0
SIZE_CONSTANT = 16.0

# "uno": unowned centres count as one pseudo-power sized by how many remain (DAIDE UNO).
# "zero": the MIT port's behaviour (neutral centres have no attack value).
NEUTRAL_SIZE_MODE = "uno"

SPRING_ATTACK_WEIGHT = 700
SPRING_DEFENSE_WEIGHT = 300
FALL_ATTACK_WEIGHT = 600
FALL_DEFENSE_WEIGHT = 400

SPRING_PROXIMITY_WEIGHTS = [100, 1000, 30, 10, 6, 5, 4, 3, 2, 1]
FALL_PROXIMITY_WEIGHTS = [1000, 100, 30, 10, 6, 5, 4, 3, 2, 1]

STRENGTH_WEIGHT = 1000
COMPETITION_WEIGHT = 1000
BUILD_DEFENSE_WEIGHT = 1000

ALTERNATIVE_DIFF_MODIFIER = 5
PLAY_ALTERNATIVE = 0.5

# --- Search (ownership: README.md "Module map") ---
SEARCH_OPPONENT_SAMPLES = 16
SEARCH_SEEDS = 12
SEARCH_PASSES = 6
# Wall-clock budget per movement decision. WEBDIP_SEARCH_BUDGET_S supplies the default.
SEARCH_TIME_BUDGET_S = float(os.environ.get("WEBDIP_SEARCH_BUDGET_S", "20"))
SEARCH_SC_WEIGHT = 10.0
SEARCH_POS_WEIGHT = 1.0
SEARCH_DISLODGED_WEIGHT = 3.0
SEARCH_PAIRS = 1  # joint move+support alternatives
SEARCH_CONVOYS = 1  # joint convoyed-move + convoy alternatives
# Opponent model: "dumbbot" (always DumbBot samples) or "adaptive" (per-power Bayesian mix of
# DumbBot vs uniform-random legal orders, learned from each power's past orders).
OPP_MODEL = "adaptive"
OPP_PRIOR_LOGODDS = 0.0
OPP_LOGODDS_CLIP = 8.0
# Search objective: "sc" (our projected centres) or "share" (projected SC^2 share x34).
SEARCH_OBJECTIVE = "sc"
# Opponent sophistication: 0 = DumbBot samples; 1 = each DumbBot sample improved by one pass
# of that power's own best response (Kissinger, the measured best: level 0 lost 0.135 and
# level 2 lost 0.11 per seat in the lab).
OPP_MODEL_LEVEL = 1
SEARCH_RISK = 0.0  # 0 = mean over opponent samples; 1 = worst case
# Opponent-belief likelihood: "competent" (sensible orders count as competent; +0.106 per
# seat in the lab) or "dumbbot" (only DumbBot-matching orders do).
OPP_LIKELIHOOD = "competent"
# With OPP_MODEL_LEVEL=1: probability that a given opponent sample is the improved (level-1)
# plan rather than the raw DumbBot plan. Mixes below 1.0 lost in the lab; the knob stays
# because its random draw is part of the search's RNG stream (golden test).
OPP_LEVEL1_SHARE = 1.0
# Implicit diplomacy (no-press): hostility memory from public history. Off in Kissinger.
DIPLO = 0
DIPLO_DECAY = 0.7      # per movement phase
DIPLO_HOSTILE = 1.0    # decayed attacks at/above this = hostile
DIPLO_GRUDGE = 0.5     # extra centre-value for taking a hostile power's centre
DIPLO_PEACE = 0.6      # centre-value discount for taking a peaceful power's centre
DIPLO_STAB_YEAR = 1905 # peace discount applies before this year

# --- Press layer (press/): see press/README section in ../README.md ---
# Limits start generous ("set all limits high, then tighten" once logs show what is used).
PRESS_SOUL = "castlereagh"          # press/souls/<name>/SOUL.md
PRESS_MODEL = "z-ai/glm-5.3-flash"  # local default; hosted uses COWORLD_LLM_MODEL (fixed per upload)
PRESS_REASONING = "low"             # OpenRouter reasoning effort ("" = provider default)
PRESS_TEMPERATURE = 0.4             # None omits it (the sidecar requires every sent parameter be supported)
PRESS_MAX_TOKENS = 6000             # per model call; some models reason past 2000 and return nothing
PRESS_CALL_TIMEOUT_S = 55.0         # per model call (the sidecar's upstream timeout is 60 s)
PRESS_REQUEST_LIMIT = 30            # model calls per wake
PRESS_WAKE_SECONDS = 120.0          # wall-clock limit per wake
PRESS_MAX_WAKES = 20                # per movement phase, phase start included
PRESS_DEBOUNCE_S = 5.0              # wait for this much quiet after new press before waking
PRESS_MAX_DEBOUNCE_S = 15.0         # but never delay a wake longer than this after the first unread message
PRESS_MIN_WAKE_S = 8.0              # no wake shorter than this
PRESS_FINAL_MARGIN_S = 12.0         # orders saved with Ready this long before the deadline
PRESS_POLL_S = 1.0                  # how often new press is checked between wakes
PRESS_MAX_MESSAGES_PER_PHASE = 30
PRESS_MAX_MESSAGE_CHARS = 800
PRESS_NOTE_CHARS = 4000             # per note key
PRESS_STATE_DIR = "/tmp/castlereagh"  # per-game notes, kept across bot restarts within a game

# Per-model sidecar quirks, verified hosted in the lab (docs: webdiplomacy-gameplay.md, "LLM
# players"). The sidecar forces provider.require_parameters=true, so an unsupported parameter
# fails EVERY call and the seat silently plays its floor. Matched by substring of the model
# name; the first match wins and overrides the PRESS_* defaults above.
MODEL_QUIRKS = [
    ("gpt-6-luna", {"PRESS_TEMPERATURE": None}),          # rejects temperature
    ("claude-haiku-5.5", {"PRESS_TEMPERATURE": None}),    # rejects temperature
    ("gemini-3.5-flash-lite", {"PRESS_REASONING": "low"}),  # rejects reasoning off
    ("deepseek", {"PRESS_REASONING": "none"}),            # reasons past the cap even at "low"; too slow
]
