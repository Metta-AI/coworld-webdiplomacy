"""Private seat history, and the bot's own files, in the seat's player artifact. Run in a
bounded worker so artifact I/O cannot delay exit."""

import io
import json
import os
import time
import zipfile
from pathlib import Path

from adapter.artifacts import write_artifact
from players.api import WebDiplomacy

# A bot may write files of its own (a decision trace, say) under this directory during the game;
# the worker bundles them beside private-press.json at game over. The launcher passes its
# environment to the bot, so both read the same name. The platform's artifact cap is 200 MiB.
ARTIFACT_DIR_ENV = "COWORLD_PLAYER_ARTIFACT_DIR"
DEFAULT_ARTIFACT_DIR = "/tmp/coworld-player-artifact"
BUNDLE_MAX_BYTES = 150 * 1024 * 1024
UPLOAD_TIMEOUT_S = 10  # inside the launcher's 12 s worker budget


def bundle_directory(archive, directory, max_bytes=BUNDLE_MAX_BYTES):
    """Add every regular file under `directory` to the open ZIP, named relative to it, in sorted
    order, until `max_bytes` of file size are in. Symlinks and special files are skipped, and so
    is a file that cannot be read. Returns {"files", "bytes", "skipped"}, or None when the
    directory does not exist (a bot that writes nothing changes nothing)."""
    directory = Path(directory)
    if not directory.is_dir():
        return None
    report = {"files": 0, "bytes": 0, "skipped": 0}
    for path in sorted(p for p in directory.rglob("*") if not p.is_symlink() and p.is_file()):
        try:
            size = path.stat().st_size
            if report["bytes"] + size > max_bytes:
                report["skipped"] += 1
                continue
            archive.write(path, arcname=path.relative_to(directory).as_posix())
        except OSError:
            report["skipped"] += 1
            continue
        report["files"] += 1
        report["bytes"] += size
    return report


class PressArchive:
    def __init__(self, api):
        self.api = api
        self.messages = {}
        self.snapshot_at = None

    def snapshot(self):
        context = self.api.context()  # No cursor or turn filter: full retained history.
        for message in context["messages"]["messages"]:
            self.messages[message["id"]] = message
        self.snapshot_at = time.time()

    def finish(self, reason):
        complete = False
        try:
            self.snapshot()
            complete = reason == "game_over"
        except (OSError, ValueError, KeyError):
            pass
        record = {
            "game_id": self.api.game_id,
            "country_id": self.api.country_id,
            "complete": complete,
            "coverage": "full_final_fetch" if complete else "best_available_snapshot",
            "reason": reason,
            "snapshot_at": self.snapshot_at,
            "messages": sorted(self.messages.values(), key=lambda item: item["id"]),
        }
        data = json.dumps(record).encode()
        print(json.dumps({"event": "private_press", "archive": record}), flush=True)
        if uri := os.environ.get("COWORLD_PLAYER_ARTIFACT_UPLOAD_URL"):
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("private-press.json", data)
                try:
                    report = bundle_directory(archive, os.environ.get(ARTIFACT_DIR_ENV) or DEFAULT_ARTIFACT_DIR)
                except (OSError, ValueError):
                    report = {"error": "bundle_failed"}  # the press archive still goes up
                if report is not None:
                    print(json.dumps({"event": "player_artifact_files", **report}), flush=True)
            try:
                write_artifact(
                    uri,
                    buffer.getvalue(),
                    "COWORLD_PLAYER_ARTIFACT_UPLOAD_METHOD",
                    content_type="application/zip",
                    timeout=UPLOAD_TIMEOUT_S,
                )
                print('{"event":"private_press_upload","status":"complete"}', flush=True)
            except (OSError, ValueError):
                # Presigned URLs and response bodies can contain credentials.
                print('{"event":"private_press_upload","status":"failed"}', flush=True)


def collect(webdip, control):
    api = WebDiplomacy(webdip["base_url"], webdip["api_key"], webdip["game_id"], webdip["country_id"], timeout=2)
    archive = PressArchive(api)
    while True:
        try:
            archive.snapshot()
        except (OSError, ValueError, KeyError):
            pass
        if control.poll(2):
            archive.finish(control.recv())
            return
