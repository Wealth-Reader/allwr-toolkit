"""Configuration loading and validation."""

from pathlib import Path

import pytest

from allwr_toolkit.configuration import config_hash, load_config
from allwr_toolkit.core.errors import ConfigurationError


def test_loads_yaml(config_file: Path) -> None:
    config = load_config(config_file)
    assert config.connector == "asana"
    assert config.target.project_id == 42
    assert config.import_source == "asana"


def test_loads_toml(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        """
connector = "freshdesk"

[source]
domain = "example"

[target]
base_url = "https://allwr.example.com/api/v1"
project_id = 7
""",
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.connector == "freshdesk"
    assert config.source["domain"] == "example"


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="not found"):
        load_config(tmp_path / "missing.yaml")


def test_unknown_extension_raises(tmp_path: Path) -> None:
    path = tmp_path / "config.ini"
    path.write_text("x", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="unsupported"):
        load_config(path)


def test_precise_validation_errors(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("connector: asana\ntarget:\n  project_id: nope\n", encoding="utf-8")
    with pytest.raises(ConfigurationError) as excinfo:
        load_config(path)
    assert "target.base_url" in str(excinfo.value)
    assert "target.project_id" in str(excinfo.value)


def test_http_base_url_rejected(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "connector: asana\ntarget:\n  base_url: http://insecure.example.com\n  project_id: 1\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError, match="https"):
        load_config(path)


def test_extra_keys_rejected(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "connector: asana\nsurprise: true\ntarget:\n"
        "  base_url: https://allwr.example.com\n  project_id: 1\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError):
        load_config(path)


def test_config_hash_stable_and_sensitive(config_file: Path, tmp_path: Path) -> None:
    from tests.conftest import write_config

    config = load_config(config_file)
    assert config_hash(config) == config_hash(load_config(config_file))
    other = load_config(
        write_config(tmp_path, manifest=Path(config.source["selection_manifest"]), project_id=43)
    )
    assert config_hash(config) != config_hash(other)
