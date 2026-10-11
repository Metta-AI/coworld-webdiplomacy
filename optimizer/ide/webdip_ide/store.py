"""The IDE's files: chat between the user and the agent, agent cards, replay annotations.

Everything is plain JSON on disk so the agent can also read it with `cat`. The web
server, the agent's CLI commands and the Claude Code hooks are separate processes;
they all go through this module, and every write holds an exclusive file lock.

Standard library only (hooks import it without `uv`).

Files, under `paths.state_dir()` unless noted:
  chat.jsonl      one message per line: {seq, id, ts, sender: "user"|"agent", text, context}
                  `context` is optional and names what the user was looking at, for example
                  {"episode": "...", "phase": 7, "annotations": ["a1f"]}.
  agent_cursor    the `seq` of the last user message delivered to the agent.
  cards.jsonl     things the agent shows the user: {seq, id, ts, kind, title, body, link}
                  kind: "idea" | "replay" | "report" | "result" | "note"; `body` is Markdown;
                  `link` is an IDE path such as "/replays/<episode>?phase=7".
  agent_seen      touched whenever the agent side runs (hook, CLI, MCP): its presence signal.
  annotations/<episode id>.json   (in `paths.annotations_dir()`, tracked by git)
                  a list of {id, ts, author: "user"|"agent", phase, power, territory, tag,
                  text}. `phase` indexes the replay's last frame `history.phases`; `power`
                  and `territory` are optional names. tag: "blunder" | "missed-alliance" |
                  "bad-trust" | "good" | "suggestion" | "question" | "note".
"""

from __future__ import annotations

import fcntl
import json
import os
import secrets
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from . import paths

SENDERS = ("user", "agent")
CARD_KINDS = ("idea", "replay", "report", "result", "note")
ANNOTATION_TAGS = ("blunder", "missed-alliance", "bad-trust", "good", "suggestion", "question", "note")


@contextmanager
def _locked(path: Path):
    """Hold an exclusive lock for a read-modify-write on `path`."""
    with open(path.with_name(path.name + ".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def _read_lines(path: Path) -> list[dict]:
    """Every complete row. Readers take no lock, so a last line still being written is skipped."""
    if not path.exists():
        return []
    text = path.read_text()
    complete = text if text.endswith("\n") else text[: text.rfind("\n") + 1]
    return [json.loads(line) for line in complete.splitlines() if line.strip()]


def _write_atomic(path: Path, text: str) -> None:
    """Replace `path` in one step, so an unlocked reader never sees a partial file.

    The scratch name is this writer's own: two processes (a hook and a CLI command) may
    write the same file at once, and a shared name would let one rename the other's away.
    """
    temporary = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    temporary.write_text(text)
    os.replace(temporary, path)


def _append(path: Path, row: dict) -> dict:
    with _locked(path):
        row = {"seq": len(_read_lines(path)) + 1, "id": secrets.token_hex(4), "ts": time.time(), **row}
        with open(path, "a") as out:
            out.write(json.dumps(row) + "\n")
    return row


# --- chat ---


def post_message(sender: str, text: str, context: dict | None = None) -> dict:
    if sender not in SENDERS:
        raise ValueError(f"sender must be one of {SENDERS}")
    row = {"sender": sender, "text": text}
    if context:
        row["context"] = context
    return _append(paths.state_dir() / "chat.jsonl", row)


def messages(after: int = 0) -> list[dict]:
    return [m for m in _read_lines(paths.state_dir() / "chat.jsonl") if m["seq"] > after]


def take_unread_for_agent() -> list[dict]:
    """User messages the agent has not been given yet. Marks them delivered."""
    cursor = paths.state_dir() / "agent_cursor"
    with _locked(cursor):
        seen = int(cursor.read_text()) if cursor.exists() else 0
        unread = [m for m in messages(after=seen) if m["sender"] == "user"]
        if unread:
            _write_atomic(cursor, str(unread[-1]["seq"]))
    return unread


def has_unread_for_agent() -> bool:
    cursor = paths.state_dir() / "agent_cursor"
    seen = int(cursor.read_text()) if cursor.exists() else 0
    return any(m["sender"] == "user" for m in messages(after=seen))


# --- agent presence ---


def touch_agent_seen() -> None:
    _write_atomic(paths.state_dir() / "agent_seen", str(time.time()))


def agent_seen() -> float | None:
    try:
        return float((paths.state_dir() / "agent_seen").read_text())
    except (OSError, ValueError):
        return None


# --- cards ---


def post_card(kind: str, title: str, body: str = "", link: str | None = None) -> dict:
    if kind not in CARD_KINDS:
        raise ValueError(f"kind must be one of {CARD_KINDS}")
    return _append(paths.state_dir() / "cards.jsonl", {"kind": kind, "title": title, "body": body, "link": link})


def cards(after: int = 0) -> list[dict]:
    return [c for c in _read_lines(paths.state_dir() / "cards.jsonl") if c["seq"] > after]


# --- annotations ---


def _annotation_path(episode: str) -> Path:
    if "/" in episode or episode.startswith("."):
        raise ValueError(f"bad episode id: {episode!r}")
    return paths.annotations_dir() / f"{episode}.json"


def annotations(episode: str) -> list[dict]:
    path = _annotation_path(episode)
    return json.loads(path.read_text()) if path.exists() else []


def all_annotations() -> dict[str, list[dict]]:
    return {path.stem: json.loads(path.read_text()) for path in sorted(paths.annotations_dir().glob("*.json"))}


def add_annotation(
    episode: str,
    author: str,
    text: str,
    tag: str = "note",
    phase: int | None = None,
    power: str | None = None,
    territory: str | None = None,
) -> dict:
    if author not in SENDERS:
        raise ValueError(f"author must be one of {SENDERS}")
    if tag not in ANNOTATION_TAGS:
        raise ValueError(f"tag must be one of {ANNOTATION_TAGS}")
    path = _annotation_path(episode)
    row = {
        "id": secrets.token_hex(4),
        "ts": time.time(),
        "author": author,
        "phase": phase,
        "power": power,
        "territory": territory,
        "tag": tag,
        "text": text,
    }
    with _locked(path):
        rows = annotations(episode)
        rows.append(row)
        _write_atomic(path, json.dumps(rows, indent=1) + "\n")
    return row


def delete_annotation(episode: str, annotation_id: str) -> bool:
    path = _annotation_path(episode)
    with _locked(path):
        rows = annotations(episode)
        kept = [row for row in rows if row["id"] != annotation_id]
        if len(kept) == len(rows):
            return False
        _write_atomic(path, json.dumps(kept, indent=1) + "\n")
    return True
