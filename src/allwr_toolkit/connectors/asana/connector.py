"""Asana connector: offline export mode and live API mode.

Offline mode consumes an export directory with the layout::

    workspace.json                users, teams, projects
    projects/<gid>.json           project + sections + task gids
    tasks/<gid>.json              full task + stories + attachments + subtask gids
    attachments/<task_gid>/...    downloaded binaries

Both modes are driven by a curated *selection manifest* of GIDs (see
:mod:`allwr_toolkit.connectors.asana.manifest`).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from allwr_toolkit.connectors.asana.api import AsanaApiClient
from allwr_toolkit.connectors.asana.convert import to_canonical
from allwr_toolkit.connectors.asana.manifest import read_selection_manifest
from allwr_toolkit.connectors.base import (
    ConnectorCapabilities,
    ConnectorMetadata,
    InspectionSummary,
    SourceConnector,
)
from allwr_toolkit.core.errors import ConfigurationError, SourceError
from allwr_toolkit.core.models import (
    CanonicalTask,
    MigrationWarning,
    Severity,
    UnsupportedField,
)

CONNECTOR_VERSION = "0.1.0"


class AsanaConnector(SourceConnector):
    """Reads Asana tasks selected by a GID manifest."""

    def __init__(self, source_config: dict[str, Any]) -> None:
        super().__init__(source_config)
        self.mode: str = source_config.get("mode", "offline")
        self.data_dir: str | None = source_config.get("data_dir")
        self.manifest_path: str | None = source_config.get("selection_manifest")
        self.workspace_gid: str = str(source_config.get("workspace_gid", ""))
        self._api: AsanaApiClient | None = None
        self.unsupported_fields: list[UnsupportedField] = []
        self.warnings: list[MigrationWarning] = []

    # -- SDK ----------------------------------------------------------------

    @classmethod
    def metadata(cls) -> ConnectorMetadata:
        return ConnectorMetadata(
            connector_id="asana",
            display_name="Asana Importer",
            source_product="Asana",
            stability="beta",
            supported_record_types=[
                "project",
                "section",
                "task",
                "subtask",
                "comment",
                "attachment",
                "tag",
                "custom_field",
                "user",
            ],
            auth_modes=["personal_access_token", "offline_export"],
            required_configuration=["selection_manifest"],
            optional_configuration=["mode", "data_dir", "workspace_gid"],
            known_limitations=[
                "Dependencies, approval workflows and time tracking are reported "
                "as unsupported fields.",
                "Externally hosted attachments are linked, not copied.",
                "Original creation timestamps are preserved as import metadata.",
            ],
            rate_limit_strategy="Honors Retry-After on HTTP 429 with backoff.",
            supports_attachments=True,
            supports_incremental=False,
        )

    @classmethod
    def capabilities(cls) -> ConnectorCapabilities:
        return ConnectorCapabilities(
            record_types=["task"],
            supports_offline_export=True,
            supports_live_api=True,
            supports_selection_manifest=True,
            preserves_source_ids=True,
        )

    def validate_configuration(self) -> list[str]:
        problems: list[str] = []
        if self.mode not in {"offline", "api"}:
            problems.append(f"source.mode must be 'offline' or 'api', got '{self.mode}'")
        if not self.manifest_path:
            problems.append("source.selection_manifest is required")
        elif not Path(self.manifest_path).is_file():
            problems.append(f"selection manifest not found: {self.manifest_path}")
        if self.mode == "offline":
            if not self.data_dir:
                problems.append("source.data_dir is required in offline mode")
            elif not (Path(self.data_dir) / "tasks").is_dir():
                problems.append(
                    f"data_dir does not look like an Asana export (missing tasks/): {self.data_dir}"
                )
        return problems

    def inspect(self) -> InspectionSummary:
        problems = self.validate_configuration()
        if problems:
            raise ConfigurationError("; ".join(problems))
        assert self.manifest_path is not None
        manifest = read_selection_manifest(self.manifest_path)
        warnings = list(self.warnings)
        for gid in manifest.duplicates:
            warnings.append(
                MigrationWarning(
                    code="duplicate_manifest_gid",
                    severity=Severity.MEDIUM,
                    message=f"GID {gid} appears more than once in the selection manifest",
                    record_id=gid,
                )
            )
        for line in manifest.invalid_lines:
            warnings.append(
                MigrationWarning(
                    code="invalid_manifest_line",
                    severity=Severity.MEDIUM,
                    message=f"manifest line {line} looks like a selection but is not a valid GID",
                )
            )
        missing = 0
        if self.mode == "offline":
            missing = sum(1 for gid in manifest.selected if self._load_offline(gid) is None)
            if missing:
                warnings.append(
                    MigrationWarning(
                        code="missing_export_data",
                        severity=Severity.HIGH,
                        message=(
                            f"{missing} selected GIDs have no data in the export; "
                            "re-run the export or remove them from the manifest"
                        ),
                    )
                )
        return InspectionSummary(
            scope=self.scope,
            record_counts={
                "selected_tasks": len(manifest.selected),
                "duplicate_gids": len(manifest.duplicates),
                "missing_export_data": missing,
            },
            warnings=warnings,
            unsupported_fields=list(self.unsupported_fields),
        )

    @property
    def scope(self) -> str:
        if self.workspace_gid:
            return f"workspace:{self.workspace_gid}"
        if self.data_dir:
            workspace = Path(self.data_dir) / "workspace.json"
            if workspace.is_file():
                return f"export:{Path(self.data_dir).name}"
        return "unknown"

    def iter_records(self) -> Iterator[CanonicalTask]:
        problems = self.validate_configuration()
        if problems:
            raise ConfigurationError("; ".join(problems))
        assert self.manifest_path is not None
        manifest = read_selection_manifest(self.manifest_path)
        for gid in manifest.selected:
            record = self.get_record(gid)
            if record is None:
                self.warnings.append(
                    MigrationWarning(
                        code="record_unavailable",
                        severity=Severity.HIGH,
                        message=f"selected GID {gid} could not be loaded from the source",
                        record_id=gid,
                    )
                )
                continue
            yield record

    def get_record(self, record_id: str) -> CanonicalTask | None:
        raw = self._load_raw(record_id)
        if raw is None:
            return None
        return to_canonical(
            raw,
            scope=self.scope,
            load_subtask=self._load_raw,
            data_dir=self.data_dir,
            unsupported=self.unsupported_fields,
        )

    def health_check(self) -> bool:
        if self.validate_configuration():
            return False
        if self.mode == "api":
            try:
                self._api_client().get_workspace_users(self.workspace_gid)
            except SourceError:
                return False
        return True

    # -- loading ------------------------------------------------------------

    def _load_raw(self, gid: str) -> dict[str, Any] | None:
        if self.mode == "offline":
            return self._load_offline(gid)
        return self._load_api(gid)

    def _load_offline(self, gid: str) -> dict[str, Any] | None:
        assert self.data_dir is not None
        path = Path(self.data_dir) / "tasks" / f"{gid}.json"
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SourceError(f"cannot read export file {path.name}: {exc}") from exc
        return data if isinstance(data, dict) else None

    def _api_client(self) -> AsanaApiClient:
        if self._api is None:
            self._api = AsanaApiClient()
        return self._api

    def _load_api(self, gid: str) -> dict[str, Any] | None:
        client = self._api_client()
        cache: dict[str, dict[str, Any]] = getattr(client, "_subtask_cache", {})
        if gid in cache:
            base = cache[gid]
            full = client.get_task(gid)
            full.update({k: v for k, v in base.items() if k not in full})
            return full
        try:
            return client.get_task(gid)
        except SourceError as exc:
            if "404" in str(exc):
                return None
            raise
