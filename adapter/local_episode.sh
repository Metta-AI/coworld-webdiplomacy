#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
RUN_ID="webdip-local-$(date +%s)"
GAME_NAME="$RUN_ID-game"
ARTIFACT_DIR="$ROOT/runs/$RUN_ID"
mkdir -p "$ARTIFACT_DIR"
python3 - "$ARTIFACT_DIR" <<'PY'
import json, sys
from pathlib import Path
Path(sys.argv[1], 'config.json').write_text(json.dumps({'tokens':[f'local-seat-{i}' for i in range(7)], 'max_phases':6, 'action_timeout_seconds':30}))
PY
docker network create "$RUN_ID" >/dev/null
docker run -d --network "$RUN_ID" --network-alias game --name "$GAME_NAME" -p 127.0.0.1::8080 \
    -e COGAME_CONFIG_URI=file:///artifacts/config.json \
    -e COGAME_RESULTS_URI=file:///artifacts/results.json \
    -e COGAME_SAVE_REPLAY_URI=file:///artifacts/replay.json \
    -e COGAME_PLAYER_FAILURE_URI=file:///artifacts/player-failure.json \
    --mount "type=bind,source=$ARTIFACT_DIR,target=/artifacts" \
    --mount "type=bind,source=$ROOT/adapter,target=/adapter,readonly" coworld-webdiplomacy-local
PORT=$(docker port "$GAME_NAME" 8080/tcp)
for attempt in $(seq 1 120); do
    if curl --fail --silent "http://$PORT/healthz" >/dev/null; then break; fi
    sleep 1
done
curl --fail --silent "http://$PORT/healthz"
for slot in 0 1 2 3 4 5 6; do
    docker run -d --name "$RUN_ID-player-$slot" --network "$RUN_ID" \
        -e "COWORLD_PLAYER_WS_URL=ws://game:8080/player?slot=$slot&token=local-seat-$slot" \
        --mount "type=bind,source=$ROOT/adapter,target=/adapter,readonly" \
        --entrypoint python coworld-webdiplomacy-player-local /adapter/player.py
done
for attempt in $(seq 1 120); do
    if [ -f "$ARTIFACT_DIR/results.json" ]; then break; fi
    sleep 1
done
cat "$ARTIFACT_DIR/results.json"
docker logs "$GAME_NAME" > "$ARTIFACT_DIR/game.log" 2>&1
for slot in 0 1 2 3 4 5 6; do
    test "$(docker wait "$RUN_ID-player-$slot")" = 0
    docker logs "$RUN_ID-player-$slot" > "$ARTIFACT_DIR/player-$slot.log" 2>&1
done
test "$(docker wait "$GAME_NAME")" = 0
docker run -d --name "$RUN_ID-replay" -p 127.0.0.1::8080 \
    -e COGAME_LOAD_REPLAY_URI=file:///artifacts/replay.json \
    --mount "type=bind,source=$ARTIFACT_DIR,target=/artifacts,readonly" \
    --mount "type=bind,source=$ROOT/adapter,target=/adapter,readonly" coworld-webdiplomacy-local
REPLAY_PORT=$(docker port "$RUN_ID-replay" 8080/tcp)
printf '\nViewer: http://%s/client/replay\nArtifacts: %s\nReplay container: %s\n' "$REPLAY_PORT" "$ARTIFACT_DIR" "$RUN_ID-replay"
