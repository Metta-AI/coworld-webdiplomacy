# Agent guide: working on the IDE's code

This is for agents changing the IDE. To *use* the IDE in an optimizer session, read the
lab skill `games/webdiplomacy/skills/ide/SKILL.md` (source: `optimizer/mixin/skills/ide/`).
[README.md](README.md) has the architecture, the state files and how delivery works.

## Layout

- Source lives in `optimizer/ide/` of coworld-webdiplomacy; `optimizer/install.sh` copies
  it to `<optimizer root>/ide/` and wires the hooks. Do not edit an installed copy.
- `webdip_ide/paths.py` is the only path logic; `webdip_ide/store.py` is the only store.
- One feature is one `routes_<name>.py` (exports `router` and `NAV`) plus its templates
  and its own `static/<name>.{js,css}`. Add it to `FEATURES` in `server.py`.

## Rules

- **Standard library only, Python 3.9 syntax, in `paths.py`, `store.py`, `hooks.py`,
  `cli.py` and the `ide` shim.** Hooks and the agent's chat commands run under whatever
  `python3` is on `PATH`, without `uv`. Import FastAPI, uvicorn or `mcp` only inside the
  `serve` and `mcp` paths. `tests/test_cli.py` runs the commands with `python3 -S` to
  catch a stray import.
- **A hook never fails the session and never repeats a message.** `hooks.run_hook`
  catches everything and exits 0; deliver only through `store.take_unread_for_agent()`.
  A Stop hook may block only when it has something new to say (unread messages), or
  once per stop (`stop_hook_active` false).
- **No `async def`.** Handlers are plain `def`; the browser polls.
- **Bind to 127.0.0.1 only.** Put `Depends(routes_chat.require_same_origin)` on every
  route that writes.
- **Never render agent or user text as raw HTML.** Use `window.ide.renderMarkdown`
  (client) or escape it (Jinja autoescape is on).
- **No CDN, no build step.** Plain scripts and CSS; the IDE works offline.
- **Design:** Softmax Ink & Print. Use the tokens and components in `static/app.css`
  (`--paper`, `--ink`, `--navy`, `.tag`, `.btn`, `table`, `.eyebrow`, …); add only
  page-specific rules in your own stylesheet. No pure black or white, no decorative
  cards, no stat tiles, every number with its n.
- Seat tokens are credentials: never display or log them. Private press may be shown
  in the IDE but is never written to tracked files.

## Check your work

```sh
cd optimizer/ide && uv run python -m unittest discover -s tests
uv run ruff check optimizer            # from the repository root
WEBDIP_LAB=~/coding/webdip-optimizer/games/webdiplomacy optimizer/ide/ide serve --port 8650   # then look at the page
```

A change to delivery (hooks, `listen`, the Rewake waiter) is not verified by unit tests
alone. Make a scratch install (`optimizer/install.sh <empty dir outside the repo>`),
start `claude` there in tmux, open the IDE, post to `/api/chat` with the session idle
and with it busy, and check that the reply appears in `GET /api/chat`. Record what you
saw in README.md under "What was verified".

## Gotchas

- The hook settings live in `hooks.hook_settings()`; `optimizer/install.sh` imports it.
  Change the entries there, not in the script.
- Claude Code shows a blocked stop and a Rewake wake-up as "Stop hook error" or "Stop
  hook feedback". That is the delivery, not a failure.
- `server.json` and `listeners/<pid>` are trusted only while their process is alive
  (`hooks.pid_alive`); stale files are ignored or removed.
- `ide/ide start` runs `uv run --project ide` with `PYTHONPATH` set to the IDE directory,
  because the project is not an installable package (`[tool.uv] package = false`).
