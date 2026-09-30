"""Embed the canonical public docs in the authored manifest; run from the repo root."""

import json
from pathlib import Path


def sync():
    path = Path("coworld_manifest_template.json")
    manifest = json.loads(path.read_text())
    game = manifest["game"]
    for target, key, source in (
        (game["docs"], "readme", "README.md"),
        (game["protocols"], "player", "docs/protocol.md"),
        (game["protocols"], "global", "docs/replay.md"),
    ):
        target[key] = {"type": "text", "value": Path(source).read_text()}
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    sync()
