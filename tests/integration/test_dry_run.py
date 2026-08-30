"""Dry-run safety: the default mode performs zero target writes."""

from pathlib import Path

import pytest
import respx

from allwr_toolkit.cli import workflows


def test_dry_run_performs_zero_http_requests(
    config_file: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No API key in the environment: a dry run must not even need one.
    monkeypatch.delenv("ALLWR_TOOLKIT_ALLWR_API_KEY", raising=False)
    plan_path = tmp_path / "plan.json"
    workflows.generate_plan(config_file, plan_path)
    with respx.mock(assert_all_called=False) as router:
        catch_all = router.route(host="allwr.example.com").respond(500)
        result = workflows.run_migration(
            config_file,
            plan_path,
            state_path=tmp_path / "state.db",
            dry_run=True,
            report_dir=tmp_path / "reports",
        )
        assert catch_all.call_count == 0
    assert result.dry_run is True
    assert result.created == 3  # two selected units + one rich subtask
    assert result.failed == 0
    # The report bundle is still produced.
    assert (tmp_path / "reports" / "migration-report.json").is_file()
    assert (tmp_path / "reports" / "migration-report.html").is_file()


def test_dry_run_is_the_default(config_file: Path, tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    workflows.generate_plan(config_file, plan_path)
    result = workflows.run_migration(config_file, plan_path, state_path=tmp_path / "state.db")
    assert result.dry_run is True
