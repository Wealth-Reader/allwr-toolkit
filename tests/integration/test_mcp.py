"""MCP server security: writes off by default, apply requires a valid plan."""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from allwr_toolkit.cli import main as cli_main
from allwr_toolkit.cli import workflows
from allwr_toolkit.cli.main import app
from allwr_toolkit.core.planning import load_plan, save_plan
from allwr_toolkit.mcp.server import build_server, writes_allowed

runner = CliRunner()

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


def _isolate_mcp_env(monkeypatch: pytest.MonkeyPatch, home: Path) -> None:
    for var in (
        "CLAUDE_CONFIG_DIR",
        "CODEX_HOME",
        "GEMINI_CLI_HOME",
        "OPENCODE_CONFIG",
        "OPENCODE_CONFIG_DIR",
        "COPILOT_HOME",
        "QWEN_HOME",
        "KIMI_CODE_HOME",
        "VSCODE_PORTABLE",
        "VSCODE_APPDATA",
        "GROK_HOME",
        "PI_CONFIG_DIR",
        "PI_CODING_AGENT_DIR",
        "HERMES_HOME",
        "QODER_CONFIG_DIR",
        "FACTORY_HOME_OVERRIDE",
        "DSH_HOME",
        "SAND_DATA_ROOT",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("APPDATA", str(home / "AppData" / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(home / "AppData" / "Local"))


def test_cli_mcp_setup_dry_run_confirmation_yes_and_doctor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate_mcp_env(monkeypatch, tmp_path)

    # No clients detected -> status="ready", exit 0
    empty_res = runner.invoke(app, ["--json", "mcp", "setup"])
    assert empty_res.exit_code == 0
    empty_payload = json.loads(empty_res.output)
    assert empty_payload["status"] == "ready"
    assert empty_payload["counts"]["total"] == 0

    # Create markers for cursor and codex
    (tmp_path / ".cursor").mkdir(parents=True)
    (tmp_path / ".codex").mkdir(parents=True)

    # 1. --dry-run emits status="planned" without creating files
    dry = runner.invoke(app, ["--json", "mcp", "setup", "--dry-run"])
    assert dry.exit_code == 0
    dry_payload = json.loads(dry.output)
    assert dry_payload["status"] == "planned"
    assert dry_payload["dry_run"] is True
    assert dry_payload["counts"]["planned_writes"] == 2
    assert not (tmp_path / ".cursor" / "mcp.json").exists()

    # 2. Without --yes in --json (or non-TTY) mode, emits status="needs_confirmation" and exits 2
    needs_conf = runner.invoke(app, ["--json", "mcp", "setup"])
    assert needs_conf.exit_code == 2
    conf_payload = json.loads(needs_conf.output)
    assert conf_payload["status"] == "needs_confirmation"
    assert not (tmp_path / ".cursor" / "mcp.json").exists()

    # 3. Interactive TTY decline and confirm
    monkeypatch.setattr(cli_main, "_is_interactive_tty", lambda: True)
    declined = runner.invoke(app, ["mcp", "setup"], input="n\n")
    assert declined.exit_code == 0
    assert "aborted" in declined.output
    assert not (tmp_path / ".cursor" / "mcp.json").exists()

    confirmed = runner.invoke(app, ["mcp", "setup"], input="y\n")
    assert confirmed.exit_code == 0
    assert (tmp_path / ".cursor" / "mcp.json").is_file()
    assert (tmp_path / ".codex" / "config.toml").is_file()
    monkeypatch.setattr(cli_main, "_is_interactive_tty", lambda: False)

    # 4. Re-running with --yes when already configured emits status="ready"
    ready_res = runner.invoke(app, ["--json", "mcp", "setup", "--yes"])
    assert ready_res.exit_code == 0
    ready_payload = json.loads(ready_res.output)
    assert ready_payload["status"] == "ready"
    assert all(c["status"] == "unchanged" for c in ready_payload["clients"])

    # 5. mcp doctor reports configured clients
    doc = runner.invoke(app, ["--json", "mcp", "doctor"])
    assert doc.exit_code == 0
    doc_payload = json.loads(doc.output)
    assert doc_payload["ok"] is True
    assert doc_payload["counts"]["configured"] == 2

    doc_human = runner.invoke(app, ["mcp", "doctor"])
    assert doc_human.exit_code == 0
    assert "[configured]" in doc_human.output


def test_cli_mcp_setup_explicit_client_and_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate_mcp_env(monkeypatch, tmp_path)

    # Explicit --client configures client even when marker directory does not exist yet
    res = runner.invoke(app, ["--json", "mcp", "setup", "--client", "windsurf", "--yes"])
    assert res.exit_code == 0
    payload = json.loads(res.output)
    assert payload["status"] == "applied"
    assert (tmp_path / ".codeium" / "windsurf" / "mcp_config.json").is_file()

    # Unknown client exits 2
    bad = runner.invoke(app, ["mcp", "setup", "--client", "unknown_agent", "--yes"])
    assert bad.exit_code == 2

    # Foreign conflict exits 2 in both setup and doctor
    cursor_cfg = tmp_path / ".cursor" / "mcp.json"
    cursor_cfg.parent.mkdir(parents=True)
    cursor_cfg.write_text(
        '{"mcpServers": {"allwr-toolkit": {"command": "/bin/foreign", "args": []}}}\n',
        encoding="utf-8",
    )
    conflict_setup = runner.invoke(app, ["mcp", "setup", "--client", "cursor", "--yes"])
    assert conflict_setup.exit_code == 2
    conflict_doc = runner.invoke(app, ["mcp", "doctor", "--client", "cursor"])
    assert conflict_doc.exit_code == 2
