"""Own daemon lifetimes without changing process identities."""

import signal
import subprocess
import threading
import time
from pathlib import Path

RUN = Path("/run/webdip")


class Supervisor:
    def __init__(self):
        self.stopping = threading.Event()
        self.children = []
        self.ready = False

    def start(self, name, command, cwd=None):
        with (RUN / "logs" / f"{name}.log").open("ab") as log:
            child = subprocess.Popen(command, cwd=cwd, stdout=log, stderr=log)
        self.children.append((name, child))

    def check(self):
        for name, child in self.children:
            if child.poll() is not None:
                raise RuntimeError(f"{name} exited ({child.returncode})")

    def wait_for(self, probe, name, timeout=20):
        deadline = time.monotonic() + timeout
        while not self.stopping.is_set():
            self.check()
            if probe():
                return
            if time.monotonic() >= deadline:
                raise RuntimeError(f"{name} readiness timed out")
            self.stopping.wait(0.05)
        raise InterruptedError("shutdown requested")

    def shutdown(self):
        self.ready = False
        # Stop the producer, HTTP ingress and PHP before the database and Redis.
        forced = []
        for name, child in reversed(self.children):
            if child.poll() is None:
                child.send_signal(signal.SIGQUIT if name in ("nginx", "php-fpm") else signal.SIGTERM)
                try:
                    child.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
                    forced.append(name)
        if forced:
            raise RuntimeError(f"forced shutdown: {forced}")
