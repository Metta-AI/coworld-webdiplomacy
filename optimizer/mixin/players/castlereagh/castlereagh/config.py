"""Live tunables for DumbBot, the search and the press layer.

The defaults are what `CASTLEREAGH_POLICY=search` plays, and the golden test
(tests/test_golden.py) pins the orders they produce. Override any value at runtime with
`CASTLEREAGH_OVERRIDES="KEY=VAL,KEY=VAL"` (see bot.apply_overrides). Config is a live
module: components read it on every decision.
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
# of that power's own best response.
OPP_MODEL_LEVEL = 1
SEARCH_RISK = 0.0  # 0 = mean over opponent samples; 1 = worst case
# Opponent-belief likelihood: "competent" (any sensible order counts as competent) or
# "dumbbot" (only DumbBot-matching orders do).
OPP_LIKELIHOOD = "competent"
# With OPP_MODEL_LEVEL=1: probability that a given opponent sample is the improved (level-1)
# plan rather than the raw DumbBot plan. Its random draw is part of the search's RNG stream,
# so the golden test depends on the draw being made even at 1.0.
OPP_LEVEL1_SHARE = 1.0

# --- Press layer (press/): see "Press layer" in ../README.md ---
# The limits are generous on purpose; tighten them once your logs show what a wake uses.
PRESS_SOUL = "default"              # press/souls/<name>/SOUL.md: the first part of the system prompt
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

# Per-model request settings. The sidecar forces provider.require_parameters=true, so a
# parameter the model does not support fails EVERY call and the seat silently plays its floor.
# Matched by substring of the model name; the first match wins and overrides the PRESS_*
# defaults above. Add an entry when a new model fails its health game on a parameter.
MODEL_QUIRKS = [
    ("gpt-6-luna", {"PRESS_TEMPERATURE": None}),          # rejects temperature
    ("claude-haiku-5.5", {"PRESS_TEMPERATURE": None}),    # rejects temperature
    ("gemini-3.5-flash-lite", {"PRESS_REASONING": "low"}),  # rejects reasoning off
    ("deepseek", {"PRESS_REASONING": "none"}),            # reasons past the token cap even at "low"
]
