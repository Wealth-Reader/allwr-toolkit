"""Shared migration workflows used by both the CLI and the MCP server.

Everything here is plan-driven: inspect reads, plan writes a plan file, apply
consumes a *validated* plan. The MCP server reuses these functions so an AI
agent cannot reach a code path the CLI does not have.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from allwr_toolkit.api.allwr import AllwrClient
from allwr_toolkit.configuration import MigrationConfig, load_config
from allwr_toolkit.connectors.base import InspectionSummary, SourceConnector, get_connector
from allwr_toolkit.core.errors import PlanValidationError, StateError
from allwr_toolkit.core.execution import ExecutionEngine, ExecutionResult
from allwr_toolkit.core.models import CanonicalTask
from allwr_toolkit.core.planning import (
    MigrationPlan,
    build_plan,
    load_plan,
    save_plan,
    verify_plan,
)
from allwr_toolkit.core.reporting import generate_reports
from allwr_toolkit.core.state import RunState, StateStore

DEFAULT_STATE_FILE = "migration-state.db"
DEFAULT_PLAN_FILE = "migration-plan.json"


def make_connector(config: MigrationConfig) -> SourceConnector:
    connector_cls = get_connector(config.connector)
    return connector_cls(config.source)


def connector_version(connector: SourceConnector) -> str:
    return str(getattr(type(connector), "VERSION", None) or "0.1.0")


def inspect_source(config_path: str | Path) -> InspectionSummary:
    config = load_config(config_path)
    connector = make_connector(config)
    return connector.inspect()


def collect_records(
    connector: SourceConnector,
) -> tuple[list[CanonicalTask], dict[str, CanonicalTask]]:
    records = list(connector.iter_records())
    return records, {r.source.record_id: r for r in records}


def generate_plan(config_path: str | Path, plan_path: str | Path) -> MigrationPlan:
    config = load_config(config_path)
    connector = make_connector(config)
    records, _ = collect_records(connector)
    plan = build_plan(
        records,
        config,
        connector_version=connector_version(connector),
        source_scope=getattr(connector, "scope", "unknown"),
        unsupported_fields=list(getattr(connector, "unsupported_fields", [])),
        extra_warnings=list(getattr(connector, "warnings", [])),
    )
    save_plan(plan, plan_path)
    return plan


class TargetConfirmation(BaseModel):
    """Shown (and required reading) before any apply."""

    base_url: str
    project_id: int
    environment: str
    records: int
    writes: int
    includes_attachments: bool
    attachments_bytes_estimate: int


def target_confirmation(plan: MigrationPlan) -> TargetConfirmation:
    return TargetConfirmation(
        base_url=plan.target.base_url,
        project_id=plan.target.project_id,
        environment=plan.target.environment,
        records=len(plan.selected_ids),
        writes=plan.write_count,
        includes_attachments=any(o.op == "upload_attachment" for o in plan.operations),
        attachments_bytes_estimate=plan.attachments_bytes_estimate,
    )


def run_migration(
    config_path: str | Path,
    plan_path: str | Path,
    *,
    state_path: str | Path = DEFAULT_STATE_FILE,
    dry_run: bool = True,
    cancel: threading.Event | None = None,
    report_dir: str | Path | None = None,
) -> ExecutionResult:
    """Execute (or dry-run) a previously generated plan."""
    config = load_config(config_path)
    plan = load_plan(plan_path)
    verify_plan(plan, config)
    connector = make_connector(config)
    _, records_by_id = collect_records(connector)
    with StateStore(state_path) as state:
        client: AllwrClient | None = None
        try:
            if not dry_run:
                client = AllwrClient(config.target.base_url)
            engine = ExecutionEngine(state=state, client=client, dry_run=dry_run)
            result = engine.apply(plan, records_by_id, config, cancel=cancel)
            if report_dir is not None:
                generate_reports(plan, result, state, report_dir)
            return result
        finally:
            if client is not None:
                client.close()


def resume_migration(
    config_path: str | Path,
    plan_path: str | Path,
    run_id: str,
    *,
    state_path: str | Path = DEFAULT_STATE_FILE,
    dry_run: bool = False,
    cancel: threading.Event | None = None,
    report_dir: str | Path | None = None,
) -> ExecutionResult:
    """Resume an interrupted or cancelled run from its last checkpoint."""
    plan = load_plan(plan_path)
    if plan.run_id != run_id:
        raise PlanValidationError(f"plan {plan_path} belongs to run {plan.run_id}, not {run_id}")
    with StateStore(state_path) as state:
        if state.get_run(run_id) is None:
            raise StateError(f"run {run_id} not found in state {state_path}")
        state.set_run_status(run_id, "running")
    return run_migration(
        config_path,
        plan_path,
        state_path=state_path,
        dry_run=dry_run,
        cancel=cancel,
        report_dir=report_dir,
    )


def migration_status(run_id: str, *, state_path: str | Path = DEFAULT_STATE_FILE) -> dict[str, Any]:
    with StateStore(state_path) as state:
        run = state.get_run(run_id)
        if run is None:
            raise StateError(f"run {run_id} not found in state {state_path}")
        records = state.records_for_run(run_id)
    by_status: dict[str, int] = {}
    for record in records:
        by_status[record.status] = by_status.get(record.status, 0) + 1
    return {"run": run.model_dump(), "records": by_status}


def cancel_migration(run_id: str, *, state_path: str | Path = DEFAULT_STATE_FILE) -> RunState:
    """Mark a run cancelled. The state stays fully resumable."""
    with StateStore(state_path) as state:
        run = state.get_run(run_id)
        if run is None:
            raise StateError(f"run {run_id} not found in state {state_path}")
        state.set_run_status(run_id, "cancelled")
        refreshed = state.get_run(run_id)
        assert refreshed is not None
        return refreshed


def migration_report(
    run_id: str,
    plan_path: str | Path,
    *,
    state_path: str | Path = DEFAULT_STATE_FILE,
    out_dir: str | Path = ".",
) -> dict[str, Path]:
    plan = load_plan(plan_path)
    if plan.run_id != run_id:
        raise PlanValidationError(f"plan {plan_path} belongs to run {plan.run_id}, not {run_id}")
    with StateStore(state_path) as state:
        if state.get_run(run_id) is None:
            raise StateError(f"run {run_id} not found in state {state_path}")
        records = state.records_for_run(run_id)
        result = ExecutionResult(
            run_id=run_id,
            dry_run=False,
            created=sum(1 for r in records if r.status == "created"),
            failed=sum(1 for r in records if r.status == "failed"),
            skipped=sum(1 for r in records if r.status == "skipped"),
        )
        return generate_reports(plan, result, state, out_dir)


def cleanup_manifest(run_id: str, *, state_path: str | Path = DEFAULT_STATE_FILE) -> dict[str, Any]:
    """Records created by this run only - the deterministic cleanup manifest."""
    with StateStore(state_path) as state:
        if state.get_run(run_id) is None:
            raise StateError(f"run {run_id} not found in state {state_path}")
        created = state.created_records(run_id)
    return {
        "run_id": run_id,
        "records": [
            {
                "record_type": r.record_type,
                "source_record_id": r.source_record_id,
                "target_record_id": r.target_record_id,
            }
            for r in created
        ],
    }
