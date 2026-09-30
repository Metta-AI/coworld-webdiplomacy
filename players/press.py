"""Private seat history. Run in a bounded worker so artifact I/O cannot delay exit."""

import io
import json
import os
import time
import zipfile

from adapter.artifacts import write_artifact
from players.api import WebDiplomacy


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
                write_artifact(
                    uri,
                    buffer.getvalue(),
                    "COWORLD_PLAYER_ARTIFACT_UPLOAD_METHOD",
                    content_type="application/zip",
                    timeout=3,
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
