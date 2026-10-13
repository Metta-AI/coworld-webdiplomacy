"""Local launch and collection; never changes platform state."""
import argparse
import signal
import subprocess
import sys

from .paths import PROJECT, runtime_dir
from .store import Store


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    collect_parser = commands.add_parser("collect", help="Poll read-only API sources into the cache")
    collect_parser.add_argument("--once", action="store_true")
    serve_parser = commands.add_parser("serve", help="Serve localhost, with a collector child by default")
    serve_parser.add_argument("--port", type=int, default=8660)
    serve_parser.add_argument("--no-collector", action="store_true", help="View cache without login or network")
    args = parser.parse_args(argv)
    store = Store(runtime_dir())
    if args.command == "collect":
        from .api import ApiError
        from .collector import collect

        try:
            collect(store, args.once)
        except ApiError as error:
            print(str(error), file=sys.stderr)
            return 1
        return int(any(r["error"] for r in store.snapshot().values())) if args.once else 0

    import uvicorn

    from .server import create_app

    store.initialize()
    child = None
    # Uvicorn replays SIGTERM after its own shutdown. Convert the default immediate
    # process exit into stack unwinding so the owned collector is terminated too.
    def terminate(signum, frame):
        raise SystemExit(0)

    previous_term = signal.signal(signal.SIGTERM, terminate)
    try:
        if not args.no_collector:
            child = subprocess.Popen([sys.executable, "-m", "league_desk", "collect"], cwd=PROJECT)
        uvicorn.run(create_app(store), host="127.0.0.1", port=args.port, access_log=False)
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        signal.signal(signal.SIGTERM, previous_term)
    return 0
