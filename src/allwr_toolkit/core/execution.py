"""The execution engine: consumes a validated plan and writes to ALL WR.

Safety properties enforced here:

- dry-run is the default and performs zero target writes;
- apply refuses plans that fail verification (hash, target, blocked warnings);
- every write is idempotent (server-side external_ref / client_request_id,
  plus the local state store as a second guard);
- interruption and cancellation leave the state resumable;
- an attachment failure never corrupts the state of its task.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, Field

from allwr_toolkit.api.allwr import AllwrClient, CommentPayload, TaskPayload
from allwr_toolkit.configuration import MigrationConfig
from allwr_toolkit.core.errors import (
    BlockedByWarningsError,
    ConfigurationError,
    ToolkitError,
)
from allwr_toolkit.core.mapping import Mapper
from allwr_toolkit.core.models import CanonicalTask, MigrationWarning, Severity
from allwr_toolkit.core.planning import (
    MigrationPlan,
    blocking_warnings,
    client_request_id,
    verify_plan,
)
from allwr_toolkit.core.state import StateStore
from allwr_toolkit.security import install_redaction, redact

logger = logging.getLogger(__name__)
install_redaction(logger)


class RecordError(BaseModel):
    source_record_id: str
    operation: str
    message: str


class ExecutionResult(BaseModel):
    run_id: str
    dry_run: bool
    created: int = 0
    replayed: int = 0
    skipped: int = 0
    failed: int = 0
    comments_created: int = 0
    attachments_created: int = 0
    relationships_created: int = 0
    cancelled: bool = False
    errors: list[RecordError] = Field(default_factory=list)
    warnings: list[MigrationWarning] = Field(default_factory=list)


ProgressCallback = Callable[[str, str], None]


class ExecutionEngine:
    def __init__(
        self,
        *,
        state: StateStore,
        client: AllwrClient | None = None,
        dry_run: bool = True,
    ) -> None:
        if not dry_run and client is None:
            raise ConfigurationError("apply mode requires an ALL WR client")
        self._state = state
        self._client = client
        self._dry_run = dry_run

    def apply(
        self,
        plan: MigrationPlan,
        records: dict[str, CanonicalTask],
        config: MigrationConfig,
        *,
        cancel: threading.Event | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> ExecutionResult:
        verify_plan(plan, config)
        blocked = blocking_warnings(plan, config.options.accepted_warnings)
        if blocked:
            raise BlockedByWarningsError(
                "plan has high severity warnings that were not accepted",
                warning_codes=sorted({w.code for w in blocked}),
            )
        mapper = Mapper(config.mapping)
        result = ExecutionResult(run_id=plan.run_id, dry_run=self._dry_run)
        self._state.create_run(
            run_id=plan.run_id,
            source_system=plan.source.system,
            source_scope=plan.source.scope,
            target_base_url=plan.target.base_url,
            target_project_id=plan.target.project_id,
            plan_hash=plan.plan_hash,
        )
        for source_id in plan.selected_ids:
            if cancel is not None and cancel.is_set():
                result.cancelled = True
                self._state.set_run_status(plan.run_id, "cancelled")
                logger.info("run %s cancelled; state is resumable", plan.run_id)
                return result
            task = records.get(source_id)
            if task is None:
                result.failed += 1
                result.errors.append(
                    RecordError(
                        source_record_id=source_id,
                        operation="load",
                        message="record listed in plan but missing from source data",
                    )
                )
                continue
            self._apply_unit(task, plan, config, mapper, result, on_progress)
        if not result.cancelled:
            self._state.set_run_status(plan.run_id, "completed" if not result.failed else "failed")
        return result

    # -- one migration unit (a task and its rich subtasks) -----------------

    def _apply_unit(
        self,
        task: CanonicalTask,
        plan: MigrationPlan,
        config: MigrationConfig,
        mapper: Mapper,
        result: ExecutionResult,
        on_progress: ProgressCallback | None,
    ) -> None:
        try:
            parent_target = self._apply_task(task, plan, config, mapper, result)
        except ToolkitError as exc:
            self._record_failure(task, plan, result, "create_task", exc)
            return
        if on_progress is not None:
            on_progress(task.source.record_id, "done")
        stack = [(task, parent_target)]
        while stack:
            current, current_target = stack.pop()
            for sub in current.subtasks:
                try:
                    sub_target = self._apply_task(sub, plan, config, mapper, result)
                except ToolkitError as exc:
                    self._record_failure(sub, plan, result, "create_task", exc)
                    continue
                if (
                    not self._dry_run
                    and self._client is not None
                    and sub_target is not None
                    and current_target is not None
                ):
                    try:
                        self._client.create_relationship(sub_target, current_target)
                        result.relationships_created += 1
                    except ToolkitError as exc:
                        result.errors.append(
                            RecordError(
                                source_record_id=sub.source.record_id,
                                operation="create_relationship",
                                message=redact(str(exc)),
                            )
                        )
                stack.append((sub, sub_target))

    def _apply_task(
        self,
        task: CanonicalTask,
        plan: MigrationPlan,
        config: MigrationConfig,
        mapper: Mapper,
        result: ExecutionResult,
    ) -> int | None:
        source_id = task.source.record_id
        existing = self._state.get_record(plan.run_id, "task", source_id)
        if existing is not None and existing.status == "created":
            result.skipped += 1
            return int(existing.target_record_id) if existing.target_record_id else None
        if self._dry_run:
            result.created += 1
            return None
        assert self._client is not None  # guaranteed by constructor
        payload = build_task_payload(task, plan, config, mapper)
        created = self._client.create_task(payload)
        if created.replayed:
            result.replayed += 1
        else:
            result.created += 1
        target_id = created.id
        self._state.mark(
            run_id=plan.run_id,
            record_type="task",
            source_record_id=source_id,
            status="created",
            target_record_id=str(target_id) if target_id is not None else None,
        )
        if target_id is None:
            return None
        self._apply_comments(task, target_id, plan, config, mapper, result)
        if config.options.include_attachments:
            self._apply_attachments(task, target_id, plan, result)
        return target_id

    def _apply_comments(
        self,
        task: CanonicalTask,
        target_id: int,
        plan: MigrationPlan,
        config: MigrationConfig,
        mapper: Mapper,
        result: ExecutionResult,
    ) -> None:
        assert self._client is not None
        for comment in sorted(task.comments, key=lambda c: (c.created_at is None, c.created_at)):
            body = comment.body_html or comment.body_text
            if not body or not body.strip():
                continue
            author_id = mapper.map_user(comment.author)
            payload = CommentPayload(
                body_html=body,
                comment_type="internal",
                created_at=comment.created_at.isoformat() if comment.created_at else None,
                author_user_id=author_id,
                legacy_author_name=(
                    None
                    if author_id is not None
                    else (comment.author.name if comment.author else None)
                ),
                client_request_id=client_request_id(
                    plan.source.system, "comment", comment.source_id
                ),
                import_batch_id=plan.target.import_batch_id,
            )
            try:
                created = self._client.add_comment(target_id, payload)
                if not created.replayed:
                    result.comments_created += 1
            except ToolkitError as exc:
                result.errors.append(
                    RecordError(
                        source_record_id=task.source.record_id,
                        operation="add_comment",
                        message=redact(str(exc)),
                    )
                )

    def _apply_attachments(
        self,
        task: CanonicalTask,
        target_id: int,
        plan: MigrationPlan,
        result: ExecutionResult,
    ) -> None:
        assert self._client is not None
        for att in task.attachments:
            if att.is_external_link or not att.local_path:
                continue
            path = Path(att.local_path)
            if not path.is_file():
                result.warnings.append(
                    MigrationWarning(
                        code="attachment_missing",
                        severity=Severity.MEDIUM,
                        message=f"attachment file not found: {att.name}",
                        record_id=task.source.record_id,
                    )
                )
                continue
            try:
                created = self._client.upload_attachment(
                    target_id,
                    path,
                    file_name=att.name,
                    client_request_id=client_request_id(
                        plan.source.system, "attachment", att.source_id
                    ),
                    created_at=att.created_at.isoformat() if att.created_at else None,
                )
                if not created.replayed:
                    result.attachments_created += 1
            except ToolkitError as exc:
                # An attachment failure is reported but never corrupts the
                # state of its (already created) task.
                result.errors.append(
                    RecordError(
                        source_record_id=task.source.record_id,
                        operation="upload_attachment",
                        message=redact(str(exc)),
                    )
                )

    def _record_failure(
        self,
        task: CanonicalTask,
        plan: MigrationPlan,
        result: ExecutionResult,
        operation: str,
        exc: ToolkitError,
    ) -> None:
        result.failed += 1
        message = redact(str(exc))
        result.errors.append(
            RecordError(
                source_record_id=task.source.record_id, operation=operation, message=message
            )
        )
        self._state.mark(
            run_id=plan.run_id,
            record_type="task",
            source_record_id=task.source.record_id,
            status="failed",
            error=message[:500],
        )


def build_task_payload(
    task: CanonicalTask,
    plan: MigrationPlan,
    config: MigrationConfig,
    mapper: Mapper,
) -> TaskPayload:
    """Translate one canonical task into the ALL WR create-task payload."""
    section = plan.target.section_done if task.completed else plan.target.section_open
    watcher_ids = sorted(
        {uid for follower in task.followers if (uid := mapper.map_user(follower)) is not None}
    )
    checklist = [
        {
            "title": item.title[:500],
            "completed": item.completed,
            "assigned_user_id": mapper.map_user(item.assignee),
            "due_date": item.due_date,
            "created_at": item.created_at.isoformat() if item.created_at else None,
            "completed_at": item.completed_at.isoformat() if item.completed_at else None,
            "created_by_user_id": mapper.map_user(item.created_by),
        }
        for item in task.checklist
    ]
    return TaskPayload(
        project_id=plan.target.project_id,
        section_id=section,
        title=(task.title or "(untitled)").strip()[:500] or "(untitled)",
        description_html=task.description_html,
        assigned_user_id=mapper.map_user(task.assignee),
        created_by_user_id=mapper.map_user(task.created_by),
        start_date=task.start_date,
        due_date=task.due_date,
        created_at=task.created_at.isoformat() if task.created_at else None,
        updated_at=task.modified_at.isoformat() if task.modified_at else None,
        completed_at=task.completed_at.isoformat() if task.completed_at else None,
        import_source=plan.target.import_source,
        external_ref=task.source.external_ref if config.options.preserve_source_ids else None,
        import_batch_id=plan.target.import_batch_id,
        watchers=watcher_ids,
        subtasks=checklist,
    )
