"""Plan building, serialization and verification.

The plan is the contract between "what will happen" and "what is allowed to
happen": apply refuses to run unless the plan hash and the target identity
still match. High severity warnings block apply unless each warning code has
been explicitly accepted in configuration.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

import allwr_toolkit
from allwr_toolkit.configuration import MigrationConfig, config_hash
from allwr_toolkit.core.errors import PlanValidationError
from allwr_toolkit.core.mapping import Mapper
from allwr_toolkit.core.models import (
    CanonicalTask,
    MigrationWarning,
    Severity,
    UnsupportedField,
)
from allwr_toolkit.security import restrict

OperationType = Literal["create_task", "add_comment", "upload_attachment", "create_relationship"]


class PlannedOperation(BaseModel):
    op: OperationType
    source_record_id: str
    client_request_id: str
    detail: str = ""


class PlanSource(BaseModel):
    system: str
    scope: str
    connector_version: str


class PlanTarget(BaseModel):
    base_url: str
    project_id: int
    section_open: int | None = None
    section_done: int | None = None
    import_source: str
    import_batch_id: int | None = None
    environment: str = "sandbox"


class MigrationPlan(BaseModel):
    plan_version: int = 1
    run_id: str
    created_at: datetime
    toolkit_version: str
    source: PlanSource
    target: PlanTarget
    config_hash: str
    counts: dict[str, int] = Field(default_factory=dict)
    selected_ids: list[str] = Field(default_factory=list)
    excluded_ids: list[str] = Field(default_factory=list)
    duplicate_suspects: list[list[str]] = Field(default_factory=list)
    unsupported_fields: list[UnsupportedField] = Field(default_factory=list)
    warnings: list[MigrationWarning] = Field(default_factory=list)
    operations: list[PlannedOperation] = Field(default_factory=list)
    attachments_bytes_estimate: int = 0
    plan_hash: str = ""

    @property
    def write_count(self) -> int:
        return len(self.operations)


def compute_plan_hash(plan: MigrationPlan) -> str:
    payload = plan.model_dump(mode="json", exclude={"plan_hash"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def client_request_id(system: str, kind: str, source_id: str) -> str:
    """Deterministic idempotency key for one write, stable across re-runs."""
    return f"{system}-{kind}-{source_id}"[:64]


def _task_operations(
    system: str, task: CanonicalTask, include_attachments: bool
) -> list[PlannedOperation]:
    ops: list[PlannedOperation] = [
        PlannedOperation(
            op="create_task",
            source_record_id=task.source.record_id,
            client_request_id=client_request_id(system, "task", task.source.record_id),
            detail=task.title[:80],
        )
    ]
    for comment in task.comments:
        ops.append(
            PlannedOperation(
                op="add_comment",
                source_record_id=task.source.record_id,
                client_request_id=client_request_id(system, "comment", comment.source_id),
            )
        )
    if include_attachments:
        for att in task.attachments:
            if att.is_external_link:
                continue
            ops.append(
                PlannedOperation(
                    op="upload_attachment",
                    source_record_id=task.source.record_id,
                    client_request_id=client_request_id(system, "attachment", att.source_id),
                    detail=att.name[:80],
                )
            )
    for sub in task.subtasks:
        ops.extend(_task_operations(system, sub, include_attachments))
        ops.append(
            PlannedOperation(
                op="create_relationship",
                source_record_id=sub.source.record_id,
                client_request_id=client_request_id(system, "rel", sub.source.record_id),
                detail="subtask_of",
            )
        )
    return ops


def build_plan(
    records: list[CanonicalTask],
    config: MigrationConfig,
    *,
    connector_version: str,
    source_scope: str,
    excluded_ids: list[str] | None = None,
    unsupported_fields: list[UnsupportedField] | None = None,
    extra_warnings: list[MigrationWarning] | None = None,
) -> MigrationPlan:
    """Build a migration plan from canonical records and configuration."""
    mapper = Mapper(config.mapping)
    system = config.connector
    warnings: list[MigrationWarning] = list(extra_warnings or [])
    unsupported: list[UnsupportedField] = list(unsupported_fields or [])
    operations: list[PlannedOperation] = []
    selected: list[str] = []
    excluded: list[str] = list(excluded_ids or [])
    attachments_bytes = 0

    seen_titles: dict[str, list[str]] = {}
    for task in records:
        if not config.options.include_completed and task.completed:
            excluded.append(task.source.record_id)
            continue
        if mapper.should_skip_for_user(task.assignee):
            excluded.append(task.source.record_id)
            warnings.append(
                MigrationWarning(
                    code="record_skipped_unknown_user",
                    severity=Severity.MEDIUM,
                    message="record skipped: assignee has no user mapping (policy 'skip')",
                    record_id=task.source.record_id,
                )
            )
            continue
        selected.append(task.source.record_id)
        seen_titles.setdefault(task.title.strip().lower(), []).append(task.source.record_id)
        operations.extend(_task_operations(system, task, config.options.include_attachments))
        for att in task.attachments:
            if att.size_bytes and not att.is_external_link:
                attachments_bytes += att.size_bytes
            if att.is_external_link:
                warnings.append(
                    MigrationWarning(
                        code="external_attachment_linked",
                        severity=Severity.INFO,
                        message=f"attachment '{att.name}' is externally hosted; linked, not copied",
                        record_id=task.source.record_id,
                    )
                )
        for user in [task.assignee, task.created_by, *task.followers]:
            if user is not None:
                mapper.map_user(user)

    # Duplicate-looking records are reported, never merged: distinct source ids
    # remain distinct records by design.
    duplicate_suspects = [ids for ids in seen_titles.values() if len(ids) > 1]
    for ids in duplicate_suspects:
        warnings.append(
            MigrationWarning(
                code="duplicate_suspect",
                severity=Severity.INFO,
                message=f"{len(ids)} records share the same title; they stay distinct records",
                record_id=ids[0],
            )
        )

    for key in mapper.unknown_users:
        warnings.append(
            MigrationWarning(
                code="unknown_user",
                severity=Severity.MEDIUM,
                message=f"source user '{key}' has no mapping; policy '{mapper.on_unknown_user}'",
            )
        )

    unsupported_severity = Severity.HIGH if config.options.stop_on_data_loss else Severity.MEDIUM
    for field in unsupported:
        warnings.append(
            MigrationWarning(
                code="unsupported_field",
                severity=unsupported_severity,
                message=f"field '{field.field}' is not supported: {field.reason}",
                record_id=field.record_id,
            )
        )

    plan = MigrationPlan(
        run_id=uuid.uuid4().hex,
        created_at=datetime.now(tz=UTC),
        toolkit_version=allwr_toolkit.__version__,
        source=PlanSource(system=system, scope=source_scope, connector_version=connector_version),
        target=PlanTarget(
            base_url=config.target.base_url,
            project_id=config.target.project_id,
            section_open=config.target.section_open,
            section_done=config.target.section_done,
            import_source=config.import_source,
            import_batch_id=config.target.import_batch_id,
            environment=config.target.environment,
        ),
        config_hash=config_hash(config),
        counts={
            "selected": len(selected),
            "excluded": len(excluded),
            "operations": len(operations),
            "comments": sum(1 for o in operations if o.op == "add_comment"),
            "attachments": sum(1 for o in operations if o.op == "upload_attachment"),
        },
        selected_ids=selected,
        excluded_ids=excluded,
        duplicate_suspects=duplicate_suspects,
        unsupported_fields=unsupported,
        warnings=warnings,
        operations=operations,
        attachments_bytes_estimate=attachments_bytes,
    )
    plan.plan_hash = compute_plan_hash(plan)
    return plan


def save_plan(plan: MigrationPlan, path: str | Path) -> Path:
    file = Path(path)
    file.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    restrict(file)
    return file


def load_plan(path: str | Path) -> MigrationPlan:
    file = Path(path)
    if not file.is_file():
        raise PlanValidationError(f"plan file not found: {file}")
    try:
        plan = MigrationPlan.model_validate_json(file.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise PlanValidationError(f"cannot parse plan {file.name}: {exc}") from exc
    return plan


def verify_plan(plan: MigrationPlan, config: MigrationConfig) -> None:
    """Raise :class:`PlanValidationError` unless the plan is intact and matches
    the configured target. Called before every apply, resume or MCP write."""
    expected = compute_plan_hash(plan)
    if plan.plan_hash != expected:
        raise PlanValidationError(
            "plan hash mismatch: the plan file changed after it was generated"
        )
    if plan.target.base_url != config.target.base_url:
        raise PlanValidationError(
            f"plan targets {plan.target.base_url} but configuration targets "
            f"{config.target.base_url}"
        )
    if plan.target.project_id != config.target.project_id:
        raise PlanValidationError(
            f"plan targets project {plan.target.project_id} but configuration targets "
            f"project {config.target.project_id}"
        )
    if plan.config_hash != config_hash(config):
        raise PlanValidationError(
            "configuration changed since the plan was generated; regenerate the plan"
        )


def blocking_warnings(plan: MigrationPlan, accepted: list[str]) -> list[MigrationWarning]:
    """High severity warnings whose code has not been explicitly accepted."""
    return [w for w in plan.warnings if w.severity is Severity.HIGH and w.code not in accepted]
