#!/usr/bin/env bash
# Build the Castlereagh reference policy image for linux/amd64 and print its tag.
#
#   tools/build.sh --tag <image-tag> [--ref <game-ref>] [--policy press|search]
#                  [--overrides "KEY=VAL,KEY=VAL"]
#
# Two steps, both linux/amd64:
#   1. the coworld-webdiplomacy player base image, built straight from GitHub at
#      <game-ref> (adapter/Dockerfile.player; no checkout or submodule needed);
#   2. players/castlereagh on top of it, with CASTLEREAGH_POLICY baked in from --policy
#      (default press; a press image plays its search core in no-press games).
# --overrides bakes CASTLEREAGH_OVERRIDES into the image, so a one-knob experiment (any
# config.py value) needs no source edit. The bot logs the overrides in its `start` line.
# Only the final image tag goes to stdout; build output goes to stderr.
#
# PINNED_GAME_REF rationale: coworld-webdiplomacy 7e16afa1 (main after PR #16) has the launcher
# that logs `child_exit` when the bot process ends before the game, which the analysis tools
# count as a crash. It needs at least b4aca731 (PR #9), the first commit whose launcher passes
# WEBDIP_END_YEAR and WEBDIP_SCORING to bots, which the press layer's briefing reads. Its
# players/api.py and players/legal_orders.py are the versions
# vendored into castlereagh/ (identical since c2f691a1). Bump it deliberately: re-sync
# those two files if they changed, rerun the golden test, and log the bump in VERSION_LOG.md.
#
# linux/amd64 is mandatory: the platform hard-checks it, and an arm64 image will upload
# but fail to start in hosted episodes.
set -euo pipefail

PINNED_GAME_REF="7e16afa1aa7e56388c885a694ae3443a6ed1d77e"
GAME_REPO="https://github.com/Metta-AI/coworld-webdiplomacy.git"
GAME_REF="$PINNED_GAME_REF"
POLICY="press"
TAG=""
OVERRIDES=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --ref) GAME_REF="$2"; shift 2 ;;
    --tag) TAG="$2"; shift 2 ;;
    --policy) POLICY="$2"; shift 2 ;;
    --overrides) OVERRIDES="$2"; shift 2 ;;
    -h|--help) sed -n '2,/^set -euo/p' "${BASH_SOURCE[0]}" | sed '$d' | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

case "$POLICY" in
  search|press) ;;
  *) echo "--policy must be search or press, not '$POLICY'" >&2; exit 2 ;;
esac
if [[ -z "$TAG" ]]; then
  # No default tag: a shared default such as ":latest" gets rebuilt while games are running,
  # and later games then run the new code under the old name. One tag per experiment.
  echo "build.sh: --tag is required, e.g. --tag webdip-<policy>:<one-change-slug>" >&2
  exit 2
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "build.sh: docker is not installed. Building and uploading policies need Docker;" \
       "editing, analysis and tests (python3 -m unittest discover -s players/castlereagh/tests) do not." >&2
  exit 3
fi
if ! docker info >/dev/null 2>&1; then
  echo "build.sh: the Docker daemon is not running (or this user cannot reach it). Start Docker and retry;" \
       "editing, analysis and tests do not need it." >&2
  exit 3
fi

LAB_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# One base tag per game ref, so different refs never overwrite each other's base.
BASE_TAG="coworld-webdiplomacy-player:${GAME_REF:0:12}"

docker build --platform linux/amd64 \
  -f adapter/Dockerfile.player \
  -t "$BASE_TAG" \
  "$GAME_REPO#$GAME_REF" >&2

docker build --platform linux/amd64 \
  --build-arg "BASE_IMAGE=$BASE_TAG" \
  --build-arg "POLICY=$POLICY" \
  --build-arg "OVERRIDES=$OVERRIDES" \
  --label "webdiplomacy.game_ref=$GAME_REF" \
  --label "castlereagh.policy=$POLICY" \
  --label "castlereagh.overrides=$OVERRIDES" \
  -t "$TAG" \
  "$LAB_ROOT/players/castlereagh" >&2

echo "$TAG"
