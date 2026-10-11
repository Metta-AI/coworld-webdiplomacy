# webDiplomacy optimizer IDE

A local web page around the optimizer lab's tools, and a bridge between that page and
the coding agent that is already running in the optimizer root.

- **Agent panel** (every page): chat with the running agent session, and the cards it
  posts (ideas, replays to look at, results, reports).
- **Home**: where the policy you follow stands (the dashboard's headline number, with what
  it covers and the alone-runs figure beside it when some games seat two of our seats), the
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
ide/ide start --open      # server in the background, browser opened; prints the URL
```

The address is http://127.0.0.1:8642 unless another lab's IDE already has that port: then
`start` takes the next free one and says so. A lab comes back to the port it used last, so
an open tab keeps working across a restart.

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
| `start [--port N] [--open]` | Start the server in the background; print the URL. Reuses a running one. Without `--port`: the port this lab used last, else 8642, else the next free one |
| `serve [--port N] [--open]` | The server in the foreground |
| `stop`, `status [--json]`, `url` | Close it; what is running; print the URL |
| `follow [NAME]` | Record which policy is the user's, so Home, Dashboard and Replays follow it until the user picks another in the browser. No name: print it |
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
| **Rewake hook** | an idle session, a busy one, and one the user interrupted with Esc | A hook on `SessionStart`, `UserPromptSubmit`, `PostToolUse` and `Stop` marked `"asyncRewake": true` runs `ide/ide hook Rewake`. Claude Code keeps it in the background; it waits for a message and exits with code 2 and the message on stderr, which wakes the session. The session's next hook event starts a new one. Until a message comes it lives as long as the session (its hook timeout is seven days), and it keeps waiting while the IDE server is down, so a server started or restarted while the session is idle still reaches it. A second waiter started while one is alive exits at once (`rewake.lock`), which is what every tool call's start normally does. Needs nothing from the agent |
| **PostToolUse / UserPromptSubmit hooks** | a busy session | Return unread messages as `additionalContext` after the agent's next tool call or the user's next terminal prompt |
| **Stop hook** | a session about to go idle | Blocks the stop with the unread messages as the reason. When the IDE is open and nothing is waiting (no Rewake hook, no listener), it blocks once and asks the agent to start `ide/ide listen` |
| **`ide/ide listen`** | an idle session, without the Rewake hook | The agent runs it as a background task; when it exits with the message, Claude Code calls the agent again. The agent restarts it each time |
| **`ide/ide inbox`, MCP `inbox`** | on demand | For harnesses with no hooks and no background tasks |
| **SessionStart hook** | a new session | Says the IDE exists, whether it is open, and where the skill is |
| **SessionEnd hook** | the page | Records that the session ended (`agent_ended`), so the panel says "The agent session has ended" at once instead of "working" |

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

After that run the waiter was changed to keep waiting while the server is down (before, a
server restart with the session idle left no waiter, and messages waited for the next
terminal prompt). Checked once, in a working lab and not a scratch install (2026-10-11,
about 02:30 PDT): the server was stopped and started with the session idle, and a message
sent afterwards was answered in a few seconds. The cases in the table were not run again
after this change.

Third run, after the cold-start drive of 2026-10-11 (Claude Code 2.1.296, Opus 5.5, a scratch
install, typing into the page; about 05:15 PDT). The drive had found that a browser message
sent after Esc in the terminal waited until the user typed there, and that the page said
"Agent is working" for three minutes after an interrupt or an exit. With the waiter also on
`PostToolUse` and `UserPromptSubmit`, and the `SessionEnd` hook:

| Case | Seen |
|---|---|
| Busy (a chain of `sleep 6` calls), one message | answered in the page in under 10 s, mid-turn |
| That waiter having fired, Esc in the terminal, then a message | a waiter was alive after the Esc; answered in under 5 s, nothing typed in the terminal |
| `/exit`, then a message | page: "The agent session has ended. Start claude again…" within 5 s |
| `claude` started again, nothing typed | the waiting message was answered about 25 s after launch |
| Terminal closed (`tmux kill-session`) | `SessionEnd` ran; status shows the session ended |
| `ide/ide start` with another lab's IDE on 8642 | "note: port 8642 is in use … uses 8643"; `stop` then `start` came back on 8643 |

Not covered by that fix: Esc before the turn's first tool call, when the waiter fired during
this same turn. No hook runs between the two, so no waiter exists; after 25 s the page says
the message is not delivered yet and what to do (see "Limits"), and "not listening" after
three minutes.

Not tried in a live session: `ide/ide listen` and the MCP tools under a harness other than
Claude Code.

The panel shows the truth about each message as far as it can know it: "Delivered to the
agent", or why it is still waiting (agent busy, agent idle and not listening, session ended,
no agent attached). An interrupt runs no hook, so an interrupted session looks busy; a
message that has waited more than 25 s under "busy" is shown as "Not delivered yet", with
the one thing to do.

### Limits

- **Esc before the turn's first tool call can leave no waiter.** The message then waits. What
  works: click into the agent's terminal, type any word and press Enter. That prompt runs the
  `UserPromptSubmit` hook, which hands over the waiting messages with it and starts a new
  waiter (seen in the cold-start drive: "go on" delivered a message that had waited three
  minutes). Enter on an empty prompt does not help: it submits nothing, and the only hooks
  are on `SessionStart`, `UserPromptSubmit`, `PostToolUse`, `Stop` and `SessionEnd`
  (`hooks.py: HOOK_EVENTS`), so none runs. The page says this after 25 s. (That an empty
  Enter runs no hook is read from the hook list, not tried in a live session.)
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

## How this differs from the first plan

The mixin's design document (`docs/designs/webdiplomacy-mixin-2026-10-09.html` in
coworld-webdiplomacy) does not cover the IDE. The only earlier plan was a paragraph in
`optimizer/README.md`: a web page for people and an MCP server for agents, two front ends
on one shared core, the MCP server on stdio so that an agent needs no port, cloud
sessions included. What was built differs:

- **The agent comes first.** The user starts Claude Code, and the agent starts the IDE and
  stays the same session throughout. The IDE has no chat backend and calls no model: the
  browser writes a line to a file, and the session's hooks hand it to the agent.
- **The command line is the agent's main way in** (`ide/ide say`, `show`, `annotations`).
  The MCP server offers the same actions for a harness with no shell; it cannot wake an
  idle session.
- **It needs a local port and a browser on the same machine.** A cloud session with no
  browser on its loopback address can still use the commands and the files, not the pages.

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
| `webdip_ide/routes_replays.py` | The replay browser and viewer pages, `/api/replays/...`, annotations |
| `webdip_ide/episodes.py` | The replay index (one row per fetched game) and the viewer's data, press audit included |
| `webdip_ide/routes_dashboard.py` | The dashboard and `/api/dashboard`: the lab's `tools/matchups.py` report as tables and charts |
| `webdip_ide/routes_reports.py`, `reports_markdown.py` | Lists and renders the Markdown reports under `<lab>/reports/`; never writes one |
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
| `agent_ended` | Time the agent's session ended (its SessionEnd hook). Newer than `agent_seen`: no session is attached |
| `followed_policy` | The policy name recorded with `ide/ide follow` |
| `port` | The port the server last listened on; the next `start` uses it again |
| `server.json` | `{pid, port, url, started}` while the server runs |
| `server.lock` | Locked by the server for as long as it lives. A `server.json` whose lock is free was left by a server that was killed, and is ignored |
| `listeners/<pid>` | One file per waiting `listen` or Rewake process |
| `rewake.lock` | Locked by the Rewake waiter while it lives, so a session has one waiter |
| `chat.jsonl.lock`, `cards.jsonl.lock`, `agent_cursor.lock`, `<episode id>.json.lock` | Lock files for writes to the file they are named after (the last for an annotation file). Empty; safe to delete when nothing is running |
| `server.log` | Output of a server started by `ide/ide start` |
| `dashboard_games.pickle`, `episode_index.json` | What was read from each fetched game, so a game is parsed once. Safe to delete: the next page load reads the games again |

Annotations are lab knowledge and are tracked: `<lab>/annotations/<episode id>.json`
(a list of `{id, ts, author, phase, power, territory, tag, text}`). Its lock file is in the
state directory, so nothing but the notes appears in the tracked folder.

### Reading games

A game is about 10 MB of replay and seat logs and takes about 0.08 s to parse. The first
page load after new games were fetched starts the read and answers at once with what is
known; pages show "Still reading games" and fill in. A batch of 16 games or more is parsed
by up to 8 worker processes (`webdip_ide/reader.py`), so the pages stay quick meanwhile; a
smaller batch is parsed in a server thread. The workers stop when the batch is done and
exit with the server, however it ended. A read that was cut short continues at the next
start: the replay index is saved every 20 games and goes on from there; the dashboard's
file is saved when its batch ends, so the dashboard reads a cut-short batch again.

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
window.ide.safeHref(link)         // the link if it is an IDE path or an http(s) address, else null; use it before setting any href from data
window.ide.draft(text)            // put text in the message box for the user to edit and send
window.ide.when(seconds)          // "4:46 AM PDT" (with "Oct 10, " when not today): Pacific, whatever zone the browser is in
```

Shared pieces live in `static/app.css`, so pages built by different people look like one
tool: a page's sections are `<section>` with an `<h2>` (a serif heading over one hairline);
a filter bar is `<form class="filters">` with a `<label>` around each `<select>` (add
class `set` to a select that narrows the page); a sortable column heading is a link or a
`th[data-sort]` and shows its direction with `aria-sort`; `.about` is the grey line that
explains a section. The policy the user follows is one cookie, `dashboard_policy`, read
and written by both the dashboard and the replay browser. Until the user picks one, every
page follows the policy the agent recorded with `ide/ide follow NAME`; without that, the
policy this lab uploaded last, read from the rows `tools/ship.py` adds to
`<lab>/players/*/VERSION_LOG.md` (the dashboard and the home page take a policy with press
games first). A lab with neither is guessing: the dashboard and the home page take the first
policy `matchups.py --list` gives and the home page says it is a guess; the replay browser
follows every seat that has a log.

Write every date with the `when` filter (`{{ row.time | when }}` gives `Oct 11, 2:42 AM`,
Pacific, with the year only when it is not this year) or `day`; in Python, `dates.when()`.
Name the zone in one way only: the abbreviation that is right for the date, `PDT` or `PST`
(`when(zone=true)`, `window.ide.when`), never "PT". A column of times carries no label on
each row (its heading's tooltip says Pacific Time, a row's tooltip has the abbreviation); a
time that stands alone in a sentence carries it.
Keep sortable values (epoch seconds, ISO strings) in the data and format them in the
template. In page text a **game** is what the user watches; say **episode id** only where
the id itself is shown (Episode stays the platform's word for the object, in code and docs).

A link can open the replay viewer at a phase (`/replays/<episode id>?seat=S&phase=N`) or,
when the phase index is not known without reading the replay, at a turn
(`?seat=S&turn=T`: the movement phase of turn T, 0 being Spring 1901). `phase` wins when
both are given. The other paths a card or a report may link to:

- `/replays?policy=NAME&opponent=NAME&variant=V&source=league|xp|local&sort=score`: the
  browser, filtered (more filters are listed at the top of `routes_replays.py`).
- `/dashboard?policy=NAME&version=vN&variant=classic-press&source=league|xp|local&opponent=NAME&alone=1`:
  every part optional. `alone=1` keeps only the games that seat one seat of the policy
  (`matchups.py --alone`), which leaves out paired A/B games; `variant=all` pools press
  and gunboat.
- `/reports`, `/reports?kind=opponents|matchups`, `/reports/opponents/<slug>`,
  `/reports/matchups/<slug>` (the slug is the report's file name without `.md`).

Write routes with `dependencies=[Depends(routes_chat.require_same_origin)]` so another
web site open in the same browser cannot post to the IDE.

## Security

The server binds to 127.0.0.1 and has no login. It shows private press from the lab's
episodes; do not put it behind a tunnel or a proxy. Every route, pages and JSON alike,
refuses a request whose `Host` is not a loopback name, so another site that points its
own name at 127.0.0.1 (DNS rebinding) cannot read the pages. Writes are also refused
unless they come from the IDE's own pages (`Origin` must match `Host`; a request with no
`Origin`, which is what `curl` and other local programs send, is accepted). Agent text,
press and annotations are rendered as text or through an escaping Markdown renderer;
links may only go to IDE paths or `http(s)` addresses. Static files are served with
`Cache-Control: no-cache`, so a browser never shows a new page with an old script.

A press audit is one seat's view of a game. The viewer joins it to the press only while
that seat is followed; from any other seat it shows whose audit it is and nothing else.
The replay list marks only that seat's row "audited"; our other seat in the same game
reads "audit is for Russia". The words for each verdict (label, note, tone, tooltip and the
"What the labels mean" list) come from the lab's `tools/press_report.py`, so the viewer and
the standalone `audit.html` read the same.
The audit folder is per episode (`.runtime/press/<episode id>/`), so when two of our
seats sit in one game, auditing the second replaces the first.

## Tests

```sh
cd ide && uv run python -m unittest discover -s tests
```
