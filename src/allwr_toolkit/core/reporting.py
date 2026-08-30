"""Report generation: machine-readable and human-readable outputs.

Reports identify what happened without leaking content: no task descriptions,
ticket bodies, comments or attachment contents are included by default, and
every free-text field passes through redaction.
"""

from __future__ import annotations

import csv
import html
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from allwr_toolkit.core.execution import ExecutionResult
from allwr_toolkit.core.planning import MigrationPlan
from allwr_toolkit.core.state import StateStore
from allwr_toolkit.security import redact, restrict


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    restrict(path)


def generate_reports(
    plan: MigrationPlan,
    result: ExecutionResult,
    state: StateStore,
    out_dir: str | Path,
) -> dict[str, Path]:
    """Write the report bundle and return the paths by kind."""
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    created = state.created_records(result.run_id)
    id_map = {r.source_record_id: r.target_record_id for r in created if r.target_record_id}
    report: dict[str, Any] = {
        "run_id": result.run_id,
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "dry_run": result.dry_run,
        "toolkit_version": plan.toolkit_version,
        "connector_version": plan.source.connector_version,
        "source": {"system": plan.source.system, "scope": plan.source.scope},
        "target": {
            "base_url": plan.target.base_url,
            "project_id": plan.target.project_id,
            "environment": plan.target.environment,
        },
        "counts": {
            "planned": len(plan.selected_ids),
            "created": result.created,
            "replayed": result.replayed,
            "skipped": result.skipped,
            "failed": result.failed,
            "comments_created": result.comments_created,
            "attachments_created": result.attachments_created,
            "relationships_created": result.relationships_created,
        },
        "cancelled": result.cancelled,
        "unsupported_fields": [f.model_dump() for f in plan.unsupported_fields],
        "warnings": [w.model_dump() for w in [*plan.warnings, *result.warnings]],
        "errors": [e.model_dump() for e in result.errors],
        "id_map": id_map,
    }
    paths: dict[str, Path] = {}

    paths["report_json"] = directory / "migration-report.json"
    _write_json(paths["report_json"], report)

    paths["report_html"] = directory / "migration-report.html"
    paths["report_html"].write_text(_render_html(report), encoding="utf-8")
    restrict(paths["report_html"])

    paths["errors_csv"] = directory / "migration-errors.csv"
    with open(paths["errors_csv"], "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["source_record_id", "operation", "message"])
        for error in result.errors:
            writer.writerow([error.source_record_id, error.operation, redact(error.message)])
    restrict(paths["errors_csv"])

    paths["warnings_csv"] = directory / "migration-warnings.csv"
    with open(paths["warnings_csv"], "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["code", "severity", "record_id", "message"])
        for warning in [*plan.warnings, *result.warnings]:
            writer.writerow(
                [
                    warning.code,
                    warning.severity.value,
                    warning.record_id or "",
                    redact(warning.message),
                ]
            )
    restrict(paths["warnings_csv"])

    paths["cleanup_json"] = directory / "migration-cleanup.json"
    _write_json(
        paths["cleanup_json"],
        {
            "run_id": result.run_id,
            "note": (
                "Records created by this run only. Deleting them removes everything "
                "this migration created and nothing else."
            ),
            "records": [
                {
                    "record_type": r.record_type,
                    "source_record_id": r.source_record_id,
                    "target_record_id": r.target_record_id,
                }
                for r in created
            ],
        },
    )
    return paths


def _render_html(report: dict[str, Any]) -> str:
    counts = report["counts"]
    rows = "".join(
        f"<tr><th>{html.escape(str(k))}</th><td>{html.escape(str(v))}</td></tr>"
        for k, v in counts.items()
    )
    warnings_rows = "".join(
        f"<tr><td>{html.escape(w['code'])}</td><td>{html.escape(w['severity'])}</td>"
        f"<td>{html.escape(str(w.get('record_id') or ''))}</td>"
        f"<td>{html.escape(redact(w['message']))}</td></tr>"
        for w in report["warnings"]
    )
    errors_rows = "".join(
        f"<tr><td>{html.escape(e['source_record_id'])}</td>"
        f"<td>{html.escape(e['operation'])}</td>"
        f"<td>{html.escape(redact(e['message']))}</td></tr>"
        for e in report["errors"]
    )
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Migration report {html.escape(report["run_id"])}</title>
<style>
 body {{ font-family: system-ui, sans-serif; margin: 2rem; color: #222; }}
 table {{ border-collapse: collapse; margin: 1rem 0; }}
 th, td {{ border: 1px solid #ccc; padding: 4px 10px; text-align: left; }}
 h1 {{ font-size: 1.3rem; }} h2 {{ font-size: 1.1rem; }}
 .meta {{ color: #666; }}
</style></head>
<body>
<h1>ALL WR Toolkit migration report</h1>
<p class="meta">Run {html.escape(report["run_id"])} ·
 {"DRY RUN (no writes)" if report["dry_run"] else "APPLY"} ·
 source {html.escape(report["source"]["system"])} ·
 target project {html.escape(str(report["target"]["project_id"]))}
 ({html.escape(report["target"]["environment"])})</p>
<h2>Counts</h2><table>{rows}</table>
<h2>Warnings ({len(report["warnings"])})</h2>
<table><tr><th>Code</th><th>Severity</th><th>Record</th><th>Message</th></tr>
{warnings_rows}</table>
<h2>Errors ({len(report["errors"])})</h2>
<table><tr><th>Record</th><th>Operation</th><th>Message</th></tr>{errors_rows}</table>
</body></html>
"""
