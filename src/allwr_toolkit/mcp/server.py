"""Safe MCP server for migration workflows.

Security model:

- read and planning tools are always available;
- mutating tools (clearly marked WRITE) are registered only when the server
  environment sets ``ALLWR_MCP_ALLOW_WRITES=true`` - an AI agent can never
  turn writes on from inside a session;
- apply requires a previously generated plan and re-verifies its hash and
  target before writing; the dry-run cycle cannot be skipped;
- no tool executes shell commands, arbitrary filesystem access or URLs;
- responses never contain credentials;
- every write is attributable to a migration run id.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from allwr_toolkit.cli import workflows
from allwr_toolkit.configuration import load_config
from allwr_toolkit.connectors.base import available_connectors, get_connector
from allwr_toolkit.core.errors import ToolkitError
from allwr_toolkit.core.planning import load_plan
from allwr_toolkit.security import redact

WRITE_ENV = "ALLWR_MCP_ALLOW_WRITES"
_MAX_PATH_LENGTH = 4096


def writes_allowed(environ: dict[str, str] | None = None) -> bool:
    env = environ if environ is not None else dict(os.environ)
    return env.get(WRITE_ENV, "").strip().lower() == "true"


def _checked_path(value: str) -> Path:
    if len(value) > _MAX_PATH_LENGTH:
        raise ValueError("path argument too long")
    return Path(value)


def _safe(payload: dict[str, Any]) -> str:
    return redact(json.dumps(payload, indent=2, default=str))


def _error(exc: Exception) -> str:
    code = exc.code if isinstance(exc, ToolkitError) else "error"
    return _safe({"ok": False, "error": code, "message": str(exc)})


def build_server(*, allow_writes: bool | None = None) -> FastMCP:
    """Build the MCP server. ``allow_writes`` defaults to the environment gate."""
    writes = writes_allowed() if allow_writes is None else allow_writes
    server = FastMCP(
        "allwr-toolkit",
        instructions=(
            "Migration tools for ALL WR. Read and planning tools are safe. "
            + (
                "Mutating tools are ENABLED on this server; apply_plan writes to "
                "the configured ALL WR target."
                if writes
                else "Mutating tools are DISABLED on this server "
                f"(set {WRITE_ENV}=true to enable them)."
            )
        ),
    )

    @server.tool()
    def list_connectors() -> str:
        """List the available source connectors (read-only)."""
        rows = {
            connector_id: cls.metadata().model_dump()
            for connector_id, cls in sorted(available_connectors().items())
        }
        return _safe({"ok": True, "connectors": rows})

    @server.tool()
    def describe_connector(connector_id: str) -> str:
        """Describe one connector's capabilities and limitations (read-only)."""
        try:
            cls = get_connector(connector_id[:100])
        except ToolkitError as exc:
            return _error(exc)
        return _safe(
            {
                "ok": True,
                "metadata": cls.metadata().model_dump(),
                "capabilities": cls.capabilities().model_dump(),
            }
        )

    @server.tool()
    def validate_config(config_path: str) -> str:
        """Validate a migration configuration file (read-only)."""
        try:
            config = load_config(_checked_path(config_path))
            connector = workflows.make_connector(config)
            problems = connector.validate_configuration()
        except (ToolkitError, ValueError) as exc:
            return _error(exc)
        return _safe({"ok": not problems, "problems": problems})

    @server.tool()
    def inspect_source(config_path: str) -> str:
        """Summarize what a source contains (read-only, no target access)."""
        try:
            summary = workflows.inspect_source(_checked_path(config_path))
        except (ToolkitError, ValueError) as exc:
            return _error(exc)
        return _safe({"ok": True, "summary": summary.model_dump()})

    @server.tool()
    def generate_plan(config_path: str, plan_path: str) -> str:
        """Generate a migration plan file (writes only the local plan file,
        never the target)."""
        try:
            plan = workflows.generate_plan(_checked_path(config_path), _checked_path(plan_path))
        except (ToolkitError, ValueError) as exc:
            return _error(exc)
        return _safe(
            {
                "ok": True,
                "run_id": plan.run_id,
                "plan_hash": plan.plan_hash,
                "confirmation": workflows.target_confirmation(plan).model_dump(),
            }
        )

    @server.tool()
    def inspect_plan(plan_path: str) -> str:
        """Show a plan's target, counts and warnings (read-only)."""
        try:
            plan = load_plan(_checked_path(plan_path))
        except (ToolkitError, ValueError) as exc:
            return _error(exc)
        return _safe(
            {
                "ok": True,
                "run_id": plan.run_id,
                "target": plan.target.model_dump(),
                "counts": plan.counts,
                "warnings": [w.model_dump() for w in plan.warnings],
                "plan_hash": plan.plan_hash,
            }
        )

    @server.tool()
    def migration_status(run_id: str, state_path: str) -> str:
        """Status of a migration run from its state database (read-only)."""
        try:
            payload = workflows.migration_status(run_id[:64], state_path=_checked_path(state_path))
        except (ToolkitError, ValueError) as exc:
            return _error(exc)
        return _safe({"ok": True, **payload})

    @server.tool()
    def migration_report(run_id: str, plan_path: str, state_path: str, out_dir: str) -> str:
        """Generate the report bundle for a run (writes local files only)."""
        try:
            paths = workflows.migration_report(
                run_id[:64],
                _checked_path(plan_path),
                state_path=_checked_path(state_path),
                out_dir=_checked_path(out_dir),
            )
        except (ToolkitError, ValueError) as exc:
            return _error(exc)
        return _safe({"ok": True, "reports": {k: str(v) for k, v in paths.items()}})

    if writes:

        @server.tool()
        def apply_plan(config_path: str, plan_path: str, state_path: str) -> str:
            """WRITE tool: apply a validated plan to the ALL WR target.

            Requires a plan generated beforehand; the plan hash and target are
            re-verified. A generic request to "migrate" is not approval: only
            call this after a human confirmed the exact plan."""
            try:
                result = workflows.run_migration(
                    _checked_path(config_path),
                    _checked_path(plan_path),
                    state_path=_checked_path(state_path),
                    dry_run=False,
                )
            except (ToolkitError, ValueError) as exc:
                return _error(exc)
            return _safe({"ok": True, "result": result.model_dump()})

        @server.tool()
        def resume_migration(config_path: str, plan_path: str, run_id: str, state_path: str) -> str:
            """WRITE tool: resume an interrupted run from its last checkpoint."""
            try:
                result = workflows.resume_migration(
                    _checked_path(config_path),
                    _checked_path(plan_path),
                    run_id[:64],
                    state_path=_checked_path(state_path),
                    dry_run=False,
                )
            except (ToolkitError, ValueError) as exc:
                return _error(exc)
            return _safe({"ok": True, "result": result.model_dump()})

        @server.tool()
        def cancel_migration(run_id: str, state_path: str) -> str:
            """WRITE tool: mark a run cancelled (state stays resumable)."""
            try:
                run = workflows.cancel_migration(run_id[:64], state_path=_checked_path(state_path))
            except (ToolkitError, ValueError) as exc:
                return _error(exc)
            return _safe({"ok": True, "run": run.model_dump()})

    return server


def serve() -> None:  # pragma: no cover - blocks on stdio
    build_server().run()
