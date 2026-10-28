"""Multi-agent MCP client detection, auto-setup, and doctor checks.

Supports 25 local MCP client configurations (JSON, JSONC, TOML, YAML) plus
hosted/manual client detection (`grok_bot`), following the REA safe setup
model:

- Read-only MCP registration (`allwr-toolkit mcp serve`) — never enables
  `ALLWR_MCP_ALLOW_WRITES` in client configs.
- Ownership checks prevent overwriting foreign entries under `allwr-toolkit`.
- Atomic writes with `.allwr-toolkit.backup` and content-addressed `.recovery`
  rotation when a previous backup differs.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

from allwr_toolkit.core.errors import ConfigurationError

SERVER_KEY = "allwr-toolkit"
DSH_PLUGIN_ID = "allwr-toolkit-mcp"
DSH_PLUGIN_NAME = "@deepseek-ai/dsh-mcp-client"
DEFAULT_STARTUP_TIMEOUT_SEC = 30

ClientFormat = Literal["json", "jsonc", "toml", "yaml", "manual"]
ClientStatus = Literal[
    "configured",
    "unchanged",
    "planned",
    "missing",
    "outdated",
    "conflict",
    "malformed",
    "manual",
]
SetupAction = Literal["none", "create", "update", "conflict", "malformed", "manual"]


@dataclass(frozen=True)
class ClientSpec:
    """Metadata and format rules for one supported MCP client."""

    client_id: str
    display_name: str
    format: ClientFormat
    shared_registration: bool = False


@dataclass
class ClientInspection:
    """Inspection or setup result for a single MCP client."""

    client_id: str
    display_name: str
    format: ClientFormat
    detected: bool
    config_path: Path | None
    markers: list[Path]
    status: ClientStatus
    action: SetupAction
    command: str
    args: list[str]
    message: str
    remediation: str | None = None
    backup_path: Path | None = None
    recovery_path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "client_id": self.client_id,
            "display_name": self.display_name,
            "format": self.format,
            "detected": self.detected,
            "config_path": str(self.config_path) if self.config_path is not None else None,
            "markers": [str(m) for m in self.markers],
            "status": self.status,
            "action": self.action,
            "command": self.command,
            "args": list(self.args),
            "message": self.message,
            "remediation": self.remediation,
            "backup_path": str(self.backup_path) if self.backup_path is not None else None,
            "recovery_path": str(self.recovery_path) if self.recovery_path is not None else None,
        }


CLIENT_SPECS: tuple[ClientSpec, ...] = (
    ClientSpec("claude_code", "Claude Code", "json"),
    ClientSpec("claude_desktop", "Claude Desktop", "jsonc"),
    ClientSpec("codex", "Codex", "toml"),
    ClientSpec("cursor", "Cursor", "jsonc"),
    ClientSpec("gemini_cli", "Gemini CLI", "jsonc"),
    ClientSpec("windsurf", "Windsurf", "jsonc"),
    ClientSpec("devin", "Devin", "jsonc"),
    ClientSpec("opencode", "OpenCode", "jsonc"),
    ClientSpec("antigravity", "Antigravity", "jsonc"),
    ClientSpec("copilot_cli", "GitHub Copilot CLI", "jsonc"),
    ClientSpec("commandcode", "Command Code", "jsonc"),
    ClientSpec("qwen_code", "Qwen Code", "jsonc"),
    ClientSpec("kimi", "Kimi Code", "json"),
    ClientSpec("vscode", "VS Code", "jsonc"),
    ClientSpec("trae", "Trae", "jsonc"),
    ClientSpec("workbuddy", "WorkBuddy", "jsonc"),
    ClientSpec("grok_build", "Grok Build", "toml"),
    ClientSpec("omp", "OMP", "jsonc"),
    ClientSpec("pi", "Pi", "json"),
    ClientSpec("hermes", "Hermes", "yaml"),
    ClientSpec("qoder", "Qoder", "jsonc"),
    ClientSpec("droid", "Factory Droid", "jsonc"),
    ClientSpec("zcode", "ZCode", "json"),
    ClientSpec("dsh", "DeepSeek Harness", "yaml"),
    ClientSpec("freebuff", "FreeBuff", "jsonc", shared_registration=True),
    ClientSpec("grok_bot", "Grok Bot", "manual"),
)

CLIENT_SPEC_MAP: dict[str, ClientSpec] = {spec.client_id: spec for spec in CLIENT_SPECS}


def available_client_ids() -> list[str]:
    """Return all supported MCP client IDs in canonical order."""
    return [spec.client_id for spec in CLIENT_SPECS]


def resolve_client_ids(raw_clients: Sequence[str] | None) -> list[str] | None:
    """Normalize repeatable / comma-separated client IDs.

    Returns ``None`` when no filter was provided (auto-detect mode).
    Returns all client IDs when ``all`` is requested.
    Raises :class:`ConfigurationError` on unknown client IDs.
    """
    if not raw_clients:
        return None
    tokens: list[str] = []
    for raw in raw_clients:
        for part in raw.split(","):
            cleaned = part.strip().lower()
            if cleaned:
                tokens.append(cleaned)
    if not tokens:
        return None
    if "all" in tokens:
        unknown = [t for t in tokens if t != "all" and t not in CLIENT_SPEC_MAP]
        if unknown:
            valid = ", ".join(available_client_ids())
            raise ConfigurationError(
                f"unknown MCP client(s): {', '.join(unknown)} (valid: {valid})"
            )
        return available_client_ids()
    unknown = [t for t in tokens if t not in CLIENT_SPEC_MAP]
    if unknown:
        valid = ", ".join(available_client_ids())
        raise ConfigurationError(f"unknown MCP client(s): {', '.join(unknown)} (valid: {valid})")
    deduped: list[str] = []
    for token in tokens:
        if token not in deduped:
            deduped.append(token)
    return deduped


def resolve_mcp_command(
    override: Sequence[str] | None = None,
    *,
    which: Callable[[str], str | None] = shutil.which,
    python_executable: str | None = None,
) -> tuple[str, list[str]]:
    """Resolve the ``(command, args)`` pair used to launch the MCP server."""
    if override is not None:
        items = [str(part) for part in override if str(part)]
        if not items:
            raise ConfigurationError("MCP command override must not be empty")
        return items[0], items[1:]
    found = which("allwr-toolkit")
    if found:
        return found, ["mcp", "serve"]
    py_exe = python_executable or sys.executable
    return py_exe, ["-m", "allwr_toolkit.cli.main", "mcp", "serve"]


def _env_path(environ: Mapping[str, str], key: str, home: Path) -> Path | None:
    raw = environ.get(key, "").strip()
    if not raw:
        return None
    if raw == "~":
        return home
    if raw.startswith("~/") or raw.startswith("~\\"):
        return home / raw[2:]
    return Path(raw)


def _xdg_config_home(home: Path, environ: Mapping[str, str]) -> Path:
    return _env_path(environ, "XDG_CONFIG_HOME", home) or (home / ".config")


def _win_appdata(home: Path, environ: Mapping[str, str]) -> Path:
    return _env_path(environ, "APPDATA", home) or (home / "AppData" / "Roaming")


def _win_localappdata(home: Path, environ: Mapping[str, str]) -> Path:
    return _env_path(environ, "LOCALAPPDATA", home) or (home / "AppData" / "Local")


def resolve_client_paths(
    client_id: str,
    *,
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
    platform: str | None = None,
) -> tuple[Path | None, list[Path]]:
    """Return ``(config_path, marker_paths)`` for ``client_id``."""
    env: Mapping[str, str] = environ if environ is not None else os.environ
    resolved_home = (
        home if home is not None else (_env_path(env, "HOME", Path.home()) or Path.home())
    )
    plat = platform if platform is not None else sys.platform
    xdg = _xdg_config_home(resolved_home, env)
    appdata = _win_appdata(resolved_home, env)
    localappdata = _win_localappdata(resolved_home, env)

    if client_id == "claude_code":
        custom = _env_path(env, "CLAUDE_CONFIG_DIR", resolved_home)
        if custom is not None:
            return custom / ".claude.json", [custom]
        return resolved_home / ".claude.json", [resolved_home / ".claude"]

    if client_id == "claude_desktop":
        if plat == "darwin":
            cfg = (
                resolved_home
                / "Library"
                / "Application Support"
                / "Claude"
                / "claude_desktop_config.json"
            )
            return cfg, [cfg.parent]
        if plat == "win32":
            std_cfg = appdata / "Claude" / "claude_desktop_config.json"
            msix_pkg = localappdata / "Packages" / "Claude_pzs8sxrjxfjjc"
            msix_cfg = msix_pkg / "LocalCache" / "Roaming" / "Claude" / "claude_desktop_config.json"
            chosen = (
                msix_cfg
                if (msix_cfg.exists() or msix_pkg.exists()) and not std_cfg.exists()
                else std_cfg
            )
            return chosen, [std_cfg.parent, msix_pkg, msix_cfg.parent]
        cfg = xdg / "Claude" / "claude_desktop_config.json"
        return cfg, [cfg.parent]

    if client_id == "codex":
        codex_dir = _env_path(env, "CODEX_HOME", resolved_home) or (resolved_home / ".codex")
        return codex_dir / "config.toml", [codex_dir]

    if client_id == "cursor":
        marker = resolved_home / ".cursor"
        return marker / "mcp.json", [marker]

    if client_id == "gemini_cli":
        base = _env_path(env, "GEMINI_CLI_HOME", resolved_home) or resolved_home
        marker = base / ".gemini"
        return marker / "settings.json", [marker]

    if client_id == "windsurf":
        marker = resolved_home / ".codeium" / "windsurf"
        return marker / "mcp_config.json", [marker]

    if client_id == "devin":
        base = appdata if plat == "win32" else xdg
        cfg = base / "devin" / "mcp_config.json"
        return cfg, [cfg.parent]

    if client_id == "opencode":
        explicit_cfg = _env_path(env, "OPENCODE_CONFIG", resolved_home)
        if explicit_cfg is not None:
            return explicit_cfg, [explicit_cfg.parent]
        opencode_dir = _env_path(env, "OPENCODE_CONFIG_DIR", resolved_home) or (xdg / "opencode")
        candidates = [
            opencode_dir / "opencode.jsonc",
            opencode_dir / "opencode.json",
            opencode_dir / "config.json",
        ]
        chosen = next((p for p in candidates if p.exists()), opencode_dir / "config.json")
        return chosen, [opencode_dir]

    if client_id == "antigravity":
        marker = resolved_home / ".gemini" / "config"
        return marker / "mcp_config.json", [marker]

    if client_id == "copilot_cli":
        marker = _env_path(env, "COPILOT_HOME", resolved_home) or (resolved_home / ".copilot")
        return marker / "mcp-config.json", [marker]

    if client_id == "commandcode":
        marker = resolved_home / ".commandcode"
        return marker / "mcp.json", [marker]

    if client_id == "qwen_code":
        marker = _env_path(env, "QWEN_HOME", resolved_home) or (resolved_home / ".qwen")
        return marker / "settings.json", [marker]

    if client_id == "kimi":
        marker = _env_path(env, "KIMI_CODE_HOME", resolved_home) or (resolved_home / ".kimi-code")
        return marker / "mcp.json", [marker]

    if client_id == "vscode":
        portable = _env_path(env, "VSCODE_PORTABLE", resolved_home)
        vscode_appdata = _env_path(env, "VSCODE_APPDATA", resolved_home)
        if portable is not None:
            user_data = portable / "user-data"
        elif vscode_appdata is not None:
            user_data = vscode_appdata / "Code"
        elif plat == "win32":
            user_data = appdata / "Code"
        elif plat == "darwin":
            user_data = resolved_home / "Library" / "Application Support" / "Code"
        else:
            user_data = xdg / "Code"
        return user_data / "User" / "mcp.json", [user_data]

    if client_id == "trae":
        if plat == "win32":
            trae_user = appdata / "Trae" / "User"
        elif plat == "darwin":
            trae_user = resolved_home / "Library" / "Application Support" / "Trae" / "User"
        else:
            trae_user = xdg / "Trae" / "User"
        return trae_user / "mcp.json", [trae_user, resolved_home / ".trae"]

    if client_id == "workbuddy":
        marker = resolved_home / ".workbuddy"
        return marker / "mcp.json", [marker]

    if client_id == "grok_build":
        marker = _env_path(env, "GROK_HOME", resolved_home) or (resolved_home / ".grok")
        return marker / "config.toml", [marker]

    if client_id == "omp":
        omp_base = _env_path(env, "PI_CONFIG_DIR", resolved_home) or (resolved_home / ".omp")
        agent_dir = omp_base / "agent"
        return agent_dir / "mcp.json", [agent_dir, omp_base]

    if client_id == "pi":
        pi_dir = _env_path(env, "PI_CODING_AGENT_DIR", resolved_home) or (
            resolved_home / ".pi" / "agent"
        )
        return pi_dir / "mcp.json", [pi_dir]

    if client_id == "hermes":
        custom = _env_path(env, "HERMES_HOME", resolved_home)
        if custom is not None:
            hermes_dir = custom
        elif plat == "win32":
            hermes_dir = localappdata / "hermes"
        else:
            hermes_dir = resolved_home / ".hermes"
        return hermes_dir / "config.yaml", [hermes_dir]

    if client_id == "qoder":
        marker = _env_path(env, "QODER_CONFIG_DIR", resolved_home) or (resolved_home / ".qoder")
        return marker / "settings.json", [marker]

    if client_id == "droid":
        base = _env_path(env, "FACTORY_HOME_OVERRIDE", resolved_home) or resolved_home
        marker = base / ".factory"
        return marker / "mcp.json", [marker]

    if client_id == "zcode":
        cli_dir = resolved_home / ".zcode" / "cli"
        return cli_dir / "config.json", [cli_dir, resolved_home / ".zcode"]

    if client_id == "dsh":
        marker = _env_path(env, "DSH_HOME", resolved_home) or (resolved_home / ".dsh")
        return marker / "cordis.patch.yml", [marker]

    if client_id == "freebuff":
        cfg = resolved_home / ".agents" / "mcp.json"
        marker = resolved_home / ".config" / "freebuff-desktop"
        return cfg, [marker]

    if client_id == "grok_bot":
        marker = _env_path(env, "SAND_DATA_ROOT", resolved_home) or (resolved_home / ".grokbot")
        return None, [marker]

    raise ConfigurationError(f"unknown MCP client: {client_id}")


def is_client_detected(spec: ClientSpec, config_path: Path | None, markers: Sequence[Path]) -> bool:
    """Return True if the client appears installed in the target environment."""
    if spec.shared_registration:
        return any(m.exists() for m in markers)
    if config_path is not None and config_path.exists():
        return True
    return any(m.exists() for m in markers)


def strip_jsonc(raw: str) -> str:
    """Strip UTF-8 BOM, ``//`` line comments, ``/* */`` block comments, and trailing commas."""
    text = raw.lstrip("\ufeff")
    out: list[str] = []
    idx = 0
    length = len(text)
    in_string = False

    while idx < length:
        ch = text[idx]
        if in_string:
            out.append(ch)
            if ch == "\\" and idx + 1 < length:
                out.append(text[idx + 1])
                idx += 2
                continue
            if ch == '"':
                in_string = False
            idx += 1
            continue

        if ch == '"':
            in_string = True
            out.append(ch)
            idx += 1
            continue

        if ch == "/" and idx + 1 < length:
            nxt = text[idx + 1]
            if nxt == "/":
                idx += 2
                while idx < length and text[idx] != "\n":
                    idx += 1
                continue
            if nxt == "*":
                idx += 2
                closed = False
                while idx + 1 < length:
                    if text[idx] == "*" and text[idx + 1] == "/":
                        idx += 2
                        closed = True
                        break
                    if text[idx] == "\n":
                        out.append("\n")
                    idx += 1
                if not closed:
                    raise ValueError("unterminated block comment in JSONC")
                continue

        out.append(ch)
        idx += 1

    no_comments = "".join(out)
    cleaned: list[str] = []
    idx = 0
    length = len(no_comments)
    in_string = False

    while idx < length:
        ch = no_comments[idx]
        if in_string:
            cleaned.append(ch)
            if ch == "\\" and idx + 1 < length:
                cleaned.append(no_comments[idx + 1])
                idx += 2
                continue
            if ch == '"':
                in_string = False
            idx += 1
            continue

        if ch == '"':
            in_string = True
            cleaned.append(ch)
            idx += 1
            continue

        if ch == ",":
            look = idx + 1
            while look < length and no_comments[look] in " \t\r\n":
                look += 1
            if look < length and no_comments[look] in "}]":
                idx += 1
                continue

        cleaned.append(ch)
        idx += 1

    return "".join(cleaned)


def _parse_json_or_jsonc(raw: str, *, allow_jsonc: bool) -> dict[str, Any]:
    stripped = raw.lstrip("\ufeff")
    if not stripped.strip():
        raise ValueError("configuration file is empty")
    source = strip_jsonc(stripped) if allow_jsonc else stripped
    parsed = json.loads(source)
    if not isinstance(parsed, dict):
        raise ValueError("root configuration value must be a JSON object")
    return parsed


def _is_owned_tokens(argv: Sequence[str]) -> bool:
    """Return True if command/args items clearly invoke ``allwr-toolkit``."""
    if not argv:
        return False
    for arg_item in argv:
        normalized = arg_item.replace("\\", "/").strip()
        basename = normalized.rsplit("/", maxsplit=1)[-1].lower()
        if basename in {"allwr-toolkit", "allwr-toolkit.exe", "allwr-toolkit.cmd"}:
            return True
        if arg_item == "allwr_toolkit" or arg_item.startswith("allwr_toolkit."):
            return True
        if "allwr-toolkit" in normalized.lower():
            return True
    return False


def _extract_entry_tokens(client_id: str, entry: Any) -> list[str] | None:
    """Extract ``[command, *args]`` from a client entry, or ``None`` if invalid shape."""
    if not isinstance(entry, dict):
        return None
    if client_id == "opencode":
        cmd_list = entry.get("command")
        if isinstance(cmd_list, list) and cmd_list and all(isinstance(x, str) for x in cmd_list):
            return list(cmd_list)
        if isinstance(cmd_list, str) and cmd_list:
            return [cmd_list]
        return None
    if client_id == "dsh":
        cfg = entry.get("config")
        if not isinstance(cfg, dict):
            return None
        cmd = cfg.get("command")
        args = cfg.get("args", [])
        if not isinstance(cmd, str) or not cmd or not isinstance(args, list):
            return None
        if not all(isinstance(x, str) for x in args):
            return None
        return [cmd, *args]

    cmd = entry.get("command")
    args = entry.get("args", [])
    if not isinstance(cmd, str) or not cmd:
        return None
    if not isinstance(args, list) or not all(isinstance(x, str) for x in args):
        return None
    return [cmd, *args]


def _desired_json_entry(
    client_id: str,
    cmd: str,
    args: list[str],
    existing_entry: dict[str, Any] | None = None,
    *,
    opencode_v2: bool = False,
) -> dict[str, Any]:
    if client_id == "opencode":
        if opencode_v2:
            return {"type": "local", "command": [cmd, *args], "disabled": False}
        return {"type": "local", "command": [cmd, *args], "enabled": True}
    if client_id == "copilot_cli":
        tools: list[str] = ["*"]
        if isinstance(existing_entry, dict):
            raw_tools = existing_entry.get("tools")
            if (
                isinstance(raw_tools, list)
                and raw_tools
                and all(isinstance(item, str) for item in raw_tools)
            ):
                tools = list(raw_tools)
        return {"type": "stdio", "command": cmd, "args": list(args), "tools": tools}
    if client_id == "commandcode":
        return {"transport": "stdio", "enabled": True, "command": cmd, "args": list(args)}
    if client_id in {"vscode", "omp", "pi"}:
        return {"type": "stdio", "command": cmd, "args": list(args)}
    return {"command": cmd, "args": list(args)}


def _inspect_and_render_json_family(
    spec: ClientSpec,
    existing_text: str | None,
    cmd: str,
    args: list[str],
) -> tuple[ClientStatus, SetupAction, str, str | None, str | None]:
    """Return ``(status, action, message, remediation, new_content)`` for JSON/JSONC clients."""
    if existing_text is None:
        root: dict[str, Any] = {}
        file_existed = False
    else:
        file_existed = True
        try:
            root = _parse_json_or_jsonc(existing_text, allow_jsonc=(spec.format == "jsonc"))
        except (ValueError, json.JSONDecodeError) as exc:
            return (
                "malformed",
                "malformed",
                f"Malformed {spec.format.upper()} configuration: {exc}",
                f"Fix syntax errors in {spec.display_name} configuration before running setup.",
                None,
            )

    existing_entry: Any = None
    opencode_v2 = False

    if spec.client_id == "opencode":
        mcp_node = root.get("mcp")
        if mcp_node is not None and not isinstance(mcp_node, dict):
            return (
                "malformed",
                "malformed",
                "Root 'mcp' field must be an object",
                "Ensure 'mcp' is a JSON object in OpenCode configuration.",
                None,
            )
        if isinstance(mcp_node, dict) and isinstance(mcp_node.get("servers"), dict):
            opencode_v2 = True
            existing_entry = mcp_node["servers"].get(SERVER_KEY)
        elif isinstance(mcp_node, dict):
            existing_entry = mcp_node.get(SERVER_KEY)
    elif spec.client_id == "zcode":
        mcp_node = root.get("mcp")
        if mcp_node is not None and not isinstance(mcp_node, dict):
            return (
                "malformed",
                "malformed",
                "Root 'mcp' field must be an object",
                "Ensure 'mcp' is a JSON object in ZCode configuration.",
                None,
            )
        if isinstance(mcp_node, dict):
            servers_node = mcp_node.get("servers")
            if servers_node is not None and not isinstance(servers_node, dict):
                return (
                    "malformed",
                    "malformed",
                    "'mcp.servers' field must be an object",
                    "Ensure 'mcp.servers' is a JSON object in ZCode configuration.",
                    None,
                )
            if isinstance(servers_node, dict):
                existing_entry = servers_node.get(SERVER_KEY)
    elif spec.client_id == "vscode":
        servers_node = root.get("servers")
        if servers_node is not None and not isinstance(servers_node, dict):
            return (
                "malformed",
                "malformed",
                "Root 'servers' field must be an object",
                "Ensure 'servers' is a JSON object in VS Code mcp.json.",
                None,
            )
        if isinstance(servers_node, dict):
            existing_entry = servers_node.get(SERVER_KEY)
    else:
        servers_node = root.get("mcpServers")
        if servers_node is not None and not isinstance(servers_node, dict):
            return (
                "malformed",
                "malformed",
                "Root 'mcpServers' field must be an object",
                f"Ensure 'mcpServers' is a JSON object in {spec.display_name} configuration.",
                None,
            )
        if isinstance(servers_node, dict):
            existing_entry = servers_node.get(SERVER_KEY)

    if existing_entry is not None:
        tokens = _extract_entry_tokens(spec.client_id, existing_entry)
        if tokens is None or not _is_owned_tokens(tokens):
            return (
                "conflict",
                "conflict",
                f"Existing '{SERVER_KEY}' entry belongs to an unrelated command",
                (
                    f"Remove or rename the foreign '{SERVER_KEY}' entry in "
                    f"{spec.display_name} configuration before running setup."
                ),
                None,
            )

    desired_entry = _desired_json_entry(
        spec.client_id,
        cmd,
        args,
        existing_entry if isinstance(existing_entry, dict) else None,
        opencode_v2=opencode_v2,
    )

    omp_disabled_needs_cleanup = False
    if spec.client_id == "omp":
        disabled_list = root.get("disabledServers")
        if isinstance(disabled_list, list) and SERVER_KEY in disabled_list:
            omp_disabled_needs_cleanup = True

    if (
        file_existed
        and isinstance(existing_entry, dict)
        and existing_entry == desired_entry
        and not omp_disabled_needs_cleanup
    ):
        return (
            "configured",
            "none",
            f"'{SERVER_KEY}' is already configured",
            None,
            None,
        )

    updated = dict(root)
    if spec.client_id == "opencode":
        mcp_copy = dict(updated.get("mcp") or {})
        if opencode_v2:
            servers_copy = dict(mcp_copy.get("servers") or {})
            servers_copy[SERVER_KEY] = desired_entry
            mcp_copy["servers"] = servers_copy
        else:
            mcp_copy[SERVER_KEY] = desired_entry
        updated["mcp"] = mcp_copy
    elif spec.client_id == "zcode":
        mcp_copy = dict(updated.get("mcp") or {})
        servers_copy = dict(mcp_copy.get("servers") or {})
        servers_copy[SERVER_KEY] = desired_entry
        mcp_copy["servers"] = servers_copy
        updated["mcp"] = mcp_copy
    elif spec.client_id == "vscode":
        servers_copy = dict(updated.get("servers") or {})
        servers_copy[SERVER_KEY] = desired_entry
        updated["servers"] = servers_copy
    else:
        servers_copy = dict(updated.get("mcpServers") or {})
        servers_copy[SERVER_KEY] = desired_entry
        updated["mcpServers"] = servers_copy

    if spec.client_id == "omp" and isinstance(updated.get("disabledServers"), list):
        updated["disabledServers"] = [
            item for item in updated["disabledServers"] if item != SERVER_KEY
        ]

    rendered = json.dumps(updated, indent=2) + "\n"
    if not file_existed:
        return (
            "missing",
            "create",
            f"'{SERVER_KEY}' is not registered (file does not exist)",
            "Run 'allwr-toolkit mcp setup --yes' to create and register the configuration.",
            rendered,
        )
    if existing_entry is None:
        return (
            "missing",
            "update",
            f"'{SERVER_KEY}' is not registered",
            "Run 'allwr-toolkit mcp setup --yes' to register the MCP server.",
            rendered,
        )
    return (
        "outdated",
        "update",
        f"'{SERVER_KEY}' registration is outdated",
        "Run 'allwr-toolkit mcp setup --yes' to update the MCP server command.",
        rendered,
    )


_TOML_SECTION_HEADER_RE = re.compile(r"^\s*\[([^\]]+)\]\s*(?:#.*)?$", re.MULTILINE)
_TOML_ALLWR_HEADERS = {
    f"mcp_servers.{SERVER_KEY}",
    f'mcp_servers."{SERVER_KEY}"',
    f"mcp_servers.'{SERVER_KEY}'",
}


def _render_toml_section(cmd: str, args: list[str]) -> str:
    args_literal = ", ".join(json.dumps(arg) for arg in args)
    return (
        f"[mcp_servers.{SERVER_KEY}]\n"
        f"command = {json.dumps(cmd)}\n"
        f"args = [{args_literal}]\n"
        f"startup_timeout_sec = {DEFAULT_STARTUP_TIMEOUT_SEC}\n"
    )


def _remove_from_toml_disabled_list(text: str, key: str, new_list: list[str]) -> str:
    """Update top-level ``disabled_mcp_servers = [...]`` in TOML text."""
    pattern = re.compile(r"^(\s*disabled_mcp_servers\s*=\s*)\[[^\]]*\]", re.MULTILINE)
    rendered_items = ", ".join(json.dumps(item) for item in new_list)
    return pattern.sub(rf"\1[{rendered_items}]", text, count=1)


def _upsert_toml_text(existing_text: str, section_block: str) -> str:
    matches = list(_TOML_SECTION_HEADER_RE.finditer(existing_text))
    for idx, match in enumerate(matches):
        header_name = match.group(1).strip()
        if header_name in _TOML_ALLWR_HEADERS:
            start = match.start()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(existing_text)
            prefix = existing_text[:start]
            suffix = existing_text[end:].lstrip("\n")
            if prefix and not prefix.endswith("\n"):
                prefix += "\n"
            joined = prefix + section_block
            if suffix:
                joined += "\n" + suffix
            return joined

    if not existing_text.strip():
        return section_block
    base = existing_text.rstrip() + "\n\n" + section_block
    return base


def _inspect_and_render_toml(
    spec: ClientSpec,
    existing_text: str | None,
    cmd: str,
    args: list[str],
) -> tuple[ClientStatus, SetupAction, str, str | None, str | None]:
    desired_section = _render_toml_section(cmd, args)
    desired_entry = {
        "command": cmd,
        "args": list(args),
        "startup_timeout_sec": DEFAULT_STARTUP_TIMEOUT_SEC,
    }

    if existing_text is None:
        return (
            "missing",
            "create",
            f"'{SERVER_KEY}' is not registered (file does not exist)",
            "Run 'allwr-toolkit mcp setup --yes' to create and register the configuration.",
            desired_section,
        )

    cleaned_text = existing_text.lstrip("\ufeff")
    try:
        parsed = tomllib.loads(cleaned_text)
    except tomllib.TOMLDecodeError as exc:
        return (
            "malformed",
            "malformed",
            f"Malformed TOML configuration: {exc}",
            f"Fix syntax errors in {spec.display_name} config.toml before running setup.",
            None,
        )

    mcp_servers = parsed.get("mcp_servers")
    if mcp_servers is not None and not isinstance(mcp_servers, dict):
        return (
            "malformed",
            "malformed",
            "'mcp_servers' in TOML configuration must be a table",
            f"Ensure 'mcp_servers' is a TOML table in {spec.display_name} config.toml.",
            None,
        )

    existing_entry = mcp_servers.get(SERVER_KEY) if isinstance(mcp_servers, dict) else None
    if existing_entry is not None:
        tokens = _extract_entry_tokens(spec.client_id, existing_entry)
        if tokens is None or not _is_owned_tokens(tokens):
            return (
                "conflict",
                "conflict",
                f"Existing '{SERVER_KEY}' entry belongs to an unrelated command",
                (
                    f"Remove or rename the foreign '[mcp_servers.{SERVER_KEY}]' section in "
                    f"{spec.display_name} config.toml before running setup."
                ),
                None,
            )

    grok_disabled_cleanup = False
    remaining_disabled: list[str] = []
    if spec.client_id == "grok_build":
        disabled_raw = parsed.get("disabled_mcp_servers")
        if isinstance(disabled_raw, list) and SERVER_KEY in disabled_raw:
            grok_disabled_cleanup = True
            remaining_disabled = [str(x) for x in disabled_raw if x != SERVER_KEY]

    if (
        isinstance(existing_entry, dict)
        and existing_entry == desired_entry
        and not grok_disabled_cleanup
    ):
        return (
            "configured",
            "none",
            f"'{SERVER_KEY}' is already configured",
            None,
            None,
        )

    working_text = cleaned_text
    if grok_disabled_cleanup:
        working_text = _remove_from_toml_disabled_list(working_text, SERVER_KEY, remaining_disabled)
    new_text = _upsert_toml_text(working_text, desired_section)

    try:
        verified = tomllib.loads(new_text)
    except tomllib.TOMLDecodeError as exc:  # pragma: no cover - defensive guard
        raise ConfigurationError(f"generated invalid TOML for {spec.client_id}: {exc}") from exc
    if verified.get("mcp_servers", {}).get(SERVER_KEY) != desired_entry:  # pragma: no cover
        raise ConfigurationError(f"TOML verification failed for {spec.client_id}")

    if existing_entry is None:
        return (
            "missing",
            "update",
            f"'{SERVER_KEY}' is not registered",
            "Run 'allwr-toolkit mcp setup --yes' to register the MCP server.",
            new_text,
        )
    return (
        "outdated",
        "update",
        f"'{SERVER_KEY}' registration is outdated",
        "Run 'allwr-toolkit mcp setup --yes' to update the MCP server command.",
        new_text,
    )


def _inspect_and_render_yaml(
    spec: ClientSpec,
    existing_text: str | None,
    cmd: str,
    args: list[str],
) -> tuple[ClientStatus, SetupAction, str, str | None, str | None]:
    file_existed = existing_text is not None
    if existing_text is None:
        root: dict[str, Any] = {}
    else:
        stripped = existing_text.lstrip("\ufeff")
        if not stripped.strip():
            return (
                "malformed",
                "malformed",
                "YAML configuration file is empty",
                f"Fix or remove empty {spec.display_name} YAML configuration before running setup.",
                None,
            )
        try:
            loaded = yaml.safe_load(stripped)
        except yaml.YAMLError as exc:
            return (
                "malformed",
                "malformed",
                f"Malformed YAML configuration: {exc}",
                f"Fix syntax errors in {spec.display_name} YAML config before running setup.",
                None,
            )
        if not isinstance(loaded, dict):
            return (
                "malformed",
                "malformed",
                "Root YAML configuration must be a mapping",
                f"Ensure root YAML value in {spec.display_name} configuration is a mapping.",
                None,
            )
        root = dict(loaded)

    if spec.client_id == "hermes":
        mcp_servers = root.get("mcp_servers")
        if mcp_servers is not None and not isinstance(mcp_servers, dict):
            return (
                "malformed",
                "malformed",
                "'mcp_servers' field must be a mapping",
                "Ensure 'mcp_servers' is a mapping in Hermes config.yaml.",
                None,
            )
        existing_entry = mcp_servers.get(SERVER_KEY) if isinstance(mcp_servers, dict) else None
        if existing_entry is not None:
            tokens = _extract_entry_tokens(spec.client_id, existing_entry)
            if tokens is None or not _is_owned_tokens(tokens):
                return (
                    "conflict",
                    "conflict",
                    f"Existing '{SERVER_KEY}' entry belongs to an unrelated command",
                    "Remove or rename the foreign 'allwr-toolkit' entry in Hermes config.yaml.",
                    None,
                )
        desired_entry = {"command": cmd, "args": list(args), "enabled": True}
        if file_existed and existing_entry == desired_entry:
            return ("configured", "none", f"'{SERVER_KEY}' is already configured", None, None)

        servers_copy = dict(mcp_servers or {})
        servers_copy[SERVER_KEY] = desired_entry
        root["mcp_servers"] = servers_copy
        rendered = yaml.safe_dump(root, sort_keys=False)
        if not file_existed:
            return (
                "missing",
                "create",
                f"'{SERVER_KEY}' is not registered (file does not exist)",
                "Run 'allwr-toolkit mcp setup --yes' to create and register the configuration.",
                rendered,
            )
        if existing_entry is None:
            return (
                "missing",
                "update",
                f"'{SERVER_KEY}' is not registered",
                "Run 'allwr-toolkit mcp setup --yes' to register the MCP server.",
                rendered,
            )
        return (
            "outdated",
            "update",
            f"'{SERVER_KEY}' registration is outdated",
            "Run 'allwr-toolkit mcp setup --yes' to update the MCP server command.",
            rendered,
        )

    # dsh (DeepSeek Harness)
    insert_list = root.get("insert")
    if insert_list is not None and not isinstance(insert_list, list):
        return (
            "malformed",
            "malformed",
            "'insert' field in cordis.patch.yml must be a list",
            "Ensure 'insert' is a list in DeepSeek Harness cordis.patch.yml.",
            None,
        )
    items = list(insert_list or [])
    desired_dsh_entry: dict[str, Any] = {
        "id": DSH_PLUGIN_ID,
        "name": DSH_PLUGIN_NAME,
        "config": {
            "serverName": SERVER_KEY,
            "transport": "stdio",
            "command": cmd,
            "args": list(args),
        },
    }

    match_index: int | None = None
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        cfg = item.get("config")
        is_target = item.get("id") == DSH_PLUGIN_ID or (
            isinstance(cfg, dict) and cfg.get("serverName") == SERVER_KEY
        )
        if is_target:
            tokens = _extract_entry_tokens("dsh", item)
            if (
                item.get("name") != DSH_PLUGIN_NAME
                or tokens is None
                or not _is_owned_tokens(tokens)
            ):
                return (
                    "conflict",
                    "conflict",
                    f"Existing '{DSH_PLUGIN_ID}' entry belongs to an unrelated command",
                    "Remove or update the foreign entry in cordis.patch.yml before running setup.",
                    None,
                )
            match_index = idx
            break

    if file_existed and match_index is not None and items[match_index] == desired_dsh_entry:
        return ("configured", "none", f"'{SERVER_KEY}' is already configured", None, None)

    if match_index is None:
        items.append(desired_dsh_entry)
    else:
        items[match_index] = desired_dsh_entry
    root["insert"] = items
    rendered = yaml.safe_dump(root, sort_keys=False)
    if not file_existed:
        return (
            "missing",
            "create",
            f"'{SERVER_KEY}' is not registered (file does not exist)",
            "Run 'allwr-toolkit mcp setup --yes' to create and register the configuration.",
            rendered,
        )
    if match_index is None:
        return (
            "missing",
            "update",
            f"'{SERVER_KEY}' is not registered",
            "Run 'allwr-toolkit mcp setup --yes' to register the MCP server.",
            rendered,
        )
    return (
        "outdated",
        "update",
        f"'{SERVER_KEY}' registration is outdated",
        "Run 'allwr-toolkit mcp setup --yes' to update the MCP server command.",
        rendered,
    )


def _inspect_and_render_client(
    spec: ClientSpec,
    config_path: Path | None,
    cmd: str,
    args: list[str],
) -> tuple[ClientStatus, SetupAction, str, str | None, str | None]:
    if spec.format == "manual" or config_path is None:
        manual_json = json.dumps({"command": cmd, "args": list(args)})
        return (
            "manual",
            "manual",
            f"{spec.display_name} does not use a local MCP configuration file.",
            (
                f"Register '{SERVER_KEY}' manually in {spec.display_name} with stdio "
                f"configuration: {manual_json}"
            ),
            None,
        )

    existing_text: str | None = None
    if config_path.exists():
        try:
            existing_text = config_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return (
                "malformed",
                "malformed",
                f"Cannot read configuration file: {exc}",
                f"Ensure {config_path} is readable UTF-8 text.",
                None,
            )

    if spec.format in {"json", "jsonc"}:
        return _inspect_and_render_json_family(spec, existing_text, cmd, args)
    if spec.format == "toml":
        return _inspect_and_render_toml(spec, existing_text, cmd, args)
    return _inspect_and_render_yaml(spec, existing_text, cmd, args)


def _atomic_write_bytes(target: Path, data: bytes, mode: int = 0o600) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, target)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise


def _write_with_backup(config_path: Path, new_text: str) -> tuple[Path | None, Path | None]:
    """Write ``new_text`` atomically to ``config_path``, rotating backups when modified."""
    new_bytes = new_text.encode("utf-8")
    backup_path: Path | None = None
    recovery_path: Path | None = None
    mode = 0o600

    if config_path.exists():
        try:
            stat_mode = config_path.stat().st_mode & 0o777
            if stat_mode:
                mode = stat_mode
        except OSError:  # pragma: no cover
            mode = 0o600
        old_bytes = config_path.read_bytes()
        if old_bytes == new_bytes:
            return None, None

        backup_path = config_path.with_name(f"{config_path.name}.allwr-toolkit.backup")
        if backup_path.exists():
            existing_backup = backup_path.read_bytes()
            if existing_backup != old_bytes:
                digest = hashlib.sha256(existing_backup).hexdigest()
                recovery_path = config_path.with_name(
                    f"{config_path.name}.allwr-toolkit.backup.{digest}.recovery"
                )
                _atomic_write_bytes(recovery_path, existing_backup, mode=0o600)
        _atomic_write_bytes(backup_path, old_bytes, mode=0o600)

    _atomic_write_bytes(config_path, new_bytes, mode=mode)
    return backup_path, recovery_path


def inspect_client(
    client_id: str,
    *,
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
    platform: str | None = None,
    command: Sequence[str] | None = None,
) -> ClientInspection:
    """Inspect a single MCP client without writing any files."""
    if client_id not in CLIENT_SPEC_MAP:
        raise ConfigurationError(f"unknown MCP client: {client_id}")
    spec = CLIENT_SPEC_MAP[client_id]
    cmd, args = resolve_mcp_command(command)
    config_path, markers = resolve_client_paths(
        client_id, home=home, environ=environ, platform=platform
    )
    detected = is_client_detected(spec, config_path, markers)
    status, action, message, remediation, _ = _inspect_and_render_client(
        spec, config_path, cmd, args
    )
    backup_candidate = (
        config_path.with_name(f"{config_path.name}.allwr-toolkit.backup")
        if config_path is not None and action == "update"
        else None
    )
    return ClientInspection(
        client_id=spec.client_id,
        display_name=spec.display_name,
        format=spec.format,
        detected=detected,
        config_path=config_path,
        markers=markers,
        status=status,
        action=action,
        command=cmd,
        args=args,
        message=message,
        remediation=remediation,
        backup_path=backup_candidate,
    )


def inspect_clients(
    *,
    client_ids: Sequence[str] | None = None,
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
    platform: str | None = None,
    command: Sequence[str] | None = None,
    include_undetected: bool = False,
) -> list[ClientInspection]:
    """Inspect target MCP clients (or all detected clients when ``client_ids`` is ``None``)."""
    normalized = resolve_client_ids(client_ids)
    explicit_all = bool(
        client_ids
        and any(part.strip().lower() == "all" for raw in client_ids for part in raw.split(","))
    )
    target_ids = normalized if normalized is not None else available_client_ids()
    results: list[ClientInspection] = []
    for cid in target_ids:
        item = inspect_client(
            cid,
            home=home,
            environ=environ,
            platform=platform,
            command=command,
        )
        if normalized is not None and not explicit_all:
            results.append(item)
        elif include_undetected or item.detected:
            results.append(item)
    return results


def apply_client_setup(
    client_id: str,
    *,
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
    platform: str | None = None,
    command: Sequence[str] | None = None,
) -> ClientInspection:
    """Apply MCP registration for one client and verify the written config."""
    if client_id not in CLIENT_SPEC_MAP:
        raise ConfigurationError(f"unknown MCP client: {client_id}")
    spec = CLIENT_SPEC_MAP[client_id]
    cmd, args = resolve_mcp_command(command)
    config_path, markers = resolve_client_paths(
        client_id, home=home, environ=environ, platform=platform
    )
    detected = is_client_detected(spec, config_path, markers)
    status, action, message, remediation, new_text = _inspect_and_render_client(
        spec, config_path, cmd, args
    )

    if action == "none":
        return ClientInspection(
            client_id=spec.client_id,
            display_name=spec.display_name,
            format=spec.format,
            detected=detected,
            config_path=config_path,
            markers=markers,
            status="unchanged",
            action=action,
            command=cmd,
            args=args,
            message=message,
            remediation=remediation,
        )

    if action not in {"create", "update"} or config_path is None or new_text is None:
        return ClientInspection(
            client_id=spec.client_id,
            display_name=spec.display_name,
            format=spec.format,
            detected=detected,
            config_path=config_path,
            markers=markers,
            status=status,
            action=action,
            command=cmd,
            args=args,
            message=message,
            remediation=remediation,
        )

    backup_path, recovery_path = _write_with_backup(config_path, new_text)
    verify_status, _, verify_msg, _, _ = _inspect_and_render_client(spec, config_path, cmd, args)
    if verify_status != "configured":  # pragma: no cover - defensive post-write check
        raise ConfigurationError(
            f"post-write verification failed for {spec.client_id}: {verify_msg}"
        )

    return ClientInspection(
        client_id=spec.client_id,
        display_name=spec.display_name,
        format=spec.format,
        detected=True,
        config_path=config_path,
        markers=markers,
        status="configured",
        action=action,
        command=cmd,
        args=args,
        message=f"Configured '{SERVER_KEY}' in {config_path}",
        remediation=None,
        backup_path=backup_path,
        recovery_path=recovery_path,
    )


def summarize_inspections(items: Sequence[ClientInspection]) -> dict[str, int]:
    """Compute status and action counts across a list of client inspections."""
    return {
        "total": len(items),
        "configured": sum(1 for item in items if item.status in {"configured", "unchanged"}),
        "unchanged": sum(1 for item in items if item.status == "unchanged"),
        "planned": sum(1 for item in items if item.status == "planned"),
        "missing": sum(1 for item in items if item.status == "missing"),
        "outdated": sum(1 for item in items if item.status == "outdated"),
        "conflict": sum(1 for item in items if item.status == "conflict"),
        "malformed": sum(1 for item in items if item.status == "malformed"),
        "manual": sum(1 for item in items if item.status == "manual"),
        "planned_writes": sum(1 for item in items if item.action in {"create", "update"}),
    }


def is_mcp_extra_installed() -> bool:
    """Return True if the optional ``mcp`` package is importable."""
    try:
        import mcp  # noqa: F401

        return True
    except ImportError:  # pragma: no cover - depends on extras
        return False


def plan_mcp_setup(
    *,
    client_ids: Sequence[str] | None = None,
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
    platform: str | None = None,
    command: Sequence[str] | None = None,
) -> list[ClientInspection]:
    """Build the setup plan for target clients without writing any files."""
    inspections = inspect_clients(
        client_ids=client_ids,
        home=home,
        environ=environ,
        platform=platform,
        command=command,
    )
    planned: list[ClientInspection] = []
    for item in inspections:
        if item.action == "none":
            planned.append(
                ClientInspection(
                    client_id=item.client_id,
                    display_name=item.display_name,
                    format=item.format,
                    detected=item.detected,
                    config_path=item.config_path,
                    markers=item.markers,
                    status="unchanged",
                    action="none",
                    command=item.command,
                    args=item.args,
                    message=item.message,
                    remediation=item.remediation,
                )
            )
        elif item.action in {"create", "update"}:
            planned.append(
                ClientInspection(
                    client_id=item.client_id,
                    display_name=item.display_name,
                    format=item.format,
                    detected=item.detected,
                    config_path=item.config_path,
                    markers=item.markers,
                    status="planned",
                    action=item.action,
                    command=item.command,
                    args=item.args,
                    message=item.message,
                    remediation=item.remediation,
                    backup_path=item.backup_path,
                )
            )
        else:
            planned.append(item)
    return planned


def run_mcp_setup(
    *,
    client_ids: Sequence[str] | None = None,
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
    platform: str | None = None,
    command: Sequence[str] | None = None,
) -> list[ClientInspection]:
    """Apply MCP setup across all target clients."""
    planned = plan_mcp_setup(
        client_ids=client_ids,
        home=home,
        environ=environ,
        platform=platform,
        command=command,
    )
    results: list[ClientInspection] = []
    for item in planned:
        results.append(
            apply_client_setup(
                item.client_id,
                home=home,
                environ=environ,
                platform=platform,
                command=command,
            )
        )
    return results


def run_mcp_doctor(
    *,
    client_ids: Sequence[str] | None = None,
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
    platform: str | None = None,
    command: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Run MCP doctor across detected (or requested) MCP clients."""
    cmd, args = resolve_mcp_command(command)
    mcp_installed = is_mcp_extra_installed()
    include_all = bool(
        client_ids
        and any(part.strip().lower() == "all" for raw in client_ids for part in raw.split(","))
    )
    inspections = inspect_clients(
        client_ids=client_ids,
        home=home,
        environ=environ,
        platform=platform,
        command=command,
        include_undetected=include_all,
    )
    counts = summarize_inspections(inspections)
    has_problems = any(item.status in {"conflict", "malformed"} for item in inspections)
    return {
        "ok": not has_problems,
        "mcp_extra_installed": mcp_installed,
        "server_key": SERVER_KEY,
        "command": cmd,
        "args": args,
        "counts": counts,
        "clients": [item.to_dict() for item in inspections],
    }
