"""Shared test fixtures: synthetic Asana export, configs and API keys."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from allwr_toolkit.configuration import MigrationConfig, load_config

FIXTURES = Path(__file__).parent / "fixtures"
ASANA_EXPORT = FIXTURES / "asana_export"

TARGET_BASE_URL = "https://allwr.example.com/api/v1"

MANIFEST_CONTENT = (
    "# id\tproject\tstate\tassignee\tdue\tcreated\tsub/com/att\ttitle\n"
    "# Delete (or comment out with #) the lines you do not want migrated.\n"
    "\n"
    "## Website Redesign\n"
    "1200000000000001\tWebsite Redesign\tOPEN\tAlex Doe\t2024-05-01\t2024-03-01"
    "\t2/2/2\tRedesign the landing page\n"
    "1200000000000004\tWebsite Redesign\tOPEN\tSam Poe\t-\t2024-04-01"
    "\t0/0/0\tRedesign the landing page\n"
    "#1200000000000005\tWebsite Redesign\tOPEN\t-\t-\t2024-04-02"
    "\t0/0/0\tExcluded on purpose\n"
)


@pytest.fixture()
def manifest_file(tmp_path: Path) -> Path:
    path = tmp_path / "selection.txt"
    path.write_text(MANIFEST_CONTENT, encoding="utf-8")
    return path


def write_config(
    tmp_path: Path,
    *,
    manifest: Path,
    base_url: str = TARGET_BASE_URL,
    project_id: int = 42,
    on_unknown_user: str = "null",
    users: list[dict[str, object]] | None = None,
    stop_on_data_loss: bool = False,
    accepted_warnings: list[str] | None = None,
    include_attachments: bool = True,
) -> Path:
    """Write a valid asana offline-mode migration config and return its path."""
    payload = {
        "connector": "asana",
        "source": {
            "mode": "offline",
            "data_dir": str(ASANA_EXPORT),
            "selection_manifest": str(manifest),
        },
        "target": {
            "base_url": base_url,
            "project_id": project_id,
            "section_open": 100,
            "section_done": 101,
            "import_batch_id": 7,
            "environment": "sandbox",
        },
        "mapping": {
            "users": users
            if users is not None
            else [
                {"source_id": "1200000000000101", "target_user_id": 11},
                {"source_id": "1200000000000102", "target_user_id": 12},
            ],
            "on_unknown_user": on_unknown_user,
        },
        "options": {
            "stop_on_data_loss": stop_on_data_loss,
            "accepted_warnings": accepted_warnings or [],
            "include_attachments": include_attachments,
        },
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


@pytest.fixture()
def config_file(tmp_path: Path, manifest_file: Path) -> Path:
    return write_config(tmp_path, manifest=manifest_file)


@pytest.fixture()
def config(config_file: Path) -> MigrationConfig:
    return load_config(config_file)


@pytest.fixture()
def allwr_key(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("ALLWR_TOOLKIT_ALLWR_API_KEY", "wrk_synthetic_test_key")
    return "wrk_synthetic_test_key"
