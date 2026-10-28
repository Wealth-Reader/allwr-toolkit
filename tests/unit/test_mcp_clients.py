"""Unit tests for multi-agent MCP client detection, setup, backups, and doctor."""

from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path

import pytest
import yaml

from allwr_toolkit.core.errors import ConfigurationError
from allwr_toolkit.mcp.clients import (
    CLIENT_SPECS,
    DSH_PLUGIN_ID,
    DSH_PLUGIN_NAME,
    SERVER_KEY,
    apply_client_setup,
    available_client_ids,
    inspect_client,
    inspect_clients,
    plan_mcp_setup,
    resolve_client_ids,
    resolve_client_paths,
    resolve_mcp_command,
    run_mcp_doctor,
    run_mcp_setup,
    strip_jsonc,
)

FIXED_CMD = ["/opt/allwr/bin/allwr-toolkit", "mcp", "serve"]


def test_all_26_clients_registered() -> None:
    ids = available_client_ids()
    assert len(ids) == 26
    assert len(set(ids)) == 26
    assert "claude_code" in ids
    assert "codex" in ids
    assert "dsh" in ids
    assert "freebuff" in ids
    assert "grok_bot" in ids


def test_resolve_client_ids_normalization_and_validation() -> None:
    assert resolve_client_ids(None) is None
    assert resolve_client_ids([]) is None
    assert resolve_client_ids([" , "]) is None
    assert resolve_client_ids(["cursor, codex", "cursor", "CLAUDE_CODE"]) == [
        "cursor",
        "codex",
        "claude_code",
    ]
    assert resolve_client_ids(["all"]) == available_client_ids()

    with pytest.raises(ConfigurationError, match="unknown MCP client"):
        resolve_client_ids(["cursor,not_a_client"])

    with pytest.raises(ConfigurationError, match="unknown MCP client"):
        resolve_client_ids(["all,not_a_client"])


def test_resolve_mcp_command_modes() -> None:
    cmd, args = resolve_mcp_command(FIXED_CMD)
    assert cmd == "/opt/allwr/bin/allwr-toolkit"
    assert args == ["mcp", "serve"]

    with pytest.raises(ConfigurationError, match="must not be empty"):
        resolve_mcp_command([])

    cmd2, args2 = resolve_mcp_command(which=lambda _: "/usr/local/bin/allwr-toolkit")
    assert cmd2 == "/usr/local/bin/allwr-toolkit"
    assert args2 == ["mcp", "serve"]

    cmd3, args3 = resolve_mcp_command(
        which=lambda _: None,
        python_executable="/opt/python3.12/bin/python",
    )
    assert cmd3 == "/opt/python3.12/bin/python"
    assert args3 == ["-m", "allwr_toolkit.cli.main", "mcp", "serve"]


def test_strip_jsonc_handles_comments_bom_strings_and_trailing_commas() -> None:
    raw = (
        "\ufeff{\n"
        '  // line comment with "quotes" and https://allwr.example.com\n'
        '  "url": "https://allwr.example.com/api/*not-a-comment*/",\n'
        '  "escaped": "val\\\\\\"ue",\n'
        "  /* multi-line\n"
        "     block comment */\n"
        '  "items": [\n'
        '    "a",\n'
        '    "b",\n'
        "  ],\n"
        "}\n"
    )
    parsed = json.loads(strip_jsonc(raw))
    assert parsed["url"] == "https://allwr.example.com/api/*not-a-comment*/"
    assert parsed["escaped"] == 'val\\"ue'
    assert parsed["items"] == ["a", "b"]

    with pytest.raises(ValueError, match="unterminated block comment"):
        strip_jsonc('{"a": 1} /* unclosed')


@pytest.mark.parametrize(
    "spec_id",
    [spec.client_id for spec in CLIENT_SPECS if spec.format != "manual"],
)
def test_create_verify_and_idempotent_rerun_all_25_configurable_clients(
    tmp_path: Path, spec_id: str
) -> None:
    env: dict[str, str] = {}
    first = apply_client_setup(
        spec_id,
        home=tmp_path,
        environ=env,
        platform="linux",
        command=FIXED_CMD,
    )
    assert first.status == "configured"
    assert first.action == "create"
    assert first.config_path is not None and first.config_path.is_file()
    assert first.backup_path is None

    # Security invariant: never enable ALLWR_MCP_ALLOW_WRITES in generated configs.
    raw_content = first.config_path.read_text(encoding="utf-8")
    assert "ALLWR_MCP_ALLOW_WRITES" not in raw_content

    inspected = inspect_client(
        spec_id,
        home=tmp_path,
        environ=env,
        platform="linux",
        command=FIXED_CMD,
    )
    assert inspected.status == "configured"
    assert inspected.action == "none"

    # Re-running setup when already configured must be a no-op with no backup created.
    second = apply_client_setup(
        spec_id,
        home=tmp_path,
        environ=env,
        platform="linux",
        command=FIXED_CMD,
    )
    assert second.status == "unchanged"
    assert second.action == "none"
    assert second.backup_path is None
    backup_candidate = first.config_path.with_name(f"{first.config_path.name}.allwr-toolkit.backup")
    assert not backup_candidate.exists()


def test_grok_bot_manual_client(tmp_path: Path) -> None:
    marker = tmp_path / ".grokbot"
    marker.mkdir(parents=True)
    inspected = inspect_client(
        "grok_bot",
        home=tmp_path,
        environ={},
        platform="linux",
        command=FIXED_CMD,
    )
    assert inspected.detected is True
    assert inspected.status == "manual"
    assert inspected.action == "manual"
    assert inspected.config_path is None
    assert inspected.remediation is not None and SERVER_KEY in inspected.remediation

    applied = apply_client_setup(
        "grok_bot",
        home=tmp_path,
        environ={},
        platform="linux",
        command=FIXED_CMD,
    )
    assert applied.status == "manual"
    assert applied.action == "manual"


def test_freebuff_shared_registration_detection(tmp_path: Path) -> None:
    # Even if ~/.agents/mcp.json exists from another agent, freebuff is not detected
    # unless ~/.config/freebuff-desktop exists.
    shared_cfg = tmp_path / ".agents" / "mcp.json"
    shared_cfg.parent.mkdir(parents=True)
    shared_cfg.write_text('{"mcpServers": {}}\n', encoding="utf-8")

    not_detected = inspect_client(
        "freebuff",
        home=tmp_path,
        environ={},
        platform="linux",
        command=FIXED_CMD,
    )
    assert not_detected.detected is False

    (tmp_path / ".config" / "freebuff-desktop").mkdir(parents=True)
    detected = inspect_client(
        "freebuff",
        home=tmp_path,
        environ={},
        platform="linux",
        command=FIXED_CMD,
    )
    assert detected.detected is True


def test_platform_and_env_path_resolution(tmp_path: Path) -> None:
    # macOS paths
    cfg_mac, _ = resolve_client_paths(
        "claude_desktop", home=tmp_path, environ={}, platform="darwin"
    )
    assert cfg_mac == (
        tmp_path / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    )
    vs_mac, _ = resolve_client_paths("vscode", home=tmp_path, environ={}, platform="darwin")
    assert vs_mac == tmp_path / "Library" / "Application Support" / "Code" / "User" / "mcp.json"
    trae_mac, _ = resolve_client_paths("trae", home=tmp_path, environ={}, platform="darwin")
    assert trae_mac == tmp_path / "Library" / "Application Support" / "Trae" / "User" / "mcp.json"

    # Windows paths & Claude Desktop MSIX detection
    appdata = tmp_path / "Roaming"
    localappdata = tmp_path / "Local"
    win_env = {"APPDATA": str(appdata), "LOCALAPPDATA": str(localappdata)}
    cfg_win_std, _ = resolve_client_paths(
        "claude_desktop", home=tmp_path, environ=win_env, platform="win32"
    )
    assert cfg_win_std == appdata / "Claude" / "claude_desktop_config.json"

    msix_pkg = localappdata / "Packages" / "Claude_pzs8sxrjxfjjc"
    msix_pkg.mkdir(parents=True)
    cfg_win_msix, _ = resolve_client_paths(
        "claude_desktop", home=tmp_path, environ=win_env, platform="win32"
    )
    assert cfg_win_msix == (
        msix_pkg / "LocalCache" / "Roaming" / "Claude" / "claude_desktop_config.json"
    )

    devin_win, _ = resolve_client_paths("devin", home=tmp_path, environ=win_env, platform="win32")
    assert devin_win == appdata / "devin" / "mcp_config.json"
    vs_win, _ = resolve_client_paths("vscode", home=tmp_path, environ=win_env, platform="win32")
    assert vs_win == appdata / "Code" / "User" / "mcp.json"
    trae_win, _ = resolve_client_paths("trae", home=tmp_path, environ=win_env, platform="win32")
    assert trae_win == appdata / "Trae" / "User" / "mcp.json"
    hermes_win, _ = resolve_client_paths("hermes", home=tmp_path, environ=win_env, platform="win32")
    assert hermes_win == localappdata / "hermes" / "config.yaml"

    # Environment overrides and tilde expansion
    override_env = {
        "CLAUDE_CONFIG_DIR": "~/custom-claude",
        "VSCODE_PORTABLE": str(tmp_path / "vs-portable"),
        "OPENCODE_CONFIG": "~/custom-opencode.jsonc",
        "HERMES_HOME": "~",
    }
    cc_cfg, _ = resolve_client_paths(
        "claude_code", home=tmp_path, environ=override_env, platform="linux"
    )
    assert cc_cfg == tmp_path / "custom-claude" / ".claude.json"
    vs_port, _ = resolve_client_paths(
        "vscode", home=tmp_path, environ=override_env, platform="linux"
    )
    assert vs_port == tmp_path / "vs-portable" / "user-data" / "User" / "mcp.json"
    oc_cfg, _ = resolve_client_paths(
        "opencode", home=tmp_path, environ=override_env, platform="linux"
    )
    assert oc_cfg == tmp_path / "custom-opencode.jsonc"
    hm_cfg, _ = resolve_client_paths(
        "hermes", home=tmp_path, environ=override_env, platform="linux"
    )
    assert hm_cfg == tmp_path / "config.yaml"

    vs_appdata, _ = resolve_client_paths(
        "vscode",
        home=tmp_path,
        environ={"VSCODE_APPDATA": str(tmp_path / "vs-appdata")},
        platform="linux",
    )
    assert vs_appdata == tmp_path / "vs-appdata" / "Code" / "User" / "mcp.json"

    with pytest.raises(ConfigurationError, match="unknown MCP client"):
        resolve_client_paths("nonexistent", home=tmp_path, environ={}, platform="linux")


def test_opencode_v2_and_copilot_tools_and_omp_and_grok_disabled_cleanup(tmp_path: Path) -> None:
    # 1. OpenCode V2 (mcp.servers dict exists) with JSONC comments
    oc_dir = tmp_path / ".config" / "opencode"
    oc_dir.mkdir(parents=True)
    oc_file = oc_dir / "opencode.jsonc"
    oc_file.write_text(
        "// OpenCode V2 config\n"
        "{\n"
        '  "mcp": {\n'
        '    "servers": {\n'
        '      "other": {"type": "local", "command": ["echo"]},\n'
        "    },\n"
        "  },\n"
        "}\n",
        encoding="utf-8",
    )
    oc_res = apply_client_setup(
        "opencode", home=tmp_path, environ={}, platform="linux", command=FIXED_CMD
    )
    assert oc_res.status == "configured"
    assert oc_res.config_path == oc_file
    oc_data = json.loads(oc_file.read_text(encoding="utf-8"))
    assert oc_data["mcp"]["servers"][SERVER_KEY] == {
        "type": "local",
        "command": FIXED_CMD,
        "disabled": False,
    }
    assert "other" in oc_data["mcp"]["servers"]

    # 2. Copilot CLI preserves existing non-empty tools list
    cp_dir = tmp_path / ".copilot"
    cp_dir.mkdir(parents=True)
    cp_file = cp_dir / "mcp-config.json"
    cp_file.write_text(
        json.dumps(
            {
                "mcpServers": {
                    SERVER_KEY: {
                        "type": "stdio",
                        "command": "/old/bin/allwr-toolkit",
                        "args": ["mcp", "serve"],
                        "tools": ["list_connectors", "inspect_plan"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    cp_res = apply_client_setup(
        "copilot_cli", home=tmp_path, environ={}, platform="linux", command=FIXED_CMD
    )
    assert cp_res.status == "configured"
    cp_data = json.loads(cp_file.read_text(encoding="utf-8"))
    assert cp_data["mcpServers"][SERVER_KEY]["tools"] == ["list_connectors", "inspect_plan"]
    assert cp_data["mcpServers"][SERVER_KEY]["command"] == FIXED_CMD[0]

    # 3. OMP removes allwr-toolkit from disabledServers
    omp_dir = tmp_path / ".omp" / "agent"
    omp_dir.mkdir(parents=True)
    omp_file = omp_dir / "mcp.json"
    omp_file.write_text(
        json.dumps(
            {
                "disabledServers": [SERVER_KEY, "other-server"],
                "mcpServers": {
                    SERVER_KEY: {
                        "type": "stdio",
                        "command": FIXED_CMD[0],
                        "args": FIXED_CMD[1:],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    assert (
        inspect_client("omp", home=tmp_path, environ={}, platform="linux", command=FIXED_CMD).status
        == "outdated"
    )
    omp_res = apply_client_setup(
        "omp", home=tmp_path, environ={}, platform="linux", command=FIXED_CMD
    )
    assert omp_res.status == "configured"
    omp_data = json.loads(omp_file.read_text(encoding="utf-8"))
    assert omp_data["disabledServers"] == ["other-server"]

    # 4. Grok Build removes allwr-toolkit from disabled_mcp_servers and preserves other TOML tables
    grok_dir = tmp_path / ".grok"
    grok_dir.mkdir(parents=True)
    grok_file = grok_dir / "config.toml"
    grok_file.write_text(
        'disabled_mcp_servers = ["allwr-toolkit", "keep-disabled"]\n\n'
        "[mcp_servers.allwr-toolkit]\n"
        'command = "/old/allwr-toolkit"\n'
        'args = ["mcp", "serve"]\n'
        "startup_timeout_sec = 10\n\n"
        '[mcp_servers.other]\ncommand = "other"\nargs = []\n',
        encoding="utf-8",
    )
    assert (
        inspect_client(
            "grok_build", home=tmp_path, environ={}, platform="linux", command=FIXED_CMD
        ).status
        == "outdated"
    )
    grok_res = apply_client_setup(
        "grok_build", home=tmp_path, environ={}, platform="linux", command=FIXED_CMD
    )
    assert grok_res.status == "configured"
    grok_parsed = tomllib.loads(grok_file.read_text(encoding="utf-8"))
    assert grok_parsed["disabled_mcp_servers"] == ["keep-disabled"]
    assert grok_parsed["mcp_servers"][SERVER_KEY]["command"] == FIXED_CMD[0]
    assert grok_parsed["mcp_servers"]["other"]["command"] == "other"


def test_backup_and_recovery_rotation(tmp_path: Path) -> None:
    cursor_dir = tmp_path / ".cursor"
    cursor_dir.mkdir(parents=True)
    cfg_path = cursor_dir / "mcp.json"

    v1_bytes = b'{\n  "mcpServers": {\n    "other": {"command": "echo", "args": ["v1"]}\n  }\n}\n'
    cfg_path.write_bytes(v1_bytes)

    # First setup creates .allwr-toolkit.backup with v1_bytes
    res1 = apply_client_setup(
        "cursor",
        home=tmp_path,
        environ={},
        platform="linux",
        command=["/bin/allwr-toolkit", "mcp", "serve"],
    )
    assert res1.status == "configured"
    backup_path = cfg_path.with_name("mcp.json.allwr-toolkit.backup")
    assert res1.backup_path == backup_path
    assert res1.recovery_path is None
    assert backup_path.read_bytes() == v1_bytes

    # Second setup with a new command updates the file and rotates v1 backup to .recovery
    v2_bytes = cfg_path.read_bytes()
    expected_digest = hashlib.sha256(v1_bytes).hexdigest()
    expected_recovery = cfg_path.with_name(
        f"mcp.json.allwr-toolkit.backup.{expected_digest}.recovery"
    )

    res2 = apply_client_setup(
        "cursor",
        home=tmp_path,
        environ={},
        platform="linux",
        command=["/opt/new/allwr-toolkit", "mcp", "serve"],
    )
    assert res2.status == "configured"
    assert res2.backup_path == backup_path
    assert res2.recovery_path == expected_recovery
    assert expected_recovery.read_bytes() == v1_bytes
    assert backup_path.read_bytes() == v2_bytes


def test_foreign_conflict_refusal_across_formats(tmp_path: Path) -> None:
    # JSONC conflict (cursor)
    cursor_cfg = tmp_path / ".cursor" / "mcp.json"
    cursor_cfg.parent.mkdir(parents=True)
    foreign_json = (
        '{"mcpServers": {"allwr-toolkit": {"command": "/usr/bin/foreign-mcp", "args": []}}}\n'
    )
    cursor_cfg.write_text(foreign_json, encoding="utf-8")

    c_res = apply_client_setup(
        "cursor", home=tmp_path, environ={}, platform="linux", command=FIXED_CMD
    )
    assert c_res.status == "conflict"
    assert c_res.action == "conflict"
    assert cursor_cfg.read_text(encoding="utf-8") == foreign_json

    # TOML conflict (codex)
    codex_cfg = tmp_path / ".codex" / "config.toml"
    codex_cfg.parent.mkdir(parents=True)
    foreign_toml = '[mcp_servers.allwr-toolkit]\ncommand = "/usr/bin/foreign"\nargs = []\n'
    codex_cfg.write_text(foreign_toml, encoding="utf-8")

    t_res = apply_client_setup(
        "codex", home=tmp_path, environ={}, platform="linux", command=FIXED_CMD
    )
    assert t_res.status == "conflict"
    assert codex_cfg.read_text(encoding="utf-8") == foreign_toml

    # YAML conflict (hermes & dsh)
    hermes_cfg = tmp_path / ".hermes" / "config.yaml"
    hermes_cfg.parent.mkdir(parents=True)
    foreign_hermes = "mcp_servers:\n  allwr-toolkit:\n    command: /usr/bin/foreign\n    args: []\n"
    hermes_cfg.write_text(foreign_hermes, encoding="utf-8")

    h_res = apply_client_setup(
        "hermes", home=tmp_path, environ={}, platform="linux", command=FIXED_CMD
    )
    assert h_res.status == "conflict"
    assert hermes_cfg.read_text(encoding="utf-8") == foreign_hermes

    dsh_cfg = tmp_path / ".dsh" / "cordis.patch.yml"
    dsh_cfg.parent.mkdir(parents=True)
    foreign_dsh = yaml.safe_dump(
        {
            "insert": [
                {
                    "id": DSH_PLUGIN_ID,
                    "name": DSH_PLUGIN_NAME,
                    "config": {
                        "serverName": SERVER_KEY,
                        "transport": "stdio",
                        "command": "/usr/bin/foreign",
                        "args": [],
                    },
                }
            ]
        }
    )
    dsh_cfg.write_text(foreign_dsh, encoding="utf-8")
    d_res = apply_client_setup(
        "dsh", home=tmp_path, environ={}, platform="linux", command=FIXED_CMD
    )
    assert d_res.status == "conflict"
    assert dsh_cfg.read_text(encoding="utf-8") == foreign_dsh


def test_malformed_configurations_reported_without_overwriting(tmp_path: Path) -> None:
    # Malformed strict JSON (comments not allowed in claude_code .claude.json)
    cc_cfg = tmp_path / ".claude.json"
    cc_cfg.write_text(
        '// comment not allowed in strict JSON\n{"mcpServers": {}}\n', encoding="utf-8"
    )
    assert (
        inspect_client(
            "claude_code", home=tmp_path, environ={}, platform="linux", command=FIXED_CMD
        ).status
        == "malformed"
    )

    # Non-object root JSON
    cursor_cfg = tmp_path / ".cursor" / "mcp.json"
    cursor_cfg.parent.mkdir(parents=True)
    cursor_cfg.write_text("[1, 2, 3]\n", encoding="utf-8")
    assert (
        inspect_client(
            "cursor", home=tmp_path, environ={}, platform="linux", command=FIXED_CMD
        ).status
        == "malformed"
    )

    # Malformed TOML
    codex_cfg = tmp_path / ".codex" / "config.toml"
    codex_cfg.parent.mkdir(parents=True)
    codex_cfg.write_text("[mcp_servers\nbroken = \n", encoding="utf-8")
    assert (
        inspect_client(
            "codex", home=tmp_path, environ={}, platform="linux", command=FIXED_CMD
        ).status
        == "malformed"
    )

    # Malformed YAML (empty or invalid syntax)
    hermes_cfg = tmp_path / ".hermes" / "config.yaml"
    hermes_cfg.parent.mkdir(parents=True)
    hermes_cfg.write_text("   \n", encoding="utf-8")
    assert (
        inspect_client(
            "hermes", home=tmp_path, environ={}, platform="linux", command=FIXED_CMD
        ).status
        == "malformed"
    )

    dsh_cfg = tmp_path / ".dsh" / "cordis.patch.yml"
    dsh_cfg.parent.mkdir(parents=True)
    dsh_cfg.write_text("insert: not_a_list\n", encoding="utf-8")
    assert (
        inspect_client("dsh", home=tmp_path, environ={}, platform="linux", command=FIXED_CMD).status
        == "malformed"
    )


def test_plan_run_and_doctor_orchestration(tmp_path: Path) -> None:
    (tmp_path / ".cursor").mkdir(parents=True)
    (tmp_path / ".codex").mkdir(parents=True)

    planned = plan_mcp_setup(home=tmp_path, environ={}, platform="linux", command=FIXED_CMD)
    assert [p.client_id for p in planned] == ["codex", "cursor"]
    assert all(p.status == "planned" for p in planned)

    applied = run_mcp_setup(home=tmp_path, environ={}, platform="linux", command=FIXED_CMD)
    assert [a.client_id for a in applied] == ["codex", "cursor"]
    assert all(a.status == "configured" for a in applied)

    doctor_report = run_mcp_doctor(home=tmp_path, environ={}, platform="linux", command=FIXED_CMD)
    assert doctor_report["ok"] is True
    assert doctor_report["counts"]["configured"] == 2
    assert doctor_report["counts"]["total"] == 2

    all_report = run_mcp_doctor(
        client_ids=["all"], home=tmp_path, environ={}, platform="linux", command=FIXED_CMD
    )
    assert all_report["counts"]["total"] == 26
    assert len(inspect_clients(home=tmp_path, environ={}, platform="linux", command=FIXED_CMD)) == 2
