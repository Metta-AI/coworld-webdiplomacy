"""Short SQLite transactions; only the collector changes source snapshots."""
import json
import sqlite3
from contextlib import contextmanager

from .config import POLL_SECONDS
from .paths import PACKAGE


class Store:
    def __init__(self, directory):
        self.directory = directory
        self.path = directory / "desk.sqlite3"

    def initialize(self):
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory.chmod(0o700)
        with self.connection() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise RuntimeError("Unsupported cache schema; use the matching League Desk version")
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript((PACKAGE / "schema.sql").read_text())
        self.path.chmod(0o600)

    @contextmanager
    def connection(self, readonly=False):
        target = self.path.as_uri() + "?mode=ro" if readonly else str(self.path)
        db = sqlite3.connect(target, uri=readonly, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def source(self, name, scope):
        with self.connection(True) as db:
            row = db.execute("SELECT * FROM sources WHERE name=? AND scope=?", (name, scope)).fetchone()
        return self.decode(row) if row else None

    @staticmethod
    def decode(row):
        return {**dict(row), "data": json.loads(row["data"]) if row["data"] is not None else None}

    def snapshot(self):
        if not self.path.exists():
            return {}
        with self.connection(True) as db:
            return {(r["name"], r["scope"]): self.decode(r) for r in db.execute(
                "SELECT sources.*, (SELECT max(observed_at) FROM observations o "
                "WHERE o.name=sources.name AND o.scope=sources.scope) AS observed_at FROM sources"
            )}

    def success(self, name, scope, data, now, observed=False):
        encoded = json.dumps(data, sort_keys=True, allow_nan=False)
        with self.connection() as db:
            if observed:
                previous = db.execute(
                    "SELECT data FROM observations WHERE name=? AND scope=? ORDER BY observed_at DESC LIMIT 1",
                    (name, scope),
                ).fetchone()
                if not previous or previous[0] != encoded:
                    db.execute("INSERT INTO observations VALUES (?, ?, ?, ?)", (name, scope, now, encoded))
            db.execute(
                "INSERT INTO sources VALUES (?, ?, ?, ?, ?, ?, 0, NULL) ON CONFLICT(name, scope) DO UPDATE SET "
                "data=excluded.data, attempted_at=excluded.attempted_at, fetched_at=excluded.fetched_at, "
                "next_due=excluded.next_due, failures=0, error=NULL",
                (name, scope, encoded, now, now, now + POLL_SECONDS),
            )

    def failure(self, name, scope, message, now, delay):
        with self.connection() as db:
            db.execute(
                "INSERT INTO sources(name, scope, attempted_at, next_due, failures, error) VALUES (?, ?, ?, ?, 1, ?) "
                "ON CONFLICT(name, scope) DO UPDATE SET attempted_at=excluded.attempted_at, "
                "next_due=excluded.next_due, failures=sources.failures+1, error=excluded.error",
                (name, scope, now, now + delay, message),
            )

    def retry_not_before(self):
        with self.connection(True) as db:
            return db.execute("SELECT retry_not_before FROM control").fetchone()[0]

    def defer(self, until):
        with self.connection() as db:
            db.execute("UPDATE control SET retry_not_before=max(retry_not_before, ?)", (until,))
