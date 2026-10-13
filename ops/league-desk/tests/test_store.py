from helpers import DeskTest


class StoreTests(DeskTest):
    def test_readonly_cannot_mutate(self):
        import sqlite3
        with self.store.connection(True) as db:
            with self.assertRaises(sqlite3.OperationalError):
                db.execute("DELETE FROM sources")

    def test_initialize_is_idempotent_and_private(self):
        self.store.success("test", "demo", {"amount": None}, self.now)
        self.store.initialize()
        self.assertEqual(self.store.source("test", "demo")["data"], {"amount": None})
        self.assertEqual(self.store.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.store.directory.stat().st_mode & 0o777, 0o700)

    def test_future_schema_rejected(self):
        with self.store.connection() as db:
            db.execute("PRAGMA user_version=999")
        with self.assertRaisesRegex(RuntimeError, "Unsupported cache"):
            self.store.initialize()

    def test_invalid_json_write_leaves_old_data(self):
        self.store.success("test", "demo", {"amount": 3}, self.now)
        with self.assertRaises(ValueError):
            self.store.success("test", "demo", {"amount": float("nan")}, self.now + 1)
        self.assertEqual(self.store.source("test", "demo")["data"], {"amount": 3})
