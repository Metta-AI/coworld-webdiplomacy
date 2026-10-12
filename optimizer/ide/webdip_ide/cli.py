"""The IDE's command line: `ide/ide <command>`, run by the agent from the optimizer root.

  Open and close
    start [--port N] [--open]   start the web server in the background and print its URL.
                                Without --port: the port this lab used last, else 8642; when
                                that one is taken (another lab's IDE), the next free one
    stop                        stop it
    serve [--port N] [--open]   run the server in the foreground (what `start` runs)
    attach                      give the browser chat to the Claude Code session that runs this
    status [--json]             is the server up, is something waiting for messages, anything unread
    follow [NAME]               record which policy is the user's, so every page follows it
                                until the user picks another in the browser (no NAME: print it).
                                It replaces a pick the browser made earlier
    url                         print the running server's URL (exit 1 when it is not running)
  Talk to the user (the user reads the browser, not the terminal)
    say TEXT                    post a chat message
    show --kind K --title T [--body MD | --body-file F] [--link /path]   post a card
    inbox [--peek] [--recent N] print unread user messages and mark them delivered (--peek: do not
                                mark; --recent N: the last N again, read or not)
    listen [--timeout S]        wait for the next user message, print it, exit. Run it as a
                                background task: its exit wakes an idle session. Only needed
                                when the session's Rewake hook is not doing this already
  Replay annotations
    annotations [EPISODE] [--json]   print annotations (the user's and the agent's)
    annotate EPISODE --text T [--phase N] [--tag TAG] [--power P] [--territory X]
  Plumbing
    hook EVENT                  Claude Code hook entry; reads the hook JSON on stdin
    mcp                         the same actions as an MCP stdio server

Everything except `serve` and `mcp` uses only the standard library and runs under plain
`python3`, so hooks and chat commands are fast. `serve` and `mcp` need FastAPI and the
MCP SDK; when those are not importable the command runs itself again through
`uv run --project <ide dir>`.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from . import hooks, paths, store

DEFAULT_PORT = 8642
PORTS_TO_TRY = 20  # how far past the wanted port `start` looks for a free one
HOST = "127.0.0.1"  # never anything else: the IDE shows private press and has no login
START_WAIT_SECONDS = 90  # the first start also builds the virtualenv


# --- server ---


def _uv_command(*args: str) -> list[str]:
    return ["uv", "run", "--quiet", "--project", str(paths.IDE_DIR), "python", "-m", "webdip_ide", *args]


def _uv_env() -> dict:
    """`python -m webdip_ide` must find this package whatever the working directory is."""
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(paths.IDE_DIR), env.get("PYTHONPATH")]))
    env["WEBDIP_LAB"] = str(paths.lab_dir())
    return env


def _reexec_with_dependencies(argv: list[str]) -> None:
    os.environ.update(_uv_env())
    try:
        os.execvp("uv", _uv_command(*argv))
    except FileNotFoundError:
        sys.exit("error: `uv` is not installed; the IDE server needs it (https://docs.astral.sh/uv/)")


def _healthy(url: str) -> bool:
    try:
        with urllib.request.urlopen(url + "/api/agent/status", timeout=2) as response:
            return response.status == 200
    except OSError:
        return False


def _port_free(port: int) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # as `serve` binds it
        try:
            probe.bind((HOST, port))
        except OSError:
            return False
    return True


def _last_port() -> int | None:
    try:
        return int((paths.state_dir() / "port").read_text())
    except (OSError, ValueError):
        return None


def _choose_port(asked: int | None) -> int:
    """The port to serve on. A port the caller named is used as it is, free or not.

    Otherwise: the port this lab's server used last (so a restart keeps the address the
    user's browser tab has), else the default; and when that one is taken, which is the
    normal case for a second lab on one machine, the next free port after it.
    """
    if asked is not None:
        return asked
    wanted = _last_port() or DEFAULT_PORT
    for port in range(wanted, wanted + PORTS_TO_TRY):
        if _port_free(port):
            if port != wanted:
                print(
                    f"note: port {wanted} is in use (another lab's IDE?), so this lab's IDE uses {port}",
                    file=sys.stderr,
                )
            return port
    sys.exit(f"error: no free port from {wanted} to {wanted + PORTS_TO_TRY - 1}; name one with --port")


def _open_browser(url: str) -> None:
    import webbrowser

    webbrowser.open(url)


def cmd_serve(args) -> int:
    running = hooks.server_info()
    if running:
        print(f"IDE already running at {running['url']} (pid {running['pid']})")
        if args.open:
            _open_browser(running["url"])
        return 0
    try:
        import uvicorn

        from .server import create_app
    except ImportError:
        _reexec_with_dependencies(
            ["serve"] + (["--port", str(args.port)] if args.port else []) + (["--open"] if args.open else [])
        )
    import socket

    port = _choose_port(args.port)
    url = f"http://{HOST}:{port}"
    # Take the port and the lab's server lock before writing the record, so a `serve` that
    # loses either one never replaces, and then deletes, the record of the server that won.
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        listener.bind((HOST, port))
    except OSError as error:
        sys.exit(
            f"error: cannot listen on {url} ({error.strerror}). Another program has that port: "
            "leave out --port and the IDE picks a free one"
        )
    lock = hooks.hold_server_lock()  # held until this process ends: see hooks.server_info
    if lock is None:
        sys.exit("error: another IDE server is starting for this lab; run `ide/ide status` in a moment")
    record = paths.state_dir() / "server.json"
    record.write_text(json.dumps({"pid": os.getpid(), "port": port, "url": url, "started": time.time()}) + "\n")
    (paths.state_dir() / "port").write_text(f"{port}\n")  # the next `start` comes back to this address
    print(f"IDE at {url}  (lab {paths.lab_dir()})", flush=True)
    if args.open:
        import threading

        threading.Timer(1.0, _open_browser, [url]).start()
    try:
        uvicorn.Server(uvicorn.Config(create_app(), log_level="warning")).run(sockets=[listener])
    finally:
        try:
            if json.loads(record.read_text()).get("pid") == os.getpid():
                record.unlink()
        except (OSError, ValueError):
            pass
    return 0


def cmd_start(args) -> int:
    running = hooks.server_info()
    if running:
        print(f"IDE already running at {running['url']}")
        if os.environ.get("CLAUDECODE"):
            store.request_claim()  # an agent told to open the IDE takes the chat, running or not
        if args.open:
            _open_browser(running["url"])
        return 0
    port = _choose_port(args.port)
    log = paths.state_dir() / "server.log"
    with open(log, "ab") as out:
        log_start = out.tell()  # an error shows only what this start wrote, not older runs
        try:
            child = subprocess.Popen(
                _uv_command("serve", "--port", str(port)),
                env=_uv_env(),
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=out,
                start_new_session=True,  # the server outlives this command and the agent's turn
            )
        except FileNotFoundError:
            sys.exit("error: `uv` is not installed; the IDE server needs it (https://docs.astral.sh/uv/)")
    url = f"http://{HOST}:{port}"
    deadline = time.time() + START_WAIT_SECONDS
    while time.time() < deadline:
        info = hooks.server_info()
        if info and _healthy(info["url"]):
            if os.environ.get("CLAUDECODE"):  # started by an agent's shell, not by the user in a terminal
                store.touch_agent_seen()
                store.request_claim()  # the hook that follows this command gives this session the chat
            print(f"IDE running at {info['url']}")
            print("The user's messages reach this session through its hooks (ide/ide status shows how).")
            if args.open:
                _open_browser(info["url"])
            return 0
        if child.poll() is not None:
            break
        time.sleep(0.3)
    with open(log, "rb") as written:
        written.seek(log_start)
        tail = "".join(written.read().decode(errors="replace").splitlines(keepends=True)[-15:])
    sys.exit(f"error: the IDE server did not come up at {url}. Last lines of {log}:\n{tail}")


def cmd_stop(args) -> int:
    running = hooks.server_info()
    if not running:
        print("IDE is not running")
        return 0
    import signal

    os.kill(int(running["pid"]), signal.SIGTERM)
    for _ in range(50):
        if not hooks.pid_alive(int(running["pid"])):
            break
        time.sleep(0.1)
    # uvicorn ends on the signal itself, before `serve` can remove its record.
    record = paths.state_dir() / "server.json"
    try:
        if json.loads(record.read_text()).get("pid") == running["pid"]:
            record.unlink()
    except (OSError, ValueError):
        pass
    print(f"IDE stopped (was {running['url']})")
    return 0


def cmd_attach(args) -> int:
    """Nothing to do here: the PostToolUse hook that follows this command gives the chat to the session that ran it."""
    if not os.environ.get("CLAUDECODE"):
        print("ide/ide attach does something only when a Claude Code session runs it: its hook takes the chat.")
        return 0
    store.request_claim()
    print("This session takes the browser chat when this command returns, not before: "
          "check with ide/ide status in a separate command.")
    return 0


def cmd_status(args) -> int:
    status = hooks.agent_status()
    if args.json:
        print(json.dumps(status, indent=1))
        return 0
    server = status["server"]
    print(f"server:    {'running at ' + server['url'] if server else 'not running (ide/ide start --open)'}")
    waiting = (
        "waiting for messages" if status["listening"] else "none (the Stop hook starts one; or run ide/ide listen)"
    )
    print(f"listener:  {waiting}")
    seen = "never" if status["seen_age"] is None else f"{status['seen_age']:.0f} s ago"
    print(f"agent:     last seen {seen}" + (" (its session has ended)" if status["state"] == "ended" else ""))
    owner = status["owner"] or "not chosen yet (the first to run a hook, or to run ide/ide attach)"
    print(f"chat:      delivered to session {owner}")
    print(f"unread:    {status['waiting']} user message(s) not yet delivered")
    print(f"lab:       {paths.lab_dir()}")
    return 0


def cmd_follow(args) -> int:
    if not args.name:
        print(store.followed_policy() or "No policy recorded. `ide/ide follow NAME` records the user's policy.")
        return 0
    name = args.name.partition(":v")[0]  # a policy, not one version of it
    store.set_followed_policy(name)
    store.touch_agent_seen()
    print(f"The IDE's pages now follow {name}, in every browser, until the user picks another policy there.")
    return 0


def cmd_url(args) -> int:
    running = hooks.server_info()
    if not running:
        print("IDE is not running (ide/ide start --open)", file=sys.stderr)
        return 1
    print(running["url"])
    return 0


# --- talking to the user ---


def _warn_if_closed() -> None:
    if hooks.server_info() is None:
        print(
            "note: the IDE server is not running, so the user cannot see this yet (ide/ide start --open)",
            file=sys.stderr,
        )


def cmd_say(args) -> int:
    text = " ".join(args.text).strip() if args.text else sys.stdin.read().strip()
    if not text:
        sys.exit("error: nothing to say (give the text as arguments or on stdin)")
    store.touch_agent_seen()
    row = store.post_message("agent", text)
    _warn_if_closed()
    print(f"sent #{row['seq']}")
    return 0


def cmd_show(args) -> int:
    body = Path(args.body_file).read_text() if args.body_file else (args.body or "")
    if args.link and not args.link.startswith(("/", "http://", "https://")):
        sys.exit("error: --link must be an IDE path such as /replays/<episode>?phase=7, or a full URL")
    store.touch_agent_seen()
    row = store.post_card(args.kind, args.title, body, args.link)
    _warn_if_closed()
    print(f"card #{row['seq']} posted: [{row['kind']}] {row['title']}")
    return 0


def cmd_inbox(args) -> int:
    store.touch_agent_seen()
    if args.recent:
        rows = [m for m in store.messages() if m["sender"] == "user"][-args.recent :]
        print(hooks.format_messages(rows) if rows else "No user messages yet.")
        return 0
    if args.peek:
        rows = [m for m in store.messages(after=hooks.delivered_seq()) if m["sender"] == "user"]
        print(hooks.format_messages(rows) if rows else "No unread messages.")
        return 0
    print(hooks.take_formatted() or "No unread messages.")
    return 0


def cmd_listen(args) -> int:
    """Block until a user message is unread, print it, exit 0.

    Exits 0 with a one-line notice on timeout too, so a caller can always just restart it.
    Stops quietly when the process that started it has gone, so a listener left behind by
    a dead session cannot swallow messages meant for the next one.
    """
    parent = os.getppid()
    deadline = time.time() + args.timeout if args.timeout else None
    hooks.register_listener()
    store.touch_agent_seen()
    try:
        while True:
            if store.has_unread_for_agent():
                text = hooks.take_formatted()
                if text:
                    print(text)
                    print("This listener has now exited. Start `ide/ide listen` in the background again.", flush=True)
                    return 0
            if os.getppid() != parent:
                return 0
            if deadline and time.time() >= deadline:
                print("[webDiplomacy IDE] No message yet. Run `ide/ide listen` again to keep waiting.")
                return 0
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return 130
    finally:
        hooks.unregister_listener()


# --- annotations ---


def cmd_annotations(args) -> int:
    store.touch_agent_seen()
    by_episode = {args.episode: store.annotations(args.episode)} if args.episode else store.all_annotations()
    by_episode = {episode: rows for episode, rows in by_episode.items() if rows}
    if args.json:
        print(json.dumps(by_episode, indent=1))
        return 0
    if not by_episode:
        print("No annotations" + (f" on {args.episode}." if args.episode else " yet."))
        return 0
    for episode, rows in by_episode.items():
        print(f"{episode}  ({len(rows)} annotation{'' if len(rows) == 1 else 's'}, /replays/{episode})")
        for row in sorted(rows, key=lambda r: (r.get("phase") is None, r.get("phase") or 0, r["ts"])):
            print("  " + hooks.annotation_line(row))
    return 0


def cmd_annotate(args) -> int:
    store.touch_agent_seen()
    row = store.add_annotation(
        args.episode, "agent", args.text, tag=args.tag, phase=args.phase, power=args.power, territory=args.territory
    )
    print(f"annotation {row['id']} added to {args.episode}")
    return 0


def cmd_hook(args) -> int:
    return hooks.run_hook(args.event)


def cmd_mcp(args) -> int:
    try:
        from . import mcp_server
    except ImportError:
        _reexec_with_dependencies(["mcp"])
    mcp_server.run()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ide/ide", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", metavar="<command>")
    commands.required = True

    def add(name: str, handler, **kwargs) -> argparse.ArgumentParser:
        sub = commands.add_parser(name, **kwargs)
        sub.set_defaults(handler=handler)
        return sub

    for name, handler in (("start", cmd_start), ("serve", cmd_serve)):
        sub = add(name, handler)
        sub.add_argument(
            "--port", type=int, help=f"default: the port this lab used last, else {DEFAULT_PORT}, else the next free"
        )
        sub.add_argument("--open", action="store_true", help="open the IDE in the default browser")
    add("stop", cmd_stop)
    add("attach", cmd_attach, help="give the browser chat to the Claude Code session that runs this")
    add("status", cmd_status).add_argument("--json", action="store_true")
    add("url", cmd_url)
    add("follow", cmd_follow).add_argument("name", nargs="?", help="a policy name, the name you upload under")

    add("say", cmd_say).add_argument("text", nargs="*", help="the message; read from stdin when omitted")
    show = add("show", cmd_show)
    show.add_argument("--kind", choices=store.CARD_KINDS, default="note")
    show.add_argument("--title", required=True)
    body = show.add_mutually_exclusive_group()
    body.add_argument("--body", help="Markdown")
    body.add_argument("--body-file", help="a Markdown file")
    show.add_argument("--link", help="an IDE path, for example /replays/<episode>?phase=7")
    inbox = add("inbox", cmd_inbox)
    inbox.add_argument("--peek", action="store_true", help="print without marking delivered")
    inbox.add_argument("--recent", type=int, metavar="N", help="print the last N user messages again, read or not")
    listen = add("listen", cmd_listen)
    listen.add_argument("--timeout", type=float, default=0, help="give up after this many seconds (default: wait)")
    listen.add_argument("--interval", type=float, default=1.0, help=argparse.SUPPRESS)

    notes = add("annotations", cmd_annotations)
    notes.add_argument("episode", nargs="?")
    notes.add_argument("--json", action="store_true")
    annotate = add("annotate", cmd_annotate)
    annotate.add_argument("episode")
    annotate.add_argument("--text", required=True)
    annotate.add_argument("--phase", type=int)
    annotate.add_argument("--tag", choices=store.ANNOTATION_TAGS, default="note")
    annotate.add_argument("--power")
    annotate.add_argument("--territory")

    add("hook", cmd_hook).add_argument("event")
    add("mcp", cmd_mcp)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(args) or 0
