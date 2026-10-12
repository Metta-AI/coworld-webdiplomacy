"""The agent side of the bridge: who is attached, what to hand the agent, and the Claude Code hooks.

A user message typed in the browser is only a line in `chat.jsonl` until something gives
it to the running agent session. Several things can, and whichever runs first wins,
because `store.take_unread_for_agent()` advances one cursor under a file lock:

  hooks      `ide hook <event>`, wired in `.claude/settings.json` (see `hook_settings()`):
               Rewake (on SessionStart, UserPromptSubmit, PostToolUse, Stop and
               FileChanged, `"asyncRewake": true`)
                                               a waiter that Claude Code keeps in the background.
                                               It exits with code 2 when a message arrives, and
                                               that wakes the session, idle or busy. This is what
                                               reaches a session sitting at its prompt, and it
                                               needs nothing from the agent. It lives as long as
                                               the session and waits while the server is down.
                                               Every event starts one and a second one exits at
                                               once, so a waiter is alive again right after one
                                               fired. FileChanged is the one event that does not
                                               depend on the agent's turn: Claude Code watches
                                               `chat.jsonl` (the SessionStart hook asks for it)
                                               and runs the waiter when a message is appended, so
                                               a session with no waiter left (the user pressed
                                               Esc, which runs no hook) is still reached.
               PostToolUse, UserPromptSubmit   add unread messages to the agent's context,
                                               so a busy agent sees them mid-turn.
               Stop                            hold the turn open when messages are unread, or
                                               when the IDE is open and nothing is waiting.
               SessionStart                    say that the IDE exists and whether it is open,
                                               and have `chat.jsonl` watched (`watchPaths`).
               SessionEnd                      record that the session ended, so the page stops
                                               saying an agent is attached.
  listener   `ide listen`, run by the agent as a background task. It exits when a message
             arrives, and the exit makes Claude Code call the agent again. The fallback for
             an idle session when the Rewake hook is not there (another harness, an older
             Claude Code); the Stop hook asks for it when it is needed.
  inbox      `ide inbox` or the MCP `inbox` tool, when the agent asks.

The hooks, the listener and the MCP tools were tried against live Claude Code 2.1.296
sessions on 2026-10-11; the IDE's README records what was seen and what was not tried.

A hook must never break the session: `run_hook` catches everything and exits 0, and a
hook that has nothing to say prints nothing.

Standard library only, and no syntax newer than Python 3.9: hooks run under plain `python3`.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import select
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import paths, store

try:
    PACIFIC = ZoneInfo("America/Los_Angeles")
except ZoneInfoNotFoundError:  # a machine with no time zone database: use its local time
    PACIFIC = None
SEEN_RECENTLY_SECONDS = 180
HOOK_EVENTS = ("SessionStart", "UserPromptSubmit", "PostToolUse", "Stop", "SessionEnd")
# FileChanged is not in HOOK_EVENTS: it has no hook of its own, only the waiter. Claude Code runs it
# when `chat.jsonl` changes (the SessionStart hook asks for that file to be watched), which is the
# one event that does not depend on the agent's turn. See `rewake`.
WAITER_EVENTS = ("SessionStart", "UserPromptSubmit", "PostToolUse", "Stop", "FileChanged")
REWAKE_TIMEOUT_SECONDS = 7 * 24 * 3600  # the waiter lives as long as the session does
# At Stop the Rewake waiter starts at the same moment as the Stop hook. Give it this long
# to register before deciding that nothing is waiting.
WAITER_GRACE_SECONDS = 2.0
# A Bash command that may make the session running it the one the browser chat belongs to. The
# text alone is not enough (a command that only mentions it, such as an `echo` or a `tmux
# send-keys`, matches too): the command must also have run, which `store.take_claim` tells.
CLAIM_COMMAND = re.compile(r"\bide[\"']?\s+(start|attach)\b")
# The waiter of the owning session can start while another session's waiter still holds the lock
# (that one lets go within a second of losing the chat). Try for this long before giving up.
REWAKE_LOCK_WAIT_SECONDS = 4.0


# --- who is attached ---


def pid_alive(pid: int) -> bool:
    if pid <= 0:  # 0 and negative numbers name process groups, not a process
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def hold_server_lock():
    """Take the lab's server lock for as long as the returned file stays open; None when another server has it.

    The lock is how everything else tells a running server from a `server.json` left
    behind by one that was killed: the system drops the lock when the process ends, and
    a pid alone can come to belong to another program.
    """
    lock = open(paths.state_dir() / "server.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.close()
        return None
    return lock


def _server_lock_held() -> bool:
    try:
        probe = open(paths.state_dir() / "server.lock")
    except OSError:
        return False
    with probe:
        try:
            fcntl.flock(probe, fcntl.LOCK_SH | fcntl.LOCK_NB)  # shared: two probes never block each other
        except OSError:
            return True
    return False


def server_info() -> dict | None:
    """The running server's `server.json` ({pid, port, url, started}), or None when it is not running."""
    path = paths.state_dir() / "server.json"
    try:
        info = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return info if pid_alive(int(info.get("pid", 0) or 0)) and _server_lock_held() else None


def _listeners_dir():
    path = paths.state_dir() / "listeners"
    path.mkdir(exist_ok=True)
    return path


def register_listener() -> None:
    (_listeners_dir() / str(os.getpid())).write_text(str(time.time()))


def unregister_listener() -> None:
    try:
        (_listeners_dir() / str(os.getpid())).unlink()
    except OSError:
        pass


def listener_alive() -> bool:
    """True when an `ide listen` process or a Rewake waiter is waiting. Clears the records of dead ones."""
    alive = False
    for record in _listeners_dir().iterdir():
        if record.name.isdigit() and pid_alive(int(record.name)):
            alive = True
        else:
            try:
                record.unlink()
            except OSError:
                pass
    return alive


def delivered_seq() -> int:
    """The `seq` of the last user message handed to the agent."""
    try:
        return int((paths.state_dir() / "agent_cursor").read_text())
    except (OSError, ValueError):
        return 0


def agent_status() -> dict:
    """What the browser shows about the agent. `state` is one of:

    listening   a listener is waiting: a message wakes the agent within seconds
    ended       the agent's session ended (its SessionEnd hook ran) and none has started since
    working     the agent ran something in the last few minutes: hooks deliver at its next step
    idle        an agent was here but is not listening: messages wait until it next runs
    none        no agent has attached to this lab

    `waiting_age` is how long the oldest undelivered user message has waited, in seconds
    (None when nothing waits). A message that waits long while the state is "working"
    usually means the turn was interrupted: an interrupt runs no hook, so nothing here
    can tell it from a long tool call.
    """
    seen = store.agent_seen()
    ended = store.agent_ended()
    listening = listener_alive()
    now = time.time()
    age = None if seen is None else max(0.0, now - seen)
    if listening:
        state = "listening"
    elif ended is not None and (seen is None or ended >= seen):
        state = "ended"
    elif age is None:
        state = "none"
    elif age <= SEEN_RECENTLY_SECONDS:
        state = "working"
    else:
        state = "idle"
    delivered = delivered_seq()
    waiting = [m for m in store.messages(after=delivered) if m["sender"] == "user"]
    return {
        "state": state,
        "listening": listening,
        "seen": seen,
        "seen_age": age,
        "delivered": delivered,
        "waiting": len(waiting),
        "waiting_age": max(0.0, now - waiting[0]["ts"]) if waiting else None,
        "server": server_info(),
        "owner": store.owner_session(),
        "now": now,
    }


# --- what the agent is handed ---


def clock(ts: float) -> str:
    return datetime.fromtimestamp(ts, PACIFIC).strftime("%H:%M:%S %Z")


def _context_lines(context: dict) -> list[str]:
    """Spell out what the user was looking at, including the text of any annotations they attached."""
    lines = []
    episode = context.get("episode")
    if episode:
        where = f"episode {episode}"
        if context.get("phase") is not None:
            where += f", phase {context['phase']}"
        link = context.get("link") or context.get("page")
        lines.append(f"  looking at: {where}" + (f"  ({link})" if link else ""))
    wanted = context.get("annotations") or []
    if episode and wanted:
        try:
            rows = [row for row in store.annotations(str(episode)) if row["id"] in wanted]
        except (OSError, ValueError):
            rows = []
        for row in rows:
            lines.append("  annotation " + annotation_line(row))
    rest = {k: v for k, v in context.items() if k not in ("episode", "phase", "annotations", "link", "label")}
    if rest or (wanted and not episode):
        lines.append(
            "  context: " + json.dumps({**rest, **({"annotations": wanted} if wanted and not episode else {})})
        )
    return lines


def annotation_line(row: dict) -> str:
    where = [f"phase {row['phase']}" if row.get("phase") is not None else None, row.get("power"), row.get("territory")]
    where = ", ".join(str(part) for part in where if part)
    return (
        f"{row['id']} [{row.get('tag', 'note')}] by {row.get('author', '?')}"
        + (f" ({where})" if where else "")
        + (f": {row.get('text', '')}")
    )


def format_messages(messages: list[dict]) -> str:
    """The text handed to the agent for a batch of user messages, the same on every route."""
    count = len(messages)
    out = [f"[webDiplomacy IDE] The user sent {count} message{'' if count == 1 else 's'} from the browser IDE:"]
    for message in messages:
        out.append(f"#{message['seq']} at {clock(message['ts'])}:")
        out.extend("  " + line for line in message["text"].splitlines() or [""])
        out.extend(_context_lines(message.get("context") or {}))
    out.append(
        'The user is reading the IDE, not this terminal. Answer there with `ide/ide say "..."` '
        "(and `ide/ide show ...` for anything worth keeping): the whole answer, with any choice "
        "or question you have for the user. What you write in the terminal they will not see."
    )
    return "\n".join(out)


def take_formatted() -> str | None:
    """Take the unread user messages (marking them delivered) and return them as text, or None."""
    unread = store.take_unread_for_agent()
    return format_messages(unread) if unread else None


# --- Claude Code hooks ---


def session_start_text() -> str:
    server = server_info()
    if server:
        state = f"Its server is running at {server['url']}."
        state += " Messages the user types there are handed to you by this session's hooks."
    else:
        state = "Its server is not running; start it with `ide/ide start --open` when the user asks to open the IDE."
    return (
        "[webDiplomacy IDE] This optimizer has a local web IDE (replays with annotations, a results dashboard, "
        "reports, and a chat panel that reaches this session). " + state + " Read the skill "
        "`games/webdiplomacy/skills/ide/SKILL.md` before using it."
    )


def owns_chat(session_id: str | None) -> bool:
    """True when this session is the one the browser chat is delivered to.

    Hooks are wired per folder, so every Claude Code session started in the optimizer
    runs them. Only one may take the user's messages: the session that last ran
    `ide/ide start` or `ide/ide attach` (see `_claims_chat`), or, when no session has
    done that, the first one whose hook runs while the IDE is in use. A hook run with no
    session id (by hand, or by an older Claude Code) is let through, as before.
    """
    if not session_id:
        return True
    owner = store.owner_session()
    if owner is None:
        if server_info() is None and not store.has_unread_for_agent():
            return True  # the IDE is not in use: nothing to own yet
        store.set_owner_session(session_id)
        return True
    return owner == session_id


def _claims_chat(event: str, payload: dict) -> bool:
    if event != "PostToolUse" or payload.get("tool_name") != "Bash":
        return False
    command = (payload.get("tool_input") or {}).get("command")
    return isinstance(command, str) and bool(CLAIM_COMMAND.search(command)) and store.take_claim()


def _hook_output(event: str, payload: dict) -> dict | None:
    session_id = payload.get("session_id")
    if session_id and _claims_chat(event, payload):
        store.set_owner_session(session_id)  # also when a sub-agent of this session ran the command
    if payload.get("agent_id"):
        return None  # a sub-agent's tool call: the user's messages are for the main session
    if event == "SessionStart":
        chat = paths.state_dir() / "chat.jsonl"
        chat.touch()  # so there is a file to watch before the first message
        return {
            "hookSpecificOutput": {
                "hookEventName": event,
                "additionalContext": session_start_text(),
                "watchPaths": [str(chat)],  # a change runs the FileChanged waiter
            }
        }
    if event == "SessionEnd":
        owner = store.owner_session()
        if session_id and owner and owner != session_id:
            return None  # another session has the chat: this one ending changes nothing
        store.set_owner_session(None)  # the next session to run a hook takes the chat
        if store.agent_seen() is not None:  # only a session the IDE knew about leaves a mark
            store.mark_agent_ended()
        return None
    if server_info() is None and not store.has_unread_for_agent():
        return None  # the IDE is not in use: stay out of the way and leave no presence signal
    if not owns_chat(session_id):
        return None  # the chat belongs to another session in this folder
    store.touch_agent_seen()
    if event in ("PostToolUse", "UserPromptSubmit"):
        text = take_formatted()
        return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}} if text else None
    if event == "Stop":
        text = take_formatted()
        if text:
            return {"decision": "block", "reason": text}
        # Ask once per stop, never in a loop: `stop_hook_active` is set when this stop
        # already follows a blocked one.
        if server_info() and not payload.get("stop_hook_active") and not _waiter_appears():
            return {
                "decision": "block",
                "reason": "[webDiplomacy IDE] The IDE is open in the user's browser but nothing is waiting for "
                "their messages, so this session will not hear them once it is idle. Start `ide/ide listen` as a "
                "background task (Bash with run_in_background), then finish. If the user is done with the IDE, "
                "run `ide/ide stop` instead.",
            }
    return None


def rewake() -> int:
    """`ide hook Rewake`: the waiter behind a hook marked `"asyncRewake": true`.

    Claude Code runs such a hook in the background and wakes the session when it exits
    with code 2, with stderr as the message. So this waits like `ide listen` and exits 2
    with the user's message; the session's next hook event starts a new one, and so does the
    next change to `chat.jsonl` (the FileChanged entry), which finds the message already
    there and exits 2 within a second. It exits 0 at once when another waiter holds the
    lock, and soon after the session that started it has gone.

    It keeps waiting while the IDE server is down: the server may be started or restarted
    later (by the agent, or by the user in another terminal) while this session sits
    idle, and nothing else could wake the session then. The wait is one `stat` a second.
    """
    session_id = _stdin_session_id()
    owner = store.owner_session()
    if session_id and owner and owner != session_id:
        return 0  # the chat belongs to another session in this folder
    lock = open(paths.state_dir() / "rewake.lock", "w")
    # Only the owner waits for the lock: the waiter of a session that just lost the chat
    # holds it for up to a second more.
    deadline = time.time() + (REWAKE_LOCK_WAIT_SECONDS if session_id and owner == session_id else 0.0)
    while True:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            if time.time() >= deadline:
                return 0
            time.sleep(0.2)
    parent = os.getppid()
    if parent == 1:
        # The session ended before this line ran. The waiter now belongs to the system's first
        # process, which never goes away, so "has my parent changed" would never be true.
        return 0
    chat = paths.state_dir() / "chat.jsonl"
    checked = None
    register_listener()
    try:
        while os.getppid() == parent:
            owner = store.owner_session()
            if session_id and owner and owner != session_id:
                return 0  # another session took the chat (it ran `ide/ide start` or `attach`)
            try:
                info = chat.stat()
                stamp = (info.st_mtime_ns, info.st_size)  # the size too: some disks keep whole seconds
            except OSError:  # no chat yet, or the state directory was deleted to reset the IDE
                stamp = None
            if stamp != checked:
                checked = stamp
                if store.has_unread_for_agent() and owns_chat(session_id):
                    text = take_formatted()
                    if text:
                        print(text, file=sys.stderr, flush=True)
                        return 2
            time.sleep(1.0)
    finally:
        unregister_listener()
    return 0


def _stdin_session_id() -> str | None:
    """The `session_id` from the hook's JSON on stdin, or None. Never waits long: a waiter run by hand has no JSON."""
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return None
        descriptor = sys.stdin.fileno()
        raw = b""
        deadline = time.time() + 1.0
        while time.time() < deadline:
            ready, _, _ = select.select([descriptor], [], [], max(0.0, deadline - time.time()))
            if not ready:
                break
            chunk = os.read(descriptor, 65536)
            if not chunk:
                break
            raw += chunk
        session_id = json.loads(raw).get("session_id") if raw.strip() else None
        return session_id if isinstance(session_id, str) and session_id else None
    except (OSError, ValueError, AttributeError):
        return None


def _waiter_appears() -> bool:
    deadline = time.time() + WAITER_GRACE_SECONDS
    while not listener_alive():
        if time.time() >= deadline:
            return False
        time.sleep(0.1)
    return True


def run_hook(event: str) -> int:
    """Entry point for `ide hook <event>`: read the hook's JSON on stdin, print the reply, exit 0 whatever happens."""
    if event.lower() == "rewake":
        try:
            return rewake()
        except Exception as error:  # noqa: BLE001
            print(f"ide hook rewake: {error!r}", file=sys.stderr)
            return 0
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
        wanted = {name.lower(): name for name in HOOK_EVENTS}.get(event.lower().replace("-", "").replace("_", ""))
        output = _hook_output(wanted, payload) if wanted else None
        if output:
            print(json.dumps(output))
    except Exception as error:  # noqa: BLE001 - a hook must never fail the session
        print(f"ide hook {event}: {error!r}", file=sys.stderr)
    return 0


def hook_settings(command: str = 'python3 "$CLAUDE_PROJECT_DIR/ide/ide" hook') -> dict:
    """The `hooks` entries for `.claude/settings.json`. `install.sh` merges these in."""

    def entry(event: str) -> dict:
        return {"hooks": [{"type": "command", "command": f"{command} {event}", "timeout": 10}]}

    waiter = {
        "hooks": [
            {
                "type": "command",
                "command": f"{command} Rewake",
                "asyncRewake": True,
                "timeout": REWAKE_TIMEOUT_SECONDS,
            }
        ]
    }
    settings = {event: [entry(event)] for event in HOOK_EVENTS}
    for event in WAITER_EVENTS:
        settings.setdefault(event, []).append(waiter)
    return settings
