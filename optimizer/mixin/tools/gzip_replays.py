#!/usr/bin/env python3
"""Compress fetched replays in place (about 20x smaller), keeping their file names.

    python3 games/webdiplomacy/tools/gzip_replays.py DIR...

A hosted gunboat replay is about 10 MB of JSON even with map rendering off,
because every frame repeats the cumulative history and the map. It gzips to
about 0.5 MB. `tools/webdip_episodes.py` sniffs the first bytes, so the lab's
tools read the compressed file under the same name. Only episodes with a
`.done` marker are touched (a replay still downloading is left alone), and
files that are already gzip are skipped. Standard library only.
"""

import argparse
import gzip
import json
from pathlib import Path

REPLAY_NAMES = ("replay.json", "replay.bin", "replay")
GZIP_MAGIC = b"\x1f\x8b"


def compress_replays(roots: list[Path]) -> tuple[int, int]:
    """Gzip every plain replay under a fetched (`.done`) episode. Returns (files compressed, bytes saved)."""
    files = saved = 0
    for root in roots:
        for done in Path(root).rglob(".done"):
            for name in REPLAY_NAMES:
                path = done.parent / name
                if not path.is_file():
                    continue
                raw = path.read_bytes()
                if raw[:2] == GZIP_MAGIC:
                    continue
                packed = gzip.compress(raw, compresslevel=6)
                path.write_bytes(packed)
                files += 1
                saved += len(raw) - len(packed)
    return files, saved


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dirs", nargs="+", metavar="DIR", help="artifact directories to search for fetched episodes")
    args = ap.parse_args(argv)
    files, saved = compress_replays([Path(root) for root in args.dirs])
    print(json.dumps({"replays_compressed": files, "mb_saved": round(saved / 2**20, 1)}))


if __name__ == "__main__":
    main()
