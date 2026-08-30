"""CLI smoke and behavior tests (no network)."""

import json
from pathlib import Path

from typer.testing import CliRunner

import allwr_toolkit
from allwr_toolkit.cli.main import app

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert allwr_toolkit.__version__ in result.output


def test_json_flag() -> None:
    result = runner.invoke(app, ["--json", "version"])
    assert json.loads(result.output)["version"] == allwr_toolkit.__version__


def test_connectors_list_and_describe() -> None:
    result = runner.invoke(app, ["connectors", "list"])
    assert result.exit_code == 0
    assert "asana" in result.output and "freshdesk" in result.output

    described = runner.invoke(app, ["connectors", "describe", "asana"])
    assert described.exit_code == 0
    assert "Asana Importer" in described.output


def test_connectors_describe_unknown_exits_2() -> None:
    result = runner.invoke(app, ["connectors", "describe", "nope"])
    assert result.exit_code == 2


def test_doctor_with_valid_config(config_file: Path) -> None:
    result = runner.invoke(app, ["doctor", "--config", str(config_file)])
    assert result.exit_code == 0
    assert "valid" in result.output


def test_doctor_with_broken_config(tmp_path: Path) -> None:
    path = tmp_path / "broken.yaml"
    path.write_text("connector: asana\n", encoding="utf-8")
    result = runner.invoke(app, ["doctor", "--config", str(path)])
    assert result.exit_code == 2


def test_migrate_inspect(config_file: Path) -> None:
    result = runner.invoke(app, ["migrate", "asana", "inspect", "--config", str(config_file)])
    assert result.exit_code == 0
    assert "selected_tasks: 2" in result.output


def test_migrate_inspect_wrong_connector(config_file: Path) -> None:
    result = runner.invoke(app, ["migrate", "freshdesk", "inspect", "--config", str(config_file)])
    assert result.exit_code == 2


def test_migrate_plan_and_dry_run_apply(config_file: Path, tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    planned = runner.invoke(
        app,
        ["migrate", "asana", "plan", "--config", str(config_file), "--out", str(plan_path)],
    )
    assert planned.exit_code == 0
    assert plan_path.is_file()
    assert "target: https://allwr.example.com" in planned.output

    applied = runner.invoke(
        app,
        [
            "migrate",
            "asana",
            "apply",
            "--config",
            str(config_file),
            "--plan",
            str(plan_path),
            "--state",
            str(tmp_path / "state.db"),
            "--report-dir",
            str(tmp_path / "reports"),
        ],
    )
    assert applied.exit_code == 0
    assert "(dry-run)" in applied.output


def test_apply_refuses_without_confirmation(config_file: Path, tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    runner.invoke(
        app,
        ["migrate", "asana", "plan", "--config", str(config_file), "--out", str(plan_path)],
    )
    # --no-dry-run without --yes prompts; answering "n" aborts with exit 0.
    result = runner.invoke(
        app,
        [
            "migrate",
            "asana",
            "apply",
            "--config",
            str(config_file),
            "--plan",
            str(plan_path),
            "--no-dry-run",
            "--state",
            str(tmp_path / "state.db"),
        ],
        input="n\n",
    )
    assert result.exit_code == 0
    assert "aborted" in result.output
    assert "About to WRITE" in result.output


def test_migration_status_unknown_run(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["migration", "status", "missing-run", "--state", str(tmp_path / "state.db")],
    )
    assert result.exit_code == 1
    assert "not found" in result.output
