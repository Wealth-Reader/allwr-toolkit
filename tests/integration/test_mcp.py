"""MCP server security: writes off by default, apply requires a valid plan."""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from allwr_toolkit.cli import workflows
from allwr_toolkit.core.planning import load_plan, save_plan
from allwr_toolkit.mcp.server import build_server, writes_allowed

WRITE_TOOLS = {"apply_plan", "resume_migration", "cancel_migration"}


def tool_names(server: Any) -> set[str]:
    return {t.name for t in asyncio.run(server.list_tools())}


def call(server: Any, name: str, args: dict[str, Any]) -> dict[str, Any]:
    result = asyncio.run(server.call_tool(name, args))
    if isinstance(result, tuple):  # newer SDKs return (content, structured)
        result = result[0]
    text = result[0].text
    return json.loads(text)


def test_writes_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALLWR_MCP_ALLOW_WRITES", raising=False)
    server = build_server()
    names = tool_names(server)
    assert WRITE_TOOLS.isdisjoint(names)
    assert {"list_connectors", "generate_plan", "inspect_plan"} <= names


def test_env_gate_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    for value in ("", "false", "1", "yes", "TRUE-ish"):
        monkeypatch.setenv("ALLWR_MCP_ALLOW_WRITES", value)
        assert writes_allowed() is False, value
    monkeypatch.setenv("ALLWR_MCP_ALLOW_WRITES", "true")
    assert writes_allowed() is True
    monkeypatch.setenv("ALLWR_MCP_ALLOW_WRITES", " True ")
    assert writes_allowed() is True


def test_writes_enabled_registers_marked_tools() -> None:
    server = build_server(allow_writes=True)
    names = tool_names(server)
    assert WRITE_TOOLS <= names


def test_read_tools_work(config_file: Path, tmp_path: Path) -> None:
    server = build_server(allow_writes=False)
    listing = call(server, "list_connectors", {})
    assert listing["ok"] and "asana" in listing["connectors"]

    described = call(server, "describe_connector", {"connector_id": "asana"})
    assert described["metadata"]["connector_id"] == "asana"

    validated = call(server, "validate_config", {"config_path": str(config_file)})
    assert validated["ok"] is True

    plan_path = tmp_path / "plan.json"
    planned = call(
        server,
        "generate_plan",
        {"config_path": str(config_file), "plan_path": str(plan_path)},
    )
    assert planned["ok"] and plan_path.is_file()

    inspected = call(server, "inspect_plan", {"plan_path": str(plan_path)})
    assert inspected["counts"]["selected"] == 2


def test_mcp_apply_requires_valid_plan(config_file: Path, tmp_path: Path, allwr_key: str) -> None:
    server = build_server(allow_writes=True)
    plan_path = tmp_path / "plan.json"
    workflows.generate_plan(config_file, plan_path)
    plan = load_plan(plan_path)
    plan.counts["selected"] = 999  # tamper -> hash mismatch
    save_plan(plan, plan_path)
    result = call(
        server,
        "apply_plan",
        {
            "config_path": str(config_file),
            "plan_path": str(plan_path),
            "state_path": str(tmp_path / "state.db"),
        },
    )
    assert result["ok"] is False
    assert result["error"] == "plan_validation_error"


def test_mcp_apply_missing_plan_rejected(config_file: Path, tmp_path: Path, allwr_key: str) -> None:
    server = build_server(allow_writes=True)
    result = call(
        server,
        "apply_plan",
        {
            "config_path": str(config_file),
            "plan_path": str(tmp_path / "does-not-exist.json"),
            "state_path": str(tmp_path / "state.db"),
        },
    )
    assert result["ok"] is False
    assert result["error"] == "plan_validation_error"
