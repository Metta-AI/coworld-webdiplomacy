"""Remote Diplomacy seat controller with a durable command identity and optional policy callback."""

import argparse
import importlib
import json
import os
import threading
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


class Api:
    def __init__(self, *, endpoint, token):
        self.endpoint = endpoint.rstrip("/")
        self.token = token

    def call(self, *, path="", value=None):
        request = Request(
            self.endpoint + path,
            data=None if value is None else json.dumps(value).encode(),
            headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json"},
        )
        with urlopen(request, timeout=20) as response:
            body = response.read(512 * 1024 + 1)
        if len(body) > 512 * 1024:
            raise ValueError("Response exceeds the participation limit")
        return json.loads(body)


class Journal:
    def __init__(self, *, path, endpoint):
        self.path = path
        self.data = json.loads(path.read_text()) if path.exists() else {"endpoint": endpoint}
        if self.data["endpoint"] != endpoint:
            raise ValueError("Journal belongs to another seat")

    def save(self):
        temporary = self.path.with_suffix(self.path.suffix + ".next")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w") as target:
            json.dump(self.data, target)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, self.path)
        directory = os.open(self.path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


def hold(observation):
    """Keep current upstream orders and mark the seat ready."""
    return {"orders": [], "ready": True}


def run(*, api, journal, policy, once):
    state = journal.data
    observed = api.call()
    current = observed["controller"]
    if "claim" not in state:
        state["claim"] = {
            "id": uuid.uuid4().hex,
            "expectedGeneration": current["generation"] if current else 0,
            "leaseMs": 180_000,
        }
        journal.save()
    claim = state["claim"]
    controller = api.call(path="/controller", value=claim)
    stop = threading.Event()
    lease_lost = threading.Event()

    def heartbeat():
        while not stop.wait(30):
            try:
                api.call(
                    path="/heartbeat",
                    value={
                        "controllerId": controller["id"],
                        "generation": controller["generation"],
                    },
                )
            except (HTTPError, URLError, TimeoutError, OSError):
                lease_lost.set()
                return

    thread = threading.Thread(target=heartbeat, name="seat-heartbeat")
    thread.start()
    try:
        while not lease_lost.is_set():
            observed = api.call(path="?waitMs=10000")
            snapshot = observed["snapshot"]
            if snapshot and snapshot["finished"]:
                return
            if observed["controller"] and observed["controller"]["id"] != controller["id"]:
                raise RuntimeError("Another controller took this seat")
            if not observed["available"] or not snapshot or not snapshot["window"]:
                time.sleep(1)
                continue
            window = snapshot["window"]
            pending = state.get("pending")
            if not pending:
                if state.get("completedWindow") == window["id"]:
                    if once:
                        return
                    time.sleep(1)
                    continue
                action = policy(snapshot["observation"])
                if lease_lost.is_set():
                    break
                pending = {
                    "id": uuid.uuid4().hex,
                    "controllerId": controller["id"],
                    "generation": controller["generation"],
                    "windowId": window["id"],
                    "kind": "orders",
                    "value": action,
                }
                state["pending"] = pending
                journal.save()
            try:
                receipt = api.call(path="/commands/" + pending["id"])
            except HTTPError as error:
                if error.code != 404:
                    raise
                receipt = api.call(path="/commands", value=pending)
            if receipt["status"] == "received":
                time.sleep(1)
                continue
            if receipt["status"] != "applied":
                raise RuntimeError("Command was not confirmed; inspect its receipt and board before continuing")
            state["completedWindow"] = pending["windowId"]
            del state["pending"]
            journal.save()
            print("Orders applied.")
            if once:
                return
        raise RuntimeError("Controller lease could not be renewed")
    finally:
        stop.set()
        thread.join()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("endpoint", help="Seat endpoint from Universe's Connect a bot view")
    parser.add_argument("--journal", required=True, type=Path)
    parser.add_argument("--policy", help="Importable module:function taking the private observation")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    url = urlsplit(args.endpoint)
    if url.username or url.password or url.query or url.fragment:
        parser.error("Use the seat endpoint without credentials or query parameters")
    if url.scheme != "https" and not (url.scheme == "http" and url.hostname in ("localhost", "127.0.0.1")):
        parser.error("Remote seats require HTTPS")
    token = os.environ.get("UNIVERSE_SEAT_TOKEN")
    if not token:
        parser.error("Set UNIVERSE_SEAT_TOKEN privately in the environment")
    policy = hold
    if args.policy:
        module, function = args.policy.split(":", 1)
        policy = getattr(importlib.import_module(module), function)
    try:
        run(
            api=Api(endpoint=args.endpoint, token=token),
            journal=Journal(path=args.journal, endpoint=args.endpoint),
            policy=policy,
            once=args.once,
        )
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        raise SystemExit("Connection interrupted. Restart with the same journal to reconcile delivery.") from error


if __name__ == "__main__":
    main()
