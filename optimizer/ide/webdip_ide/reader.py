"""Parse fetched games without stalling the pages.

Reading one game is the lab's `matchups.load_game`: the replay (about 10 MB of JSON) and the
seat logs, about 0.08 s of parsing. Parsing holds Python's interpreter lock, so hundreds of
games read in a server thread starve every request: a 0.3 s page took 6 to 20 s for the first
minute after a start with 500 new games. A large batch therefore goes to a few worker
processes, and the server's threads only wait for the results. A small batch (a few games
fetched while the server runs, a test lab) is read in the calling thread, because starting
the workers costs more than it saves.

Two readers want every game: the dashboard's cache (`routes_dashboard.GameCache`) and the
replay index's deep rows (`episodes._fill_deep`). Both call `each_game()`, and a game is
parsed once for the two of them: the result is kept here until a file of the game changes.

The worker processes are started the "spawn" way (a new interpreter that imports this module),
so `load_game` stays a plain function of two strings, this module imports nothing heavy, and
the `ide` command must keep its `if __name__ == "__main__"` line (a worker imports the main
script again). A worker ends by itself when the server does, however the server ended.
"""

from __future__ import annotations

import multiprocessing
import os
import sys
import threading
from collections.abc import Iterator
from concurrent.futures import BrokenExecutor, CancelledError, Future, ProcessPoolExecutor
from multiprocessing.connection import wait
from pathlib import Path

from . import paths

POOL_MIN = 16  # fewer games than this are read in the calling thread
MAX_WORKERS = 8

_lock = threading.Lock()  # guards everything below
_parsed: dict[str, tuple[tuple, Future]] = {}  # episode directory -> (fingerprint, its game or the error)
_pool: ProcessPoolExecutor | None = None
_pool_users = 0  # `each_game` calls using `_pool` now; the workers are stopped when the last one ends


def fingerprint(ep: Path) -> tuple:
    """Changes when any file the loader reads in this episode directory changes."""
    out = []
    for folder in (ep, ep / "policy-logs", ep / "logs"):
        try:
            entries = list(os.scandir(folder))
        except OSError:  # not there, or removed while a page was being built
            continue
        for entry in entries:
            try:
                if entry.is_file():
                    info = entry.stat()
                    out.append((folder.name if folder != ep else "", entry.name, info.st_mtime_ns, info.st_size))
            except OSError:  # a fetch renamed or removed it just now: the next look sees the result
                pass
    return tuple(sorted(out))


def load_game(tools: str, ep: str):
    """`matchups.load_game` for one episode directory. Runs in a worker process or in the caller's thread."""
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import matchups

    return matchups.load_game(Path(ep))


def _exit_with_server() -> None:
    """In a worker: leave when the server process is gone.

    `ide/ide stop` ends the server with a signal and a crash ends it with no warning; neither
    gives it the chance to stop its workers, which would then wait for work for ever.
    """
    wait([multiprocessing.parent_process().sentinel])
    os._exit(0)


def _start_worker() -> None:
    threading.Thread(target=_exit_with_server, daemon=True).start()


def _open_pool() -> ProcessPoolExecutor:
    global _pool, _pool_users
    with _lock:
        if _pool is None:
            workers = min(MAX_WORKERS, max(1, (os.cpu_count() or 2) - 2))  # leave room for the server itself
            _pool = ProcessPoolExecutor(workers, mp_context=multiprocessing.get_context("spawn"),
                                        initializer=_start_worker)  # fmt: skip
        _pool_users += 1
        return _pool


def _close_pool() -> None:
    global _pool, _pool_users
    with _lock:
        _pool_users -= 1
        if _pool_users == 0 and _pool is not None:
            _pool.shutdown(wait=False, cancel_futures=True)
            _pool = None


def _stopped(future: Future) -> bool:
    """True when the workers went away before this game was read (not when the game is unreadable)."""
    return future.done() and (future.cancelled() or isinstance(future.exception(), BrokenExecutor))


def _finished(future: Future) -> bool:
    """Wait for the game. False when the workers went away before it was read."""
    try:
        future.exception()
    except CancelledError:
        return False
    return not _stopped(future)


def _claim(ep: Path, stamp, tools: str, pool: ProcessPoolExecutor | None) -> tuple[Future, bool]:
    """The game's result, already asked for or not. True when the caller must fill it in itself."""
    stamp = tuple(tuple(item) for item in stamp)  # a stamp that was saved as JSON comes back as lists
    with _lock:
        known = _parsed.get(str(ep))
        if known and known[0] == stamp and not _stopped(known[1]):
            return known[1], False
        future = pool.submit(load_game, tools, str(ep)) if pool else Future()
        _parsed[str(ep)] = (stamp, future)
        return future, pool is None


def each_game(todo: dict[Path, tuple]) -> Iterator[tuple[Path, object | None, str | None]]:
    """(episode directory, its `matchups.Game`, None), or (directory, None, why it could not be
    read), for each directory in `todo`, in order.

    `todo` gives each directory's `fingerprint()` as the caller last saw it. A result kept under
    the same fingerprint is used again; the caller has already paid for the file checks, so none
    are repeated here (a second thread checking 500 directories slows the page being built).

    Ends early, with the rest not yielded, when the worker processes are lost (the server is
    stopping, or a worker died). The caller keeps what it has and asks again later.
    """
    paths.use_lab_tools()  # a result from a worker is unpickled here, which imports `matchups`
    tools = str(paths.lab_dir() / "tools")
    if len(todo) < POOL_MIN:
        for ep, stamp in todo.items():
            future, mine = _claim(ep, stamp, tools, None)
            if mine:
                # Filled in before the next one is claimed: this thread never waits for another
                # reader while a reader may be waiting for it.
                try:
                    future.set_result(load_game(tools, str(ep)))
                except Exception as error:  # noqa: BLE001  one unreadable game must not stop the rest
                    future.set_exception(error)
            if not _finished(future):
                return
            yield _outcome(ep, future)
        return
    pool = _open_pool()
    try:
        try:
            futures = [(ep, _claim(ep, stamp, tools, pool)[0]) for ep, stamp in todo.items()]
        except RuntimeError:  # the workers are gone, or Python is shutting down
            return
        for ep, future in futures:
            if not _finished(future):
                return
            yield _outcome(ep, future)
    finally:
        _close_pool()


def _outcome(ep: Path, future: Future) -> tuple[Path, object | None, str | None]:
    error = future.exception()
    if error is not None:
        return ep, None, f"{type(error).__name__}: {error}"
    return ep, future.result(), None


def forget() -> None:
    """Drop every kept result, so the next read parses each game again."""
    with _lock:
        _parsed.clear()
