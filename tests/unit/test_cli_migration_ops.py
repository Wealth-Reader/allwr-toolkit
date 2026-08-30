"""CLI migration operation commands against a real (dry-run) state."""

import json
from pathlib import Path

from typer.testing import CliRunner

from allwr_toolkit.cli import workflows
from allwr_toolkit.cli.main import app

runner = CliRunner()


def make_run(config_file: Path, tmp_path: Path) -> tuple[str, Path, Path]:
    plan_path = tmp_path / "plan.json"
    plan = workflows.generate_plan(config_file, plan_path)
    state_path = tmp_path / "state.db"
    workflows.run_migration(config_file, plan_path, state_path=state_path, dry_run=True)
    return plan.run_id, plan_path, state_path


def test_status_cancel_report_cleanup(config_file: Path, tmp_path: Path) -> None:
    run_id, plan_path, state_path = make_run(config_file, tmp_path)

    status = runner.invoke(
        app, ["--json", "migration", "status", run_id, "--state", str(state_path)]
    )
    assert status.exit_code == 0
    assert json.loads(status.output)["run"]["run_id"] == run_id

    cancelled = runner.invoke(app, ["migration", "cancel", run_id, "--state", str(state_path)])
    assert cancelled.exit_code == 0
    assert "resumable" in cancelled.output

    report = runner.invoke(
        app,
        [
            "migration",
            "report",
            run_id,
            "--plan",
            str(plan_path),
            "--state",
            str(state_path),
            "--out-dir",
            str(tmp_path / "out"),
        ],
    )
    assert report.exit_code == 0
    assert (tmp_path / "out" / "migration-report.json").is_file()

    cleanup = runner.invoke(
        app,
        ["--json", "migration", "cleanup-plan", run_id, "--state", str(state_path)],
    )
    assert cleanup.exit_code == 0
    payload = json.loads(cleanup.output)
    assert payload["run_id"] == run_id
    assert payload["records"] == []  # dry-run created nothing


def test_report_with_wrong_plan_fails(config_file: Path, tmp_path: Path) -> None:
    run_id, _plan_path, state_path = make_run(config_file, tmp_path)
    other_plan = tmp_path / "other-plan.json"
    workflows.generate_plan(config_file, other_plan)  # different run id
    result = runner.invoke(
        app,
        [
            "migration",
            "report",
            run_id,
            "--plan",
            str(other_plan),
            "--state",
            str(state_path),
        ],
    )
    assert result.exit_code == 2
    assert "belongs to run" in result.output


def test_apply_blocked_by_high_warnings_exit_code(tmp_path: Path, manifest_file: Path) -> None:
    from tests.conftest import write_config

    # missing export data -> high severity warning -> blocked apply
    bad_manifest = tmp_path / "bad.txt"
    bad_manifest.write_text("1200000000000001\tok\n1200000000009999\tmissing\n", encoding="utf-8")
    config_path = write_config(tmp_path, manifest=bad_manifest)
    plan_path = tmp_path / "plan.json"
    planned = runner.invoke(
        app,
        ["migrate", "asana", "plan", "--config", str(config_path), "--out", str(plan_path)],
    )
    assert planned.exit_code == 0
    applied = runner.invoke(
        app,
        [
            "migrate",
            "asana",
            "apply",
            "--config",
            str(config_path),
            "--plan",
            str(plan_path),
            "--state",
            str(tmp_path / "state.db"),
        ],
    )
    assert applied.exit_code == 3
    assert "blocked_by_warnings" in applied.output
