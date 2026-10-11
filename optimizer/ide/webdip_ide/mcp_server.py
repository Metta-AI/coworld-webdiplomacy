"""The agent's IDE actions as MCP tools: `ide mcp` (stdio), registered in `.mcp.json` as `webdip-ide`.

For agents and harnesses that cannot run `ide/ide` through a shell. The tools do exactly
what the CLI commands of the same name do, through the same store, so a message read
here is not delivered again by a hook or the listener.

MCP tools cannot wake an idle session. Under Claude Code the session's Rewake hook does that;
elsewhere it needs `ide/ide listen` as a background task, or a call to `inbox` when the agent next runs.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from . import hooks, store

server = FastMCP(
    "webdip-ide",
    instructions="The webDiplomacy optimizer's local web IDE. The user reads and types in a browser page; "
    "`inbox` returns what they typed, `say` answers them, `show_card` posts something they can find again. "
    "Read games/webdiplomacy/skills/ide/SKILL.md first.",
)


@server.tool()
def say(text: str) -> str:
    """Post a chat message to the user in the IDE's agent panel."""
    store.touch_agent_seen()
    return f"sent #{store.post_message('agent', text)['seq']}"


@server.tool()
def show_card(title: str, kind: str = "note", body: str = "", link: str | None = None) -> str:
    """Post a card to the IDE's Cards tab.

    kind: idea | replay | report | result | note. body: Markdown. link: an IDE path such as
    /replays/<episode id>?phase=7, /dashboard or /reports/opponents/<slug>.
    """
    if link and not link.startswith(("/", "http://", "https://")):
        raise ValueError("link must be an IDE path such as /replays/<episode>?phase=7, or a full URL")
    store.touch_agent_seen()
    row = store.post_card(kind, title, body, link)
    return f"card #{row['seq']} posted"


@server.tool()
def inbox(peek: bool = False) -> str:
    """Return the user's unread messages from the IDE and mark them delivered (unless peek)."""
    store.touch_agent_seen()
    if peek:
        rows = [m for m in store.messages(after=hooks.delivered_seq()) if m["sender"] == "user"]
        return hooks.format_messages(rows) if rows else "No unread messages."
    return hooks.take_formatted() or "No unread messages."


@server.tool()
def annotations(episode: str | None = None) -> dict[str, list[dict]]:
    """Replay annotations by episode id (the user's and the agent's); all episodes when none is given."""
    store.touch_agent_seen()
    return {episode: store.annotations(episode)} if episode else store.all_annotations()


@server.tool()
def annotate(
    episode: str,
    text: str,
    phase: int | None = None,
    tag: str = "note",
    power: str | None = None,
    territory: str | None = None,
) -> str:
    """Add the agent's own annotation to a replay.

    tag: blunder | missed-alliance | bad-trust | good | suggestion | question | note.
    phase indexes the last replay frame's history.phases.
    """
    store.touch_agent_seen()
    row = store.add_annotation(episode, "agent", text, tag=tag, phase=phase, power=power, territory=territory)
    return f"annotation {row['id']} added to {episode}"


@server.tool()
def status() -> dict:
    """Whether the IDE server is running, whether a listener is waiting, and how many messages are unread."""
    return hooks.agent_status()


def run() -> None:
    server.run()
