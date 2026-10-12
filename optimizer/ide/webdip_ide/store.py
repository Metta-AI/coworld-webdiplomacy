"""The IDE's files: chat between the user and the agent, agent cards, replay annotations.

Everything is plain JSON on disk so the agent can also read it with `cat`. The web
server, the agent's CLI commands and the Claude Code hooks are separate processes;
they all go through this module, and every write holds an exclusive file lock.

Standard library only (hooks import it without `uv`).

Files, under `paths.state_dir()` unless noted:
  chat.jsonl      one message per line: {seq, id, ts, sender: "user"|"agent", text, context}
                  `context` is optional and names what the user was looking at, for example
                  {"episode": "...", "phase": 7, "annotations": ["a1f"]}. It is whatever small
                  object the page sent: `seat`, `label`, `page`, `request` and others also occur.
  agent_cursor    the `seq` of the last user message delivered to the agent.
  cards.jsonl     things the agent shows the user: {seq, id, ts, kind, title, body, link}
                  kind: "idea" | "replay" | "report" | "result" | "note"; `body` is Markdown;
                  `link` is an IDE path such as "/replays/<episode>?phase=7".
  agent_seen      the time (seconds since 1970) the agent side last acted: a chat, card or
                  annotation command, `start`, an MCP tool, or a hook while the IDE is in use.
                  Its presence signal.
  owner_session   the id of the one agent session the browser chat is delivered to
  agent_ended     the time the agent's session ended (its SessionEnd hook). Newer than
                  `agent_seen` means no session is attached.
  followed_policy the name of the policy the pages follow until the user picks another in
                  the browser. The agent writes it (`ide/ide follow NAME`); the file's time is
                  when, and a browser's choice made before then no longer counts.
  port            the port the server last listened on, so the next `start` uses it again.
  annotations/<episode id>.json   (in `paths.annotations_dir()`, tracked by git)
                  a list of {id, ts, author: "user"|"agent", phase, power, territory, tag,
                  text}. `phase` indexes the replay's last frame `history.phases`; `power`
                  and `territory` are optional names. tag: "blunder" | "missed-alliance" |
                  "bad-trust" | "good" | "suggestion" | "question" | "note".

Each write takes `<file name>.lock` in `paths.state_dir()` (`chat.jsonl.lock`,
`cards.jsonl.lock`, `agent_cursor.lock`, `<episode id>.json.lock` for an annotation file).

Other modules keep their own files in `paths.state_dir()`: `server.json`, `server.lock`,
`server.log`, `listeners/<pid>` and `rewake.lock` (`cli.py`, `hooks.py`), and the two saved
reads of the fetched games, `episode_index.json` (`episodes.py`) and `dashboard_games.pickle`
(`routes_dashboard.py`). The IDE's README lists them all.
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
    """Hold an exclusive lock for a read-modify-write on `path`.

    The lock file is kept in the state directory whatever directory `path` is in, so no
    lock file appears among the tracked annotations.
    """
    with open(paths.state_dir() / (path.name + ".lock"), "w") as lock:
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


def mark_agent_ended() -> None:
    _write_atomic(paths.state_dir() / "agent_ended", str(time.time()))


def agent_ended() -> float | None:
    try:
        return float((paths.state_dir() / "agent_ended").read_text())
    except (OSError, ValueError):
        return None


def owner_session() -> str | None:
    """The id of the agent session the browser chat belongs to, or None when no session has it."""
    try:
        return (paths.state_dir() / "owner_session").read_text().strip() or None
    except OSError:
        return None


CLAIM_SECONDS = 60.0


def request_claim() -> None:
    """Note that `ide/ide start` or `attach` has just run inside an agent's shell (see `take_claim`)."""
    _write_atomic(paths.state_dir() / "claim_pending", str(time.time()))


def take_claim() -> bool:
    """True, once, when `ide/ide start` or `attach` ran in the last minute. Removes the note."""
    path = paths.state_dir() / "claim_pending"
    try:
        asked = float(path.read_text())
        path.unlink()
    except (OSError, ValueError):
        return False
    return time.time() - asked <= CLAIM_SECONDS


def set_owner_session(session_id: str | None) -> None:
    path = paths.state_dir() / "owner_session"
    if session_id:
        _write_atomic(path, session_id)
        return
    try:
        path.unlink()
    except OSError:
        pass


# --- the policy the pages follow ---


def set_followed_policy(name: str) -> None:
    _write_atomic(paths.state_dir() / "followed_policy", name.strip() + "\n")


def followed_policy() -> str:
    """The policy name the agent recorded as ours, or "" when none was recorded."""
    try:
        return (paths.state_dir() / "followed_policy").read_text().strip()
    except OSError:
        return ""


def followed_at() -> float:
    """When the agent last recorded the policy (every `ide/ide follow NAME` counts, also with the
    same name), or 0.0 when it never did."""
    try:
        return (paths.state_dir() / "followed_policy").stat().st_mtime
    except OSError:
        return 0.0


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
