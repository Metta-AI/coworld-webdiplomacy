# webDiplomacy optimizer IDE

A local web page around the optimizer lab's tools, and a bridge between that page and
the coding agent that is already running in the optimizer root.

- **Agent panel** (every page): chat with the running agent session, and the cards it
  posts (ideas, replays to look at, results, reports).
- **Home**: where the policy you follow stands (the dashboard's headline number), the
  games worth opening (its lowest and highest recent scores, with flags and who lied to
  us), your notes not yet sent to the agent, and reports written since you were last here.
- **Replays**: watch any fetched game phase by phase, annotate where it went wrong, send
  the annotations to the agent, overlay the press audit. The board stays in view while you
  read the press beside it; pointing at an order or an audited claim lights it on the board.
- **Dashboard**: how the policy performs by power, opponent, version and source.
- **Reports**: matchup write-ups and opponent profiles the agent's skills produce.

**Prototype (V1, 2026-10-11).** Local only, one user, one agent session per lab.

## Start

The agent comes first. Start Claude Code in the optimizer root and say **"open the
IDE"**. The agent runs:

```sh
ide/ide start --open      # server in the background on http://127.0.0.1:8642, browser opened
```

Type in the panel on the right. The message reaches the agent session whether it is
idle or in the middle of a turn, and its answer appears in the panel. `ide/ide stop`
closes the IDE; `ide/ide status` says what is running.

By hand, without an agent (the pages work; the chat waits for one):

```sh
ide/ide serve --port 8642                         # foreground
WEBDIP_LAB=/path/to/games/webdiplomacy ide/ide serve   # another lab
```

Needs [uv](https://docs.astral.sh/uv/) (the first start builds `ide/.venv`) and
`python3` 3.9 or newer on `PATH` for the hooks. Agent instructions are in the lab skill
`games/webdiplomacy/skills/ide/SKILL.md`.

## Commands

| Command | What it does |
|---|---|
| `start [--port N] [--open]` | Start the server in the background; print the URL. Reuses a running one |
| `serve [--port N] [--open]` | The server in the foreground |
| `stop`, `status [--json]`, `url` | Close it; what is running; print the URL |
| `say TEXT` | Agent to user: a chat line (text from stdin when no arguments) |
| `show --kind idea\|replay\|report\|result\|note --title T [--body MD \| --body-file F] [--link /path]` | Agent to user: a card |
| `inbox [--peek] [--recent N]` | Print unread user messages and mark them delivered |
| `listen [--timeout S]` | Wait for the next user message, print it, exit 0 |
| `annotations [EPISODE] [--json]` | Print replay annotations |
| `annotate EPISODE --text T [--phase N] [--tag TAG] [--power P] [--territory X]` | The agent's own annotation |
| `hook EVENT` | Claude Code hook entry (JSON on stdin) |
| `mcp` | The same actions as an MCP stdio server |

Everything except `serve` and `mcp` is standard-library Python and starts in about 50 ms.

## How a message reaches the running session

The browser only appends the message to `chat.jsonl`. Handing it to the agent is the
agent side's job, and there are several routes. Whichever runs first takes the message:
one cursor (`agent_cursor`), advanced under a file lock, so a message is delivered once.

| Route | Reaches | How |
|---|---|---|
| **Rewake hook** | an idle session, and a busy one | A hook on `Stop` and `SessionStart` marked `"asyncRewake": true` runs `ide/ide hook Rewake`. Claude Code keeps it in the background; it waits for a message and exits with code 2 and the message on stderr, which wakes the session. The next `Stop` starts a new one. It keeps waiting while the IDE server is down, so a server started or restarted while the session is idle still reaches it. Needs nothing from the agent |
| **PostToolUse / UserPromptSubmit hooks** | a busy session | Return unread messages as `additionalContext` after the agent's next tool call or the user's next terminal prompt |
| **Stop hook** | a session about to go idle | Blocks the stop with the unread messages as the reason. When the IDE is open and nothing is waiting (no Rewake hook, no listener), it blocks once and asks the agent to start `ide/ide listen` |
| **`ide/ide listen`** | an idle session, without the Rewake hook | The agent runs it as a background task; when it exits with the message, Claude Code calls the agent again. The agent restarts it each time |
| **`ide/ide inbox`, MCP `inbox`** | on demand | For harnesses with no hooks and no background tasks |
| **SessionStart hook** | a new session | Says the IDE exists, whether it is open, and where the skill is |

`optimizer/install.sh` writes the hook entries into `.claude/settings.json` (they come
from `webdip_ide/hooks.py: hook_settings()`), the `webdip-ide` server into `.mcp.json`,
and links the skill into `.claude/skills/`.

### What was verified

With Claude Code 2.1.296 (model Sonnet) in tmux, in scratch installs made by
`optimizer/install.sh`, posting to `POST /api/chat` and reading `GET /api/chat`
(2026-10-11, about 01:30 to 02:00 PDT):

| Case | Route that delivered | Agent's reply in `/api/chat` after |
|---|---|---|
| Idle at the prompt (4 messages, one after 11 idle minutes) | Rewake hook | 2 to 7 s |
| Busy (a chain of `sleep 6` tool calls), 3 messages | Rewake hook or PostToolUse hook, mid-turn | 2 to 6 s |
| Message sent while no session was running; a new session started and nothing typed | Rewake hook at SessionStart | answered about 15 s after launch |
| Typed in the browser panel with a context chip (Enter to send) | Rewake hook | 6 s; the agent named the attached episode and phase and posted a card |
| Hooks reduced to PostToolUse and Stop, agent busy, no listener | PostToolUse hook | 1 s after the running tool call ended |
| Same, idle, agent running `ide/ide listen` in the background | the listener's exit | 5 s |
| Same, turn ends with the IDE open and nothing waiting | Stop hook asked for a listener; the agent started one | same turn |

Also seen: the Rewake waiter is started again at every Stop (one process, never two),
it outlives the default 600 s hook timeout because its entry sets a long one, and it
exits when the session does.

The panel shows the truth about each message: "Delivered to the agent", or why it is
still waiting (agent busy, agent idle and not listening, no agent attached).

### Limits

- **A long tool call delays a busy agent.** Hooks run between tool calls; the Rewake
  message is also injected between them. A 20-minute command means a 20-minute wait.
- **Delivered is not the same as read.** The cursor moves when the text is handed to
  Claude Code. If the session dies in that instant the message is on disk but marked
  delivered; `ide/ide inbox --recent 5` prints it again.
- **One agent session per lab.** Two sessions in the same optimizer root share the
  cursor; each message goes to whichever asks first.
- **Sub-agents do not receive messages** (hook input with `agent_id` is skipped); the
  main session gets them at its next step.
- **Hooks need workspace trust** and Claude Code 2.1.296 or newer (older versions were
  not tested; one that does not know `asyncRewake` may run the waiter as an ordinary
  blocking Stop hook, so remove the two `Rewake` entries there and rely on `listen`).
- **MCP channels** (a research preview that pushes events into a session) were not
  used: a local channel server must be chosen when `claude` is launched, which
  contradicts "the agent is already running".

## Architecture

```
browser ──HTTP, polls every 2 s──▶ ide serve (FastAPI, 127.0.0.1)
                                        │ reads and writes
                                        ▼
                    <lab>/.runtime/ide/   chat.jsonl  cards.jsonl  agent_cursor  agent_seen
                    <lab>/annotations/    <episode id>.json
                                        ▲
                                        │ reads and writes
agent session ──▶ ide/ide say|show|inbox|listen|annotate,  ide/ide hook <event>,  ide/ide mcp
```

The server and the agent never talk to each other directly; both use `webdip_ide/store.py`.

| File | What |
|---|---|
| `ide` | The command shim (plain `python3`) |
| `webdip_ide/paths.py` | Finds the lab; every directory the IDE uses |
| `webdip_ide/store.py` | Chat, cards and annotations on disk; its docstring is the data contract |
| `webdip_ide/cli.py` | The commands above |
| `webdip_ide/hooks.py` | The agent side: delivery text, hooks, the Rewake waiter, agent status |
| `webdip_ide/mcp_server.py` | MCP tools `say`, `show_card`, `inbox`, `annotations`, `annotate`, `status` |
| `webdip_ide/server.py` | The FastAPI app; one `routes_<feature>.py` per feature |
| `webdip_ide/routes_chat.py` | `/api/chat`, `/api/cards`, `/api/agent/status` |
| `webdip_ide/routes_home.py` | The home page: headline, games worth opening, what is waiting |
| `webdip_ide/reader.py` | Parses fetched games for the dashboard and the replay index: worker processes for a large batch, one parse of a game for both |
| `webdip_ide/dates.py` | The one date format (Pacific, `Oct 11, 2:42 AM`); the Jinja filters `when` and `day` |
| `webdip_ide/static/app.css` | The shared visual system (tokens and base components) |
| `webdip_ide/static/chat.js` | The agent panel and `window.ide` |

## State files

Under `<lab>/.runtime/ide/` (git-ignored; delete the directory to reset the IDE):

| File | Contents |
|---|---|
| `chat.jsonl` | One message per line: `{seq, id, ts, sender, text, context}` |
| `agent_cursor` | `seq` of the last user message handed to the agent |
| `cards.jsonl` | One card per line: `{seq, id, ts, kind, title, body, link}` |
| `agent_seen` | Time of the agent side's last action: the presence signal |
| `server.json` | `{pid, port, url, started}` while the server runs |
| `server.lock` | Locked by the server for as long as it lives. A `server.json` whose lock is free was left by a server that was killed, and is ignored |
| `listeners/<pid>` | One file per waiting `listen` or Rewake process |
| `server.log` | Output of a server started by `ide/ide start` |
| `dashboard_games.pickle`, `episode_index.json` | What was read from each fetched game, so a game is parsed once. Safe to delete: the next page load reads the games again |

Annotations are lab knowledge and are tracked: `<lab>/annotations/<episode id>.json`.

### Reading games

A game is about 10 MB of replay and seat logs and takes about 0.08 s to parse. The first
page load after new games were fetched starts the read and answers at once with what is
known; pages show "Still reading games" and fill in. A batch of 16 games or more is parsed
by up to 8 worker processes (`webdip_ide/reader.py`), so the pages stay quick meanwhile; a
smaller batch is parsed in a server thread. The workers stop when the batch is done and
exit with the server, however it ended. A read that was cut short continues at the next start.

Measured on 510 games with nothing saved (14-core Mac, 2026-10-11): every page answered in
under 0.8 s from the first request, and everything was read 5 to 7 s after it. Before the
worker processes the first page took 20 s, later ones 6 s each, and the read 65 s.

## For page authors

Every page extends `templates/base.html` (blocks `title`, `head`, `content`, `scripts`)
and gets the agent panel. From any page:

```js
window.ide.sendToAgent("Audit the press in this game", {episode, phase})   // posts now; opens the panel
window.ide.setContext({episode, phase, annotations: [ids], label: "optional chip text"})  // attached to what the user types next
window.ide.renderMarkdown(text)   // safe HTML for a small Markdown subset
window.ide.draft(text)            // put text in the message box for the user to edit and send
```

Shared pieces live in `static/app.css`, so pages built by different people look like one
tool: a page's sections are `<section>` with an `<h2>` (a serif heading over one hairline);
a filter bar is `<form class="filters">` with a `<label>` around each `<select>` (add
class `set` to a select that narrows the page); a sortable column heading is a link or a
`th[data-sort]` and shows its direction with `aria-sort`; `.about` is the grey line that
explains a section. The policy the user follows is one cookie, `dashboard_policy`, read
and written by both the dashboard and the replay browser.

Write every date with the `when` filter (`{{ row.time | when }}` gives `Oct 11, 2:42 AM`,
Pacific, with the year only when it is not this year) or `day`; in Python, `dates.when()`.
Keep sortable values (epoch seconds, ISO strings) in the data and format them in the
template. In page text a **game** is what the user watches; say **episode id** only where
the id itself is shown (Episode stays the platform's word for the object, in code and docs).

A link can open the replay viewer at a phase (`/replays/<episode id>?seat=S&phase=N`) or,
when the phase index is not known without reading the replay, at a turn
(`?seat=S&turn=T`: the movement phase of turn T, 0 being Spring 1901).

Write routes with `dependencies=[Depends(routes_chat.require_same_origin)]` so another
web site open in the same browser cannot post to the IDE.

## Security

The server binds to 127.0.0.1 and has no login. It shows private press from the lab's
episodes; do not put it behind a tunnel or a proxy. Every route, pages and JSON alike,
refuses a request whose `Host` is not a loopback name, so another site that points its
own name at 127.0.0.1 (DNS rebinding) cannot read the pages. Writes are also refused
unless they come from the IDE's own pages (`Origin` must match `Host`). Agent text,
press and annotations are rendered as text or through an escaping Markdown renderer;
links may only go to IDE paths or `http(s)` addresses. Static files are served with
`Cache-Control: no-cache`, so a browser never shows a new page with an old script.

A press audit is one seat's view of a game. The viewer joins it to the press only while
that seat is followed; from any other seat it shows whose audit it is and nothing else.
The audit folder is per episode (`.runtime/press/<episode id>/`), so when two of our
seats sit in one game, auditing the second replaces the first.

## Tests

```sh
cd ide && uv run python -m unittest discover -s tests
```
