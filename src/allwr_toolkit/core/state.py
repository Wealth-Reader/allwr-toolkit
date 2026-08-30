"""SQLite migration state store: checkpoints, resume and idempotency.

The state store keeps the minimum needed to resume and to prevent duplicates:
identifiers, statuses, attempts and checksums. It never stores tokens and it
never stores record bodies.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from allwr_toolkit.core.errors import StateError
from allwr_toolkit.security import restrict

SCHEMA_VERSION = 1

RecordStatus = Literal["pending", "created", "failed", "skipped"]


class RecordState(BaseModel):
    run_id: str
    source_record_id: str
    record_type: str
    status: RecordStatus
    target_record_id: str | None = None
    attempt_count: int = 0
    last_error: str | None = None
    checksum: str | None = None
    updated_at: str | None = None


class RunState(BaseModel):
    run_id: str
    source_system: str
    source_scope: str
    target_base_url: str
    target_project_id: int
    plan_hash: str
    status: Literal["running", "completed", "cancelled", "failed"]
    created_at: str
    updated_at: str


def _now() -> str:
    return datetime.now(tz=UTC).isoformat()


class StateStore:
    """One SQLite file per migration effort; safe to reopen at any time."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        existed = self._path.exists()
        self._conn = sqlite3.connect(self._path)
        self._conn.row_factory = sqlite3.Row
        self._migrate()
        if not existed:
            restrict(self._path)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> StateStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- schema ------------------------------------------------------------

    def _migrate(self) -> None:
        cur = self._conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
        row = cur.execute("SELECT version FROM schema_version").fetchone()
        if row is None:
            cur.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
        elif row["version"] > SCHEMA_VERSION:
            raise StateError(
                f"state file {self._path.name} uses schema v{row['version']}, newer than "
                f"this toolkit (v{SCHEMA_VERSION}); upgrade the toolkit"
            )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                source_system TEXT NOT NULL,
                source_scope TEXT NOT NULL,
                target_base_url TEXT NOT NULL,
                target_project_id INTEGER NOT NULL,
                plan_hash TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS records (
                run_id TEXT NOT NULL,
                source_record_id TEXT NOT NULL,
                record_type TEXT NOT NULL,
                status TEXT NOT NULL,
                target_record_id TEXT,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                checksum TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (run_id, record_type, source_record_id)
            )
            """
        )
        self._conn.commit()

    # -- runs --------------------------------------------------------------

    def create_run(
        self,
        *,
        run_id: str,
        source_system: str,
        source_scope: str,
        target_base_url: str,
        target_project_id: int,
        plan_hash: str,
    ) -> None:
        now = _now()
        self._conn.execute(
            """
            INSERT OR IGNORE INTO runs
              (run_id, source_system, source_scope, target_base_url,
               target_project_id, plan_hash, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'running', ?, ?)
            """,
            (
                run_id,
                source_system,
                source_scope,
                target_base_url,
                target_project_id,
                plan_hash,
                now,
                now,
            ),
        )
        self._conn.commit()

    def get_run(self, run_id: str) -> RunState | None:
        row = self._conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return RunState(**dict(row)) if row else None

    def set_run_status(
        self, run_id: str, status: Literal["running", "completed", "cancelled", "failed"]
    ) -> None:
        self._conn.execute(
            "UPDATE runs SET status = ?, updated_at = ? WHERE run_id = ?",
            (status, _now(), run_id),
        )
        self._conn.commit()

    def list_runs(self) -> list[RunState]:
        rows = self._conn.execute("SELECT * FROM runs ORDER BY created_at").fetchall()
        return [RunState(**dict(r)) for r in rows]

    # -- records -----------------------------------------------------------

    def get_record(
        self, run_id: str, record_type: str, source_record_id: str
    ) -> RecordState | None:
        row = self._conn.execute(
            "SELECT * FROM records WHERE run_id = ? AND record_type = ? AND source_record_id = ?",
            (run_id, record_type, source_record_id),
        ).fetchone()
        return RecordState(**dict(row)) if row else None

    def is_created(self, run_id: str, record_type: str, source_record_id: str) -> bool:
        rec = self.get_record(run_id, record_type, source_record_id)
        return rec is not None and rec.status == "created"

    def mark(
        self,
        *,
        run_id: str,
        record_type: str,
        source_record_id: str,
        status: RecordStatus,
        target_record_id: str | None = None,
        error: str | None = None,
        checksum: str | None = None,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO records
              (run_id, record_type, source_record_id, status, target_record_id,
               attempt_count, last_error, checksum, updated_at)
            VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)
            ON CONFLICT (run_id, record_type, source_record_id) DO UPDATE SET
              status = excluded.status,
              target_record_id = COALESCE(excluded.target_record_id, target_record_id),
              attempt_count = records.attempt_count + 1,
              last_error = excluded.last_error,
              checksum = COALESCE(excluded.checksum, records.checksum),
              updated_at = excluded.updated_at
            """,
            (
                run_id,
                record_type,
                source_record_id,
                status,
                target_record_id,
                error,
                checksum,
                _now(),
            ),
        )
        self._conn.commit()

    def records_for_run(self, run_id: str, status: RecordStatus | None = None) -> list[RecordState]:
        if status is None:
            rows = self._conn.execute(
                "SELECT * FROM records WHERE run_id = ? ORDER BY updated_at", (run_id,)
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM records WHERE run_id = ? AND status = ? ORDER BY updated_at",
                (run_id, status),
            ).fetchall()
        return [RecordState(**dict(r)) for r in rows]

    def created_records(self, run_id: str) -> list[RecordState]:
        """Records created by *this run only* - the cleanup manifest source."""
        return self.records_for_run(run_id, status="created")


@contextmanager
def open_state(path: str | Path) -> Iterator[StateStore]:
    store = StateStore(path)
    try:
        yield store
    finally:
        store.close()
