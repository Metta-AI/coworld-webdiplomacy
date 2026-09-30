#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Resolve and confine the clean-build destination before removing stale assets.
python3 - "$repo_dir" "$1" <<'PY'
from pathlib import Path
import shutil
import sys
root = Path(sys.argv[1]).resolve()
out = Path(sys.argv[2])
allowed = (root / 'build', root / 'dist' / 'build')
if not out.is_absolute() or not any(out.resolve().is_relative_to(base) and out.resolve() != base for base in allowed):
    raise SystemExit('bundle output must be a directory below the package build directory')
if out.is_symlink():
    raise SystemExit('bundle output cannot be a symlink')
if out.exists():
    shutil.rmtree(out)
out.mkdir(parents=True)
for source, target in [('adapter/viewer.html', 'index.html'), ('adapter/client/viewer.js', 'viewer.js')]:
    shutil.copyfile(root / source, out / target)
PY
# The base-map resource uses indexing colors. Use the native sample rendered at
# image bake time, with country colors and province labels, in both live and replay.
docker compose -f "$repo_dir/compose.yaml" build game >&2
container="$(docker create --platform linux/amd64 coworld-webdiplomacy-game:latest)"
trap 'docker rm "$container" >/dev/null' EXIT
docker cp "$container:/opt/adapter/client/smallmap.png" "$1/smallmap.png"
