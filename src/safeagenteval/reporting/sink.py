"""Where run records go: per-run JSON files, or a SQLite run store.

A record sink is the harness's only output dependency. ``file`` keeps the
historical behavior (one JSON document per run, human-inspectable).
``sqlite`` stores the same records in a single database file with indexed
scenario/agent/passed columns, so run history across vendors and months
can be queried without scanning directories. Both sinks store the full
``SavedRunRecord`` JSON; the database is an index over it, not a second
schema that could drift.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Protocol

from safeagenteval.reporting.report import SavedRunRecord

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT,
    scenario_id TEXT NOT NULL,
    agent TEXT NOT NULL,
    repeat INTEGER NOT NULL,
    passed INTEGER NOT NULL,
    completed INTEGER NOT NULL,
    recorded_order INTEGER PRIMARY KEY AUTOINCREMENT,
    record_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_scenario ON runs (scenario_id);
CREATE INDEX IF NOT EXISTS idx_runs_agent ON runs (agent);
CREATE INDEX IF NOT EXISTS idx_runs_passed ON runs (passed);
"""


class RecordSink(Protocol):
    """A destination for completed run records."""

    def write(self, record: SavedRunRecord) -> None:
        """Persist one run record."""
        ...

    def close(self) -> None:
        """Flush and release any held resources."""
        ...


class FileRecordSink:
    """One ``<scenario>[.rN].json`` file per run under a directory."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory
        directory.mkdir(parents=True, exist_ok=True)

    def write(self, record: SavedRunRecord) -> None:
        suffix = "" if record.repeat == 0 else f".r{record.repeat + 1}"
        name = f"{record.scenario_id}{suffix}.json"
        if record.run_id:
            name = f"{record.scenario_id}{suffix}.{record.run_id[:8]}.json"
        (self._directory / name).write_text(record.model_dump_json(indent=2), encoding="utf-8")

    def close(self) -> None:
        pass


class SqliteRecordSink:
    """Run records in a SQLite database (stdlib only, no server needed)."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path)
        self._connection.executescript(_SCHEMA)

    def write(self, record: SavedRunRecord) -> None:
        self._connection.execute(
            "INSERT INTO runs (run_id, scenario_id, agent, repeat, passed, completed,"
            " record_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                record.run_id,
                record.scenario_id,
                record.agent,
                record.repeat,
                int(record.passed),
                int(record.completed),
                record.model_dump_json(),
            ),
        )
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()


def build_sink(kind: str, out: Path) -> RecordSink:
    """Build the sink named by ``kind`` writing at ``out``."""
    if kind == "file":
        return FileRecordSink(out)
    if kind == "sqlite":
        return SqliteRecordSink(out)
    raise ValueError(f"unknown sink {kind!r} (file | sqlite)")


def load_records(source: Path) -> list[SavedRunRecord]:
    """Load run records from a directory of JSON files or a SQLite store."""
    if source.is_file():
        connection = sqlite3.connect(source)
        try:
            rows = connection.execute(
                "SELECT record_json FROM runs ORDER BY recorded_order"
            ).fetchall()
        finally:
            connection.close()
        return [SavedRunRecord.model_validate_json(row[0]) for row in rows]
    from safeagenteval.reporting.report import load_run_files

    return load_run_files(source)
