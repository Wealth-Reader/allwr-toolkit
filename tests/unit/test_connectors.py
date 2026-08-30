"""Connector SDK, registry and connector-level behavior."""

from pathlib import Path

import httpx
import pytest
import respx

from allwr_toolkit.connectors.asana.connector import AsanaConnector
from allwr_toolkit.connectors.base import available_connectors, get_connector
from allwr_toolkit.connectors.freshdesk.client import FreshdeskClient
from allwr_toolkit.connectors.freshdesk.connector import FreshdeskConnector
from allwr_toolkit.core.errors import ConfigurationError
from tests.conftest import ASANA_EXPORT


def test_registry_finds_builtins() -> None:
    connectors = available_connectors()
    assert connectors["asana"] is AsanaConnector
    assert connectors["freshdesk"] is FreshdeskConnector
    with pytest.raises(ConfigurationError, match="unknown connector"):
        get_connector("does-not-exist")


def test_metadata_and_capabilities_are_complete() -> None:
    for cls in (AsanaConnector, FreshdeskConnector):
        meta = cls.metadata()
        assert meta.connector_id and meta.display_name and meta.stability
        assert meta.known_limitations, "limitations must be declared, not hidden"
        caps = cls.capabilities()
        assert caps.record_types


def test_asana_validate_configuration_messages(tmp_path: Path) -> None:
    problems = AsanaConnector({}).validate_configuration()
    assert any("selection_manifest" in p for p in problems)
    assert any("data_dir" in p for p in problems)

    problems = AsanaConnector(
        {"mode": "weird", "selection_manifest": str(tmp_path / "missing.txt")}
    ).validate_configuration()
    assert any("mode" in p for p in problems)
    assert any("not found" in p for p in problems)

    manifest = tmp_path / "m.txt"
    manifest.write_text("1200000000000001\n", encoding="utf-8")
    problems = AsanaConnector(
        {
            "mode": "offline",
            "selection_manifest": str(manifest),
            "data_dir": str(tmp_path),
        }
    ).validate_configuration()
    assert any("does not look like an Asana export" in p for p in problems)


def make_asana(manifest: Path) -> AsanaConnector:
    return AsanaConnector(
        {
            "mode": "offline",
            "data_dir": str(ASANA_EXPORT),
            "selection_manifest": str(manifest),
        }
    )


def test_asana_inspect_reports_missing_and_duplicates(tmp_path: Path) -> None:
    manifest = tmp_path / "m.txt"
    manifest.write_text(
        "1200000000000001\tok\n"
        "1200000000000001\tduplicate\n"
        "1200000000009999\tmissing from export\n"
        "12x\tinvalid-ish\n",
        encoding="utf-8",
    )
    connector = make_asana(manifest)
    summary = connector.inspect()
    assert summary.record_counts["selected_tasks"] == 2
    assert summary.record_counts["missing_export_data"] == 1
    codes = {w.code for w in summary.warnings}
    assert {"duplicate_manifest_gid", "invalid_manifest_line", "missing_export_data"} <= codes


def test_asana_iter_records_flags_unavailable(tmp_path: Path) -> None:
    manifest = tmp_path / "m.txt"
    manifest.write_text("1200000000000001\tok\n1200000000009999\tmissing\n", encoding="utf-8")
    connector = make_asana(manifest)
    records = list(connector.iter_records())
    assert [r.source.record_id for r in records] == ["1200000000000001"]
    assert any(w.code == "record_unavailable" for w in connector.warnings)


def test_asana_health_check_and_scope(tmp_path: Path) -> None:
    manifest = tmp_path / "m.txt"
    manifest.write_text("1200000000000001\n", encoding="utf-8")
    connector = make_asana(manifest)
    assert connector.health_check() is True
    assert connector.scope.startswith("export:")
    assert AsanaConnector({"workspace_gid": "1200000000000777"}).scope == (
        "workspace:1200000000000777"
    )
    assert AsanaConnector({}).scope == "unknown"


def test_asana_iter_records_requires_valid_config() -> None:
    with pytest.raises(ConfigurationError):
        list(AsanaConnector({}).iter_records())
    with pytest.raises(ConfigurationError):
        AsanaConnector({}).inspect()


def test_default_get_attachment_only_serves_local_files(tmp_path: Path) -> None:
    from allwr_toolkit.core.models import CanonicalAttachment

    manifest = tmp_path / "m.txt"
    manifest.write_text("1200000000000001\n", encoding="utf-8")
    connector = make_asana(manifest)
    local = ASANA_EXPORT / "attachments/1200000000000001/1200000000000601_wireframe.txt"
    found = connector.get_attachment(
        CanonicalAttachment(source_id="a", name="w.txt", local_path=str(local)), tmp_path
    )
    assert found == local
    missing = connector.get_attachment(
        CanonicalAttachment(source_id="b", name="gone.txt", local_path="/nope"), tmp_path
    )
    assert missing is None


@respx.mock
def test_freshdesk_include_closed_false_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLWR_TOOLKIT_FRESHDESK_API_KEY", "synthetic_key")
    monkeypatch.setattr(FreshdeskClient, "_sleep", lambda self, s: None)
    base = "https://example.freshdesk.com/api/v2"
    respx.get(f"{base}/tickets").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": 1, "subject": "Open one", "status": 2, "created_at": None},
                {"id": 2, "subject": "Closed one", "status": 5, "created_at": None},
            ],
        )
    )
    respx.get(f"{base}/tickets/1/conversations").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{base}/contacts").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{base}/agents").mock(return_value=httpx.Response(200, json=[]))
    connector = FreshdeskConnector({"domain": "example", "include_closed": False})
    records = list(connector.iter_records())
    assert [r.source.record_id for r in records] == ["1"]
    assert records[0].completed is False


@respx.mock
def test_freshdesk_get_record_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLWR_TOOLKIT_FRESHDESK_API_KEY", "synthetic_key")
    monkeypatch.setattr(FreshdeskClient, "_sleep", lambda self, s: None)
    respx.get("https://example.freshdesk.com/api/v2/tickets/99").mock(
        return_value=httpx.Response(404, json={})
    )
    connector = FreshdeskConnector({"domain": "example"})
    assert connector.get_record("99") is None


@respx.mock
def test_freshdesk_health_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLWR_TOOLKIT_FRESHDESK_API_KEY", "synthetic_key")
    monkeypatch.setattr(FreshdeskClient, "_sleep", lambda self, s: None)
    route = respx.get("https://example.freshdesk.com/api/v2/agents/me")
    route.mock(return_value=httpx.Response(200, json={"id": 1}))
    assert FreshdeskConnector({"domain": "example"}).health_check() is True
    route.mock(return_value=httpx.Response(403, json={}))
    assert FreshdeskConnector({"domain": "example"}).health_check() is False
    assert FreshdeskConnector({}).health_check() is False


@respx.mock
def test_freshdesk_deleted_agent_tolerated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLWR_TOOLKIT_FRESHDESK_API_KEY", "synthetic_key")
    monkeypatch.setattr(FreshdeskClient, "_sleep", lambda self, s: None)
    base = "https://example.freshdesk.com/api/v2"
    respx.get(f"{base}/agents").mock(return_value=httpx.Response(200, json=[]))
    connector = FreshdeskConnector({"domain": "example"})
    user = connector._agent(12345)
    assert user is not None and user.source_id == "12345" and user.name is None
