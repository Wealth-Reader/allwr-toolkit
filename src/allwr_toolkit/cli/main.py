"""The ``allwr-toolkit`` command line interface.

Exit codes: 0 success, 1 unexpected error, 2 configuration or validation
error, 3 apply blocked by unaccepted high severity warnings.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Annotated, Any

import typer

import allwr_toolkit
from allwr_toolkit.cli import workflows
from allwr_toolkit.configuration import load_config
from allwr_toolkit.connectors.base import available_connectors, get_connector
from allwr_toolkit.core.errors import (
    BlockedByWarningsError,
    ConfigurationError,
    PlanValidationError,
    ToolkitError,
)
from allwr_toolkit.core.planning import load_plan
from allwr_toolkit.security import install_redaction

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_VALIDATION = 2
EXIT_BLOCKED = 3

app = typer.Typer(
    name="allwr-toolkit",
    help="Migration, integration and automation tools for ALL WR.",
    no_args_is_help=True,
)
connectors_app = typer.Typer(help="Discover and describe source connectors.")
migrate_app = typer.Typer(help="Plan and execute migrations (dry-run by default).")
migration_app = typer.Typer(help="Operate on existing migration runs.")
mcp_app = typer.Typer(help="Model Context Protocol server.")
app.add_typer(connectors_app, name="connectors")
app.add_typer(migrate_app, name="migrate")
app.add_typer(migration_app, name="migration")
app.add_typer(mcp_app, name="mcp")

_state = {"json": False}


def _emit(payload: dict[str, Any], human: str) -> None:
    if _state["json"]:
        typer.echo(json.dumps(payload, indent=2, default=str))
    else:
        typer.echo(human)


def _fail(exc: ToolkitError) -> typer.Exit:
    code = (
        EXIT_VALIDATION if isinstance(exc, ConfigurationError | PlanValidationError) else EXIT_ERROR
    )
    if isinstance(exc, BlockedByWarningsError):
        code = EXIT_BLOCKED
    _emit({"error": exc.code, "message": str(exc)}, f"error [{exc.code}]: {exc}")
    return typer.Exit(code)


@app.callback()
def main_options(
    json_output: Annotated[
        bool, typer.Option("--json", help="Machine-readable JSON output.")
    ] = False,
    verbose: Annotated[bool, typer.Option("--verbose", help="Verbose logging.")] = False,
    debug: Annotated[
        bool,
        typer.Option(
            "--debug",
            help=(
                "Debug logging. Warning: debug output may include additional "
                "operational metadata (never credentials)."
            ),
        ),
    ] = False,
) -> None:
    _state["json"] = json_output
    level = logging.DEBUG if debug else logging.INFO if verbose else logging.WARNING
    logging.basicConfig(level=level)
    install_redaction()


@app.command()
def version() -> None:
    """Print the toolkit version."""
    _emit({"version": allwr_toolkit.__version__}, allwr_toolkit.__version__)


@app.command()
def doctor(
    config: Annotated[
        Path | None, typer.Option(help="Optional migration configuration to check.")
    ] = None,
) -> None:
    """Check the local setup: Python, dependencies and configuration."""
    import sys

    checks: list[dict[str, Any]] = [
        {
            "check": "python",
            "ok": sys.version_info >= (3, 11),
            "detail": sys.version.split()[0],
        }
    ]
    try:
        import mcp  # noqa: F401

        checks.append({"check": "mcp extra", "ok": True, "detail": "installed"})
    except ImportError:  # pragma: no cover - depends on extras
        checks.append({"check": "mcp extra", "ok": True, "detail": "not installed (optional)"})
    if config is not None:
        try:
            cfg = load_config(config)
            connector = workflows.make_connector(cfg)
            problems = connector.validate_configuration()
            checks.append(
                {
                    "check": f"configuration ({cfg.connector})",
                    "ok": not problems,
                    "detail": "; ".join(problems) or "valid",
                }
            )
        except ToolkitError as exc:
            checks.append({"check": "configuration", "ok": False, "detail": str(exc)})
    ok = all(c["ok"] for c in checks)
    human = "\n".join(
        f"[{'ok' if c['ok'] else 'FAIL'}] {c['check']}: {c['detail']}" for c in checks
    )
    _emit({"ok": ok, "checks": checks}, human)
    if not ok:
        raise typer.Exit(EXIT_VALIDATION)


@connectors_app.command("list")
def connectors_list() -> None:
    """List available source connectors."""
    rows = []
    for connector_id, cls in sorted(available_connectors().items()):
        meta = cls.metadata()
        rows.append(
            {
                "id": connector_id,
                "name": meta.display_name,
                "product": meta.source_product,
                "stability": meta.stability,
            }
        )
    human = "\n".join(f"{r['id']:<12} {r['name']} ({r['product']}, {r['stability']})" for r in rows)
    _emit({"connectors": rows}, human)


@connectors_app.command("describe")
def connectors_describe(connector_id: str) -> None:
    """Describe one connector: capabilities, configuration, limitations."""
    try:
        cls = get_connector(connector_id)
    except ConfigurationError as exc:
        raise _fail(exc) from exc
    meta = cls.metadata().model_dump()
    caps = cls.capabilities().model_dump()
    human_lines = [f"{meta['display_name']} ({meta['stability']})"]
    human_lines += [f"  requires: {', '.join(meta['required_configuration'])}"]
    human_lines += [f"  optional: {', '.join(meta['optional_configuration'])}"]
    human_lines += ["  limitations:"] + [f"   - {li}" for li in meta["known_limitations"]]
    _emit({"metadata": meta, "capabilities": caps}, "\n".join(human_lines))


def _check_connector_matches(config_path: Path, connector_id: str) -> None:
    cfg = load_config(config_path)
    if cfg.connector != connector_id:
        raise ConfigurationError(
            f"configuration is for connector '{cfg.connector}', not '{connector_id}'"
        )


def _register_migrate_commands(connector_id: str) -> None:
    """Register `migrate <connector> inspect|plan|apply` for one connector."""
    sub = typer.Typer(help=f"Migrate from {connector_id} (dry-run by default).")
    migrate_app.add_typer(sub, name=connector_id)

    @sub.command("inspect")
    def migrate_inspect(
        config: Annotated[Path, typer.Option(help="Migration configuration file.")],
    ) -> None:
        """Summarize what the source contains. Read-only."""
        try:
            _check_connector_matches(config, connector_id)
            summary = workflows.inspect_source(config)
        except ToolkitError as exc:
            raise _fail(exc) from exc
        counts = "\n".join(f"  {k}: {v}" for k, v in summary.record_counts.items())
        warnings = "\n".join(f"  [{w.severity.value}] {w.message}" for w in summary.warnings)
        _emit(
            summary.model_dump(),
            f"scope: {summary.scope}\ncounts:\n{counts}\nwarnings:\n{warnings or '  none'}",
        )

    @sub.command("plan")
    def migrate_plan(
        config: Annotated[Path, typer.Option(help="Migration configuration file.")],
        out: Annotated[Path, typer.Option(help="Where to write the plan.")] = Path(
            workflows.DEFAULT_PLAN_FILE
        ),
    ) -> None:
        """Build and save a migration plan. Read-only against the target."""
        try:
            _check_connector_matches(config, connector_id)
            plan = workflows.generate_plan(config, out)
        except ToolkitError as exc:
            raise _fail(exc) from exc
        confirmation = workflows.target_confirmation(plan)
        _emit(
            {
                "plan": str(out),
                "run_id": plan.run_id,
                "confirmation": confirmation.model_dump(),
            },
            (
                f"plan written to {out}\n"
                f"run id: {plan.run_id}\n"
                f"target: {confirmation.base_url} project {confirmation.project_id} "
                f"({confirmation.environment})\n"
                f"records: {confirmation.records} - writes: {confirmation.writes} - "
                f"attachments: {'yes' if confirmation.includes_attachments else 'no'}\n"
                f"high severity warnings: "
                f"{sum(1 for w in plan.warnings if w.severity.value == 'high')}"
            ),
        )

    @sub.command("apply")
    def migrate_apply(
        config: Annotated[Path, typer.Option(help="Migration configuration file.")],
        plan: Annotated[Path, typer.Option(help="Validated plan produced by 'plan'.")],
        yes: Annotated[
            bool, typer.Option("--yes", help="Confirm the target non-interactively.")
        ] = False,
        dry_run: Annotated[
            bool,
            typer.Option(
                "--dry-run/--no-dry-run",
                help="Dry-run is the default; writing requires --no-dry-run.",
            ),
        ] = True,
        state: Annotated[Path, typer.Option(help="Migration state database.")] = Path(
            workflows.DEFAULT_STATE_FILE
        ),
        report_dir: Annotated[Path, typer.Option(help="Directory for the report bundle.")] = Path(
            "."
        ),
    ) -> None:
        """Execute a plan. Without --no-dry-run nothing is written anywhere."""
        try:
            _check_connector_matches(config, connector_id)
            loaded = load_plan(plan)
            confirmation = workflows.target_confirmation(loaded)
            if not dry_run:
                typer.echo(
                    "About to WRITE to:\n"
                    f"  base URL:    {confirmation.base_url}\n"
                    f"  project:     {confirmation.project_id}\n"
                    f"  environment: {confirmation.environment}\n"
                    f"  records:     {confirmation.records}\n"
                    f"  writes:      {confirmation.writes}\n"
                    f"  attachments: "
                    f"{'yes' if confirmation.includes_attachments else 'no'}"
                )
                if not yes:
                    confirmed = typer.confirm("Proceed?", default=False)
                    if not confirmed:
                        typer.echo("aborted")
                        raise typer.Exit(EXIT_OK)
            result = workflows.run_migration(
                config, plan, state_path=state, dry_run=dry_run, report_dir=report_dir
            )
        except ToolkitError as exc:
            raise _fail(exc) from exc
        _emit(
            result.model_dump(),
            (
                f"run {result.run_id} {'(dry-run) ' if result.dry_run else ''}finished: "
                f"created={result.created} replayed={result.replayed} "
                f"skipped={result.skipped} failed={result.failed}"
                + (" - CANCELLED (resumable)" if result.cancelled else "")
            ),
        )
        if result.failed:
            raise typer.Exit(EXIT_ERROR)


for _connector_id in sorted(available_connectors()):
    _register_migrate_commands(_connector_id)


@migration_app.command("status")
def migration_status(
    run_id: str,
    state: Annotated[Path, typer.Option(help="Migration state database.")] = Path(
        workflows.DEFAULT_STATE_FILE
    ),
) -> None:
    """Show the status of one migration run."""
    try:
        payload = workflows.migration_status(run_id, state_path=state)
    except ToolkitError as exc:
        raise _fail(exc) from exc
    run = payload["run"]
    records = ", ".join(f"{k}={v}" for k, v in payload["records"].items()) or "no records"
    _emit(payload, f"run {run_id}: {run['status']} · {records}")


@migration_app.command("resume")
def migration_resume(
    run_id: str,
    config: Annotated[Path, typer.Option(help="Migration configuration file.")],
    plan: Annotated[Path, typer.Option(help="The plan of the run being resumed.")],
    yes: Annotated[bool, typer.Option("--yes", help="Confirm non-interactively.")] = False,
    state: Annotated[Path, typer.Option(help="Migration state database.")] = Path(
        workflows.DEFAULT_STATE_FILE
    ),
    report_dir: Annotated[Path, typer.Option(help="Report directory.")] = Path("."),
) -> None:
    """Resume an interrupted or cancelled run from its last checkpoint."""
    if not yes:
        confirmed = typer.confirm(f"Resume run {run_id} and write to the target?", default=False)
        if not confirmed:
            typer.echo("aborted")
            raise typer.Exit(EXIT_OK)
    try:
        result = workflows.resume_migration(
            config, plan, run_id, state_path=state, dry_run=False, report_dir=report_dir
        )
    except ToolkitError as exc:
        raise _fail(exc) from exc
    _emit(
        result.model_dump(),
        f"run {run_id} resumed: created={result.created} skipped={result.skipped} "
        f"failed={result.failed}",
    )


@migration_app.command("cancel")
def migration_cancel(
    run_id: str,
    state: Annotated[Path, typer.Option(help="Migration state database.")] = Path(
        workflows.DEFAULT_STATE_FILE
    ),
) -> None:
    """Mark a run cancelled. Its state stays resumable."""
    try:
        run = workflows.cancel_migration(run_id, state_path=state)
    except ToolkitError as exc:
        raise _fail(exc) from exc
    _emit(run.model_dump(), f"run {run_id} cancelled (state remains resumable)")


@migration_app.command("report")
def migration_report(
    run_id: str,
    plan: Annotated[Path, typer.Option(help="The plan of the run.")],
    state: Annotated[Path, typer.Option(help="Migration state database.")] = Path(
        workflows.DEFAULT_STATE_FILE
    ),
    out_dir: Annotated[Path, typer.Option(help="Report directory.")] = Path("."),
) -> None:
    """Generate the report bundle for a run."""
    try:
        paths = workflows.migration_report(run_id, plan, state_path=state, out_dir=out_dir)
    except ToolkitError as exc:
        raise _fail(exc) from exc
    _emit(
        {k: str(v) for k, v in paths.items()},
        "\n".join(f"{k}: {v}" for k, v in paths.items()),
    )


@migration_app.command("cleanup-plan")
def migration_cleanup_plan(
    run_id: str,
    state: Annotated[Path, typer.Option(help="Migration state database.")] = Path(
        workflows.DEFAULT_STATE_FILE
    ),
) -> None:
    """Print the cleanup manifest: records created by this run only."""
    try:
        manifest = workflows.cleanup_manifest(run_id, state_path=state)
    except ToolkitError as exc:
        raise _fail(exc) from exc
    _emit(
        manifest,
        f"run {run_id}: {len(manifest['records'])} records created by this run",
    )


@mcp_app.command("serve")
def mcp_serve() -> None:
    """Run the MCP server on stdio. Write tools stay disabled unless
    ALLWR_MCP_ALLOW_WRITES=true is set in the environment."""
    try:
        from allwr_toolkit.mcp.server import serve
    except ImportError as exc:  # pragma: no cover - depends on extras
        raise _fail(
            ConfigurationError("the MCP extra is not installed: pip install 'allwr-toolkit[mcp]'")
        ) from exc
    serve()  # pragma: no cover - blocks on stdio


def main() -> None:  # pragma: no cover - thin entry point
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
