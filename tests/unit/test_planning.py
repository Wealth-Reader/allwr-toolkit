"""Plan building, hashing and verification."""

from pathlib import Path

import pytest

from allwr_toolkit.configuration import load_config
from allwr_toolkit.core.errors import PlanValidationError
from allwr_toolkit.core.models import Severity, UnsupportedField
from allwr_toolkit.core.planning import (
    blocking_warnings,
    build_plan,
    client_request_id,
    compute_plan_hash,
    load_plan,
    save_plan,
    verify_plan,
)
from tests.conftest import write_config
from tests.unit.test_convert_asana import convert


def build(config_path: Path):  # type: ignore[no-untyped-def]
    config = load_config(config_path)
    records = [convert("1200000000000001"), convert("1200000000000004")]
    return (
        build_plan(records, config, connector_version="0.1.0", source_scope="export:test"),
        config,
    )


def test_plan_counts_and_operations(config_file: Path) -> None:
    plan, _ = build(config_file)
    assert plan.counts["selected"] == 2
    ops = [o.op for o in plan.operations]
    # parent + rich subtask + duplicate-title task = 3 creates + 1 relationship
    assert ops.count("create_task") == 3
    assert ops.count("create_relationship") == 1
    assert ops.count("add_comment") == 2
    assert ops.count("upload_attachment") == 1  # external one is linked, not uploaded


def test_distinct_gids_with_same_title_both_planned(config_file: Path) -> None:
    plan, _ = build(config_file)
    assert "1200000000000001" in plan.selected_ids
    assert "1200000000000004" in plan.selected_ids
    assert ["1200000000000001", "1200000000000004"] in plan.duplicate_suspects
    # reported as suspects, never merged
    assert plan.counts["selected"] == 2


def test_plan_roundtrip_and_verify(config_file: Path, tmp_path: Path) -> None:
    plan, config = build(config_file)
    path = tmp_path / "plan.json"
    save_plan(plan, path)
    loaded = load_plan(path)
    verify_plan(loaded, config)  # must not raise
    assert loaded.plan_hash == compute_plan_hash(loaded)


def test_tampered_plan_hash_rejected(config_file: Path, tmp_path: Path) -> None:
    plan, config = build(config_file)
    plan.counts["selected"] = 999  # tamper after hashing
    with pytest.raises(PlanValidationError, match="hash"):
        verify_plan(plan, config)


def test_target_mismatch_rejected(config_file: Path, tmp_path: Path, manifest_file: Path) -> None:
    plan, _ = build(config_file)
    other = load_config(
        write_config(tmp_path, manifest=manifest_file, base_url="https://other.example.com")
    )
    with pytest.raises(PlanValidationError, match="targets"):
        verify_plan(plan, other)


def test_project_mismatch_rejected(config_file: Path, tmp_path: Path, manifest_file: Path) -> None:
    plan, _ = build(config_file)
    other = load_config(write_config(tmp_path, manifest=manifest_file, project_id=999))
    with pytest.raises(PlanValidationError, match="project"):
        verify_plan(plan, other)


def test_config_change_rejected(config_file: Path, tmp_path: Path, manifest_file: Path) -> None:
    plan, _ = build(config_file)
    changed = load_config(write_config(tmp_path, manifest=manifest_file, on_unknown_user="skip"))
    with pytest.raises(PlanValidationError, match="configuration changed"):
        verify_plan(plan, changed)


def test_stop_on_data_loss_escalates_unsupported_to_blocking(
    tmp_path: Path, manifest_file: Path
) -> None:
    config = load_config(write_config(tmp_path, manifest=manifest_file, stop_on_data_loss=True))
    records = [convert("1200000000000001")]
    plan = build_plan(
        records,
        config,
        connector_version="0.1.0",
        source_scope="export:test",
        unsupported_fields=[
            UnsupportedField(record_id="1200000000000001", field="dependencies", reason="x")
        ],
    )
    blocked = blocking_warnings(plan, [])
    assert blocked and blocked[0].code == "unsupported_field"
    assert blocking_warnings(plan, ["unsupported_field"]) == []


def test_unknown_users_produce_warnings(tmp_path: Path, manifest_file: Path) -> None:
    config = load_config(write_config(tmp_path, manifest=manifest_file, users=[]))
    plan = build_plan(
        [convert("1200000000000001")],
        config,
        connector_version="0.1.0",
        source_scope="export:test",
    )
    assert any(w.code == "unknown_user" for w in plan.warnings)
    assert all(w.severity is not Severity.HIGH for w in plan.warnings if w.code == "unknown_user")


def test_client_request_id_is_deterministic_and_bounded() -> None:
    a = client_request_id("asana", "comment", "1200000000000501")
    b = client_request_id("asana", "comment", "1200000000000501")
    assert a == b
    assert len(client_request_id("asana", "attachment", "9" * 200)) <= 64
