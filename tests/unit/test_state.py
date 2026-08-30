"""SQLite state store: idempotency, resume, cleanup scoping."""

import sqlite3
import stat
from pathlib import Path

import pytest

from allwr_toolkit.core.errors import StateError
from allwr_toolkit.core.state import StateStore


def make_run(state: StateStore, run_id: str = "run1") -> None:
    state.create_run(
        run_id=run_id,
        source_system="asana",
        source_scope="export:test",
        target_base_url="https://allwr.example.com/api/v1",
        target_project_id=42,
        plan_hash="abc",
    )


def test_mark_created_and_idempotency(tmp_path: Path) -> None:
    with StateStore(tmp_path / "s.db") as state:
        make_run(state)
        assert not state.is_created("run1", "task", "t1")
        state.mark(
            run_id="run1",
            record_type="task",
            source_record_id="t1",
            status="created",
            target_record_id="900",
        )
        assert state.is_created("run1", "task", "t1")
        record = state.get_record("run1", "task", "t1")
        assert record is not None and record.target_record_id == "900"


def test_failed_then_created_keeps_target_and_counts_attempts(tmp_path: Path) -> None:
    with StateStore(tmp_path / "s.db") as state:
        make_run(state)
        state.mark(
            run_id="run1", record_type="task", source_record_id="t1", status="failed", error="boom"
        )
        state.mark(
            run_id="run1",
            record_type="task",
            source_record_id="t1",
            status="created",
            target_record_id="901",
        )
        record = state.get_record("run1", "task", "t1")
        assert record is not None
        assert record.status == "created"
        assert record.attempt_count == 2


def test_cleanup_manifest_scoped_to_its_run(tmp_path: Path) -> None:
    with StateStore(tmp_path / "s.db") as state:
        make_run(state, "run1")
        make_run(state, "run2")
        state.mark(
            run_id="run1",
            record_type="task",
            source_record_id="a",
            status="created",
            target_record_id="1",
        )
        state.mark(
            run_id="run2",
            record_type="task",
            source_record_id="b",
            status="created",
            target_record_id="2",
        )
        state.mark(run_id="run1", record_type="task", source_record_id="c", status="failed")
        created = state.created_records("run1")
        assert [r.source_record_id for r in created] == ["a"]


def test_cancelled_run_stays_resumable(tmp_path: Path) -> None:
    path = tmp_path / "s.db"
    with StateStore(path) as state:
        make_run(state)
        state.mark(
            run_id="run1",
            record_type="task",
            source_record_id="t1",
            status="created",
            target_record_id="900",
        )
        state.set_run_status("run1", "cancelled")
    # Reopen: everything is still there.
    with StateStore(path) as state:
        run = state.get_run("run1")
        assert run is not None and run.status == "cancelled"
        assert state.is_created("run1", "task", "t1")
        state.set_run_status("run1", "running")
        run = state.get_run("run1")
        assert run is not None and run.status == "running"


def test_newer_schema_rejected(tmp_path: Path) -> None:
    path = tmp_path / "s.db"
    StateStore(path).close()
    conn = sqlite3.connect(path)
    conn.execute("UPDATE schema_version SET version = 999")
    conn.commit()
    conn.close()
    with pytest.raises(StateError, match="newer"):
        StateStore(path)


def test_state_file_is_owner_only(tmp_path: Path) -> None:
    path = tmp_path / "s.db"
    StateStore(path).close()
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600


def test_no_token_columns(tmp_path: Path) -> None:
    """The schema has no place for credentials - by construction."""
    path = tmp_path / "s.db"
    StateStore(path).close()
    conn = sqlite3.connect(path)
    columns = [
        row[1]
        for table in ("runs", "records")
        for row in conn.execute(f"PRAGMA table_info({table})")
    ]
    conn.close()
    assert not any("token" in c or "secret" in c or "key" in c for c in columns)
