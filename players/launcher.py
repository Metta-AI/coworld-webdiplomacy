"""Keep Coworld presence separate from the bot's upstream HTTP traffic."""

import json
import multiprocessing
import os
import signal
import subprocess
import sys
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

from players.press import collect


def stop_child(child):
    if child is None:
        return
    # The command owns its process group, including any subprocesses it starts.
    try:
        os.killpg(child.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        child.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass
    # Reap surviving descendants even if the direct child already exited.
    try:
        os.killpg(child.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    child.wait(timeout=2)


def finish_press(worker, control, reason):
    if worker is None:
        return
    try:
        control.send(reason)
    except BrokenPipeError:
        print('{"event":"private_press_upload","status":"worker_failed"}', flush=True)
    worker.join(timeout=12)
    if worker.is_alive():
        worker.kill()
        worker.join(timeout=2)
        print('{"event":"private_press_upload","status":"deadline_exceeded"}', flush=True)
    elif worker.exitcode:
        print('{"event":"private_press_upload","status":"worker_failed"}', flush=True)
    control.close()


def main():
    url = urlsplit(os.environ["COWORLD_PLAYER_WS_URL"])
    query = dict(parse_qsl(url.query))
    query["mode"] = "bot"
    address = urlunsplit(url._replace(query=urlencode(query)))
    child = worker = control = None
    stop = False
    reason = "interrupted"
    status = 0

    def stopping(*_):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, stopping)
    signal.signal(signal.SIGINT, stopping)
    try:
        while not stop:
            try:
                with connect(address, ping_timeout=None, open_timeout=3, close_timeout=1) as ws:
                    hello = json.loads(ws.recv(timeout=3))
                    if hello.get("protocol") != "webdip-coworld/1":
                        raise RuntimeError("unexpected game protocol")
                    webdip = hello["webdip"]
                    if child is None:
                        env = {
                            **os.environ,
                            "WEBDIP_URL": webdip["base_url"],
                            "WEBDIP_API_KEY": webdip["api_key"],
                            "WEBDIP_GAME_ID": str(webdip["game_id"]),
                            "WEBDIP_COUNTRY_ID": str(webdip["country_id"]),
                            "WEBDIP_SEED": str(hello.get("rules", {}).get("seed", 0)),
                        }
                        command = sys.argv[1:] or [sys.executable, "-m", "players.random_bot"]
                        child = subprocess.Popen(command, env=env, start_new_session=True)
                        context = multiprocessing.get_context("spawn")
                        receiver, control = context.Pipe(duplex=False)
                        worker = context.Process(target=collect, args=(webdip, receiver))
                        worker.start()
                        receiver.close()
                    while not stop:
                        # A finished bot is allowed to wait for game_over. Failures remain
                        # visible in the player exit code, while presence and press survive.
                        if child.poll() is not None and child.returncode != 0:
                            status = child.returncode
                        try:
                            message = json.loads(ws.recv(timeout=0.5))
                        except TimeoutError:
                            continue
                        if message.get("type") == "game_over":
                            if child.poll() is not None and child.returncode != 0:
                                status = child.returncode
                            reason = (
                                "cancelled" if message.get("results", {}).get("outcome") == "cancelled" else "game_over"
                            )
                            stop_child(child)
                            child = None
                            finish_press(worker, control, reason)
                            worker = None
                            try:
                                ws.send(json.dumps({"type": "game_over_ack"}))
                            except ConnectionClosed:
                                pass  # Completion still succeeds if the server already closed its drain window.
                            return status
            except (ConnectionClosed, OSError, TimeoutError):
                if not stop:
                    time.sleep(0.2)
    finally:
        stop_child(child)
        finish_press(worker, control, reason)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
