"""The source connector SDK.

A connector's only job is to read a source system faithfully: authenticate,
fetch, paginate, respect rate limits, convert errors into typed errors and
emit canonical records. Connectors never write to ALL WR - that is the
execution engine's job, always behind a validated plan.
"""

from __future__ import annotations

import abc
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from allwr_toolkit.core.models import (
    CanonicalAttachment,
    CanonicalTask,
    MigrationWarning,
    UnsupportedField,
)


class ConnectorMetadata(BaseModel):
    connector_id: str
    display_name: str
    source_product: str
    stability: str = Field(description="alpha, beta or stable.")
    supported_record_types: list[str]
    auth_modes: list[str]
    required_configuration: list[str]
    optional_configuration: list[str] = []
    known_limitations: list[str] = []
    rate_limit_strategy: str
    supports_attachments: bool = True
    supports_incremental: bool = False
    maintainer: str = "ALL WR Toolkit maintainers"


class ConnectorCapabilities(BaseModel):
    record_types: list[str]
    supports_offline_export: bool = False
    supports_live_api: bool = False
    supports_selection_manifest: bool = False
    preserves_source_ids: bool = True


class InspectionSummary(BaseModel):
    """What a source contains, before any plan is built."""

    scope: str
    record_counts: dict[str, int] = Field(default_factory=dict)
    users: list[str] = Field(default_factory=list)
    warnings: list[MigrationWarning] = Field(default_factory=list)
    unsupported_fields: list[UnsupportedField] = Field(default_factory=list)


class SourceConnector(abc.ABC):
    """Base class for source connectors.

    Third-party connectors can be distributed as separate packages exposing an
    ``allwr_toolkit.connectors`` entry point. Installing a third-party
    connector runs third-party code with your credentials and your data:
    install connectors only from sources you trust, exactly as you would any
    other dependency.
    """

    def __init__(self, source_config: dict[str, Any]) -> None:
        self.source_config = source_config

    @classmethod
    @abc.abstractmethod
    def metadata(cls) -> ConnectorMetadata:
        """Static description of the connector."""

    @classmethod
    @abc.abstractmethod
    def capabilities(cls) -> ConnectorCapabilities:
        """What this connector can and cannot do."""

    @abc.abstractmethod
    def validate_configuration(self) -> list[str]:
        """Return a list of human-readable configuration problems (empty = valid)."""

    @abc.abstractmethod
    def inspect(self) -> InspectionSummary:
        """Summarize the source without transferring record bodies."""

    @abc.abstractmethod
    def iter_records(self) -> Iterator[CanonicalTask]:
        """Yield the selected canonical records, one migration unit at a time."""

    @abc.abstractmethod
    def get_record(self, record_id: str) -> CanonicalTask | None:
        """Fetch a single record by source id."""

    def get_attachment(self, attachment: CanonicalAttachment, dest_dir: Path) -> Path | None:
        """Materialize one attachment into *dest_dir* and return its path.

        Default: only attachments already present in an offline export are
        available. Live connectors override this to download with streaming.
        """
        if attachment.local_path and Path(attachment.local_path).is_file():
            return Path(attachment.local_path)
        return None

    def estimate(self) -> dict[str, int]:
        """Rough record counts used for progress reporting."""
        return self.inspect().record_counts

    def health_check(self) -> bool:
        """True when the source is reachable with the current configuration."""
        return not self.validate_configuration()
