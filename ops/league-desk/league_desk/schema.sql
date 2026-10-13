-- Selected-field snapshots; history scans carry explicit completeness and cursor state.
CREATE TABLE IF NOT EXISTS sources (
    name TEXT NOT NULL,
    scope TEXT NOT NULL,
    data TEXT,
    attempted_at REAL,
    fetched_at REAL,
    next_due REAL NOT NULL DEFAULT 0,
    failures INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    PRIMARY KEY (name, scope)
);
CREATE TABLE IF NOT EXISTS control (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    retry_not_before REAL NOT NULL DEFAULT 0
);
INSERT OR IGNORE INTO control(singleton) VALUES (1);
-- Observations are not release timestamps or retroactive settings history.
CREATE TABLE IF NOT EXISTS observations (
    name TEXT NOT NULL,
    scope TEXT NOT NULL,
    observed_at REAL NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (name, scope, observed_at)
);
PRAGMA user_version = 1;
