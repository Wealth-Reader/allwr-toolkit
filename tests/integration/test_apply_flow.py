"""Apply flow against a fully mocked ALL WR API: idempotency, failures, reports."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from allwr_toolkit.api.allwr import AllwrClient
from allwr_toolkit.cli import workflows
from allwr_toolkit.core.errors import PlanValidationError
from allwr_toolkit.core.planning import load_plan, save_plan
from allwr_toolkit.core.state import StateStore
from tests.conftest import TARGET_BASE_URL


@pytest.fixture(autouse=True)
def fast_client(monkeypatch: pytest.MonkeyPatch, allwr_key: str) -> None:
    monkeypatch.setattr(AllwrClient, "_sleep", lambda self, s: None)


class FakeAllwr:
    """Mounts respx routes that emulate the import-mode API with idempotency."""

    def __init__(self) -> None:
        self.tasks: dict[str, int] = {}  # external_ref -> id
        self.comments: set[str] = set()
        self.attachments: set[str] = set()
        self.relationships: list[tuple[int, int]] = []
        self.next_id = 900
        self.fail_attachments = False

    def install(self) -> None:
        respx.post(f"{TARGET_BASE_URL}/tasks").mock(side_effect=self._create_task)
        respx.route(method="POST", url__regex=rf"{TARGET_BASE_URL}/tasks/\d+/comments").mock(
            side_effect=self._add_comment
        )
        respx.post(f"{TARGET_BASE_URL}/attachments/upload").mock(side_effect=self._upload)
        respx.route(method="POST", url__regex=rf"{TARGET_BASE_URL}/tasks/\d+/relationships").mock(
            side_effect=self._relationship
        )

    def _create_task(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        ref = body.get("external_ref") or body["title"]
        if ref in self.tasks:
            return httpx.Response(
                200, json={"ok": True, "replayed": True, "task": {"id": self.tasks[ref]}}
            )
        self.next_id += 1
        self.tasks[ref] = self.next_id
        return httpx.Response(201, json={"ok": True, "task": {"id": self.next_id}})

    def _add_comment(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        key = body["client_request_id"]
        replayed = key in self.comments
        self.comments.add(key)
        return httpx.Response(
            200 if replayed else 201,
            json={"ok": True, "replayed": replayed, "comment": {"id": 1}},
        )

    def _upload(self, request: httpx.Request) -> httpx.Response:
        if self.fail_attachments:
            return httpx.Response(422, json={"ok": False, "error": "upload_rejected"})
        content = request.content.decode(errors="replace")
        marker = "client_request_id"
        key = content[content.find(marker) : content.find(marker) + 80]
        replayed = key in self.attachments
        self.attachments.add(key)
        return httpx.Response(201, json={"ok": True, "replayed": replayed})

    def _relationship(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        task_id = int(str(request.url.path).split("/")[-2])
        self.relationships.append((task_id, body["target_task_id"]))
        assert body["relation_type"] == "subtask_of"
        return httpx.Response(201, json={"ok": True})


def prepare(config_file: Path, tmp_path: Path) -> tuple[Path, Path]:
    plan_path = tmp_path / "plan.json"
    workflows.generate_plan(config_file, plan_path)
    return plan_path, tmp_path / "state.db"


@respx.mock
def test_apply_creates_everything_and_rerun_does_not_duplicate(
    config_file: Path, tmp_path: Path
) -> None:
    fake = FakeAllwr()
    fake.install()
    plan_path, state_path = prepare(config_file, tmp_path)

    result = workflows.run_migration(
        config_file,
        plan_path,
        state_path=state_path,
        dry_run=False,
        report_dir=tmp_path / "reports",
    )
    assert result.failed == 0
    assert result.created == 3  # parent, rich subtask, duplicate-title task
    assert result.comments_created == 2
    assert result.attachments_created == 1
    assert result.relationships_created == 1
    # Distinct GIDs with the same title -> two distinct tasks in the target.
    assert "1200000000000001" in fake.tasks
    assert "1200000000000004" in fake.tasks
    tasks_after_first = dict(fake.tasks)

    # Re-run: local state skips everything; nothing new is created remotely.
    rerun = workflows.run_migration(config_file, plan_path, state_path=state_path, dry_run=False)
    assert rerun.created == 0
    assert rerun.skipped == 3
    assert fake.tasks == tasks_after_first

    # Fresh state, same server: server-side idempotency answers "replayed".
    rerun2 = workflows.run_migration(
        config_file, plan_path, state_path=tmp_path / "state2.db", dry_run=False
    )
    assert rerun2.created == 0
    assert rerun2.replayed == 3
    assert fake.tasks == tasks_after_first


@respx.mock
def test_apply_without_valid_plan_rejected(config_file: Path, tmp_path: Path) -> None:
    FakeAllwr().install()
    plan_path, state_path = prepare(config_file, tmp_path)
    plan = load_plan(plan_path)
    plan.counts["selected"] = 999  # tamper
    save_plan(plan, plan_path)
    with pytest.raises(PlanValidationError, match="hash"):
        workflows.run_migration(config_file, plan_path, state_path=state_path, dry_run=False)
    assert not respx.calls, "a rejected plan must produce zero target requests"


@respx.mock
def test_attachment_failure_does_not_corrupt_state(config_file: Path, tmp_path: Path) -> None:
    fake = FakeAllwr()
    fake.fail_attachments = True
    fake.install()
    plan_path, state_path = prepare(config_file, tmp_path)
    result = workflows.run_migration(config_file, plan_path, state_path=state_path, dry_run=False)
    # The task itself was created and recorded; the attachment error reported.
    assert result.created == 3
    assert any(e.operation == "upload_attachment" for e in result.errors)
    with StateStore(state_path) as state:
        assert state.is_created(result.run_id, "task", "1200000000000001")
    # A later re-run stays idempotent.
    rerun = workflows.run_migration(config_file, plan_path, state_path=state_path, dry_run=False)
    assert rerun.skipped == 3


@respx.mock
def test_reports_and_cleanup_manifest(config_file: Path, tmp_path: Path) -> None:
    fake = FakeAllwr()
    fake.install()
    plan_path, state_path = prepare(config_file, tmp_path)
    result = workflows.run_migration(
        config_file,
        plan_path,
        state_path=state_path,
        dry_run=False,
        report_dir=tmp_path / "reports",
    )
    report: dict[str, Any] = json.loads(
        (tmp_path / "reports" / "migration-report.json").read_text(encoding="utf-8")
    )
    assert report["run_id"] == result.run_id
    assert report["counts"]["created"] == 3
    assert report["id_map"]["1200000000000001"]
    # Reports never include record bodies.
    assert "hero section" not in json.dumps(report)

    manifest = workflows.cleanup_manifest(result.run_id, state_path=state_path)
    refs = {r["source_record_id"] for r in manifest["records"]}
    assert refs == {"1200000000000001", "1200000000000002", "1200000000000004"}

    cleanup: dict[str, Any] = json.loads(
        (tmp_path / "reports" / "migration-cleanup.json").read_text(encoding="utf-8")
    )
    assert cleanup["run_id"] == result.run_id
