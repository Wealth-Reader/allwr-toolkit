"""Cancellation and resume: interrupted migrations continue from checkpoints."""

import threading
from pathlib import Path

import pytest
import respx

from allwr_toolkit.api.allwr import AllwrClient
from allwr_toolkit.cli import workflows
from allwr_toolkit.core.state import StateStore
from tests.integration.test_apply_flow import FakeAllwr, prepare


@pytest.fixture(autouse=True)
def fast_client(monkeypatch: pytest.MonkeyPatch, allwr_key: str) -> None:
    monkeypatch.setattr(AllwrClient, "_sleep", lambda self, s: None)


@respx.mock
def test_cancel_mid_run_then_resume_completes(config_file: Path, tmp_path: Path) -> None:
    fake = FakeAllwr()
    fake.install()
    plan_path, state_path = prepare(config_file, tmp_path)

    cancel = threading.Event()

    def cancel_after_first(record_id: str, status: str) -> None:
        cancel.set()  # stop after the first completed unit

    # Interrupted run: only the first unit lands.
    config = config_file
    from allwr_toolkit.configuration import load_config
    from allwr_toolkit.core.execution import ExecutionEngine
    from allwr_toolkit.core.planning import load_plan

    loaded_config = load_config(config)
    plan = load_plan(plan_path)
    connector = workflows.make_connector(loaded_config)
    _, records = workflows.collect_records(connector)
    with StateStore(state_path) as state, AllwrClient(loaded_config.target.base_url) as client:
        engine = ExecutionEngine(state=state, client=client, dry_run=False)
        result = engine.apply(
            plan, records, loaded_config, cancel=cancel, on_progress=cancel_after_first
        )
    assert result.cancelled is True
    assert result.created == 2  # first unit = parent + rich subtask
    with StateStore(state_path) as state:
        run = state.get_run(plan.run_id)
        assert run is not None and run.status == "cancelled"
        assert state.is_created(plan.run_id, "task", "1200000000000001")
        assert not state.is_created(plan.run_id, "task", "1200000000000004")

    # Resume: picks up from the checkpoint, does not duplicate the first unit.
    resumed = workflows.resume_migration(
        config_file, plan_path, plan.run_id, state_path=state_path, dry_run=False
    )
    assert resumed.cancelled is False
    assert resumed.skipped == 2
    assert resumed.created == 1  # only the remaining unit
    assert len(fake.tasks) == 3
    with StateStore(state_path) as state:
        run = state.get_run(plan.run_id)
        assert run is not None and run.status == "completed"


@respx.mock
def test_cli_cancel_marks_run_resumable(config_file: Path, tmp_path: Path) -> None:
    fake = FakeAllwr()
    fake.install()
    plan_path, state_path = prepare(config_file, tmp_path)
    result = workflows.run_migration(config_file, plan_path, state_path=state_path, dry_run=False)
    run = workflows.cancel_migration(result.run_id, state_path=state_path)
    assert run.status == "cancelled"
    status = workflows.migration_status(result.run_id, state_path=state_path)
    assert status["run"]["status"] == "cancelled"
    # Still resumable (everything already created -> all skipped).
    resumed = workflows.resume_migration(
        config_file, plan_path, result.run_id, state_path=state_path, dry_run=False
    )
    assert resumed.skipped == 3
