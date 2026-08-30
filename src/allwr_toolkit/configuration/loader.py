"""Load and validate migration configuration files.

Routine migrations are driven entirely by configuration - nobody should have
to edit Python to run one. Configuration never contains secrets: credentials
come from environment variables.
"""

from __future__ import annotations

import hashlib
import tomllib
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from allwr_toolkit.core.errors import ConfigurationError


class TargetConfig(BaseModel):
    """Where the migration writes. There is deliberately no default base_url:
    migrating into a production tenant must always be an explicit decision."""

    model_config = ConfigDict(extra="forbid")

    base_url: str = Field(description="ALL WR Tasks API base URL, explicit on purpose.")
    project_id: int = Field(description="Target ALL WR project id.")
    section_open: int | None = Field(default=None, description="Section id for open tasks.")
    section_done: int | None = Field(default=None, description="Section id for completed tasks.")
    import_source: str | None = Field(
        default=None, description="Import source label; defaults to the connector id."
    )
    import_batch_id: int | None = Field(default=None, description="Optional import batch id.")
    environment: Literal["sandbox", "production"] = Field(
        default="sandbox",
        description="Declared environment; shown in the apply confirmation.",
    )

    @field_validator("base_url")
    @classmethod
    def _https_only(cls, value: str) -> str:
        if not value.startswith(("https://", "http://localhost", "http://127.0.0.1")):
            raise ValueError("base_url must use https (plain http only for localhost)")
        return value.rstrip("/")


class UserMapEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str | None = None
    email: str | None = None
    name: str | None = None
    target_user_id: int

    @field_validator("target_user_id")
    @classmethod
    def _positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("target_user_id must be a positive id")
        return value


class MappingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    users: list[UserMapEntry] = Field(default_factory=list)
    statuses: dict[str, str] = Field(default_factory=dict)
    priorities: dict[str, str] = Field(default_factory=dict)
    default_status: str | None = None
    default_priority: str | None = None
    on_unknown_user: Literal["null", "skip", "fail"] = Field(
        default="null",
        description=(
            "What to do when a source user has no target mapping: 'null' imports the "
            "record unassigned and preserves the original author as legacy metadata, "
            "'skip' excludes the record, 'fail' aborts planning."
        ),
    )


class OptionsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include_completed: bool = True
    include_attachments: bool = True
    preserve_source_ids: bool = True
    stop_on_data_loss: bool = Field(
        default=False,
        description="Escalate every unsupported field to a high severity (blocking) warning.",
    )
    max_attachment_mb: int = 50
    accepted_warnings: list[str] = Field(
        default_factory=list,
        description="Warning codes explicitly accepted; only these unblock apply.",
    )


class MigrationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connector: str = Field(description="Source connector id, e.g. 'asana' or 'freshdesk'.")
    source: dict[str, Any] = Field(
        default_factory=dict, description="Connector-specific source settings."
    )
    target: TargetConfig
    mapping: MappingConfig = Field(default_factory=MappingConfig)
    options: OptionsConfig = Field(default_factory=OptionsConfig)

    @property
    def import_source(self) -> str:
        return self.target.import_source or self.connector


def load_config(path: str | Path) -> MigrationConfig:
    """Load a migration configuration from a YAML or TOML file."""
    file = Path(path)
    if not file.is_file():
        raise ConfigurationError(f"configuration file not found: {file}")
    try:
        if file.suffix.lower() == ".toml":
            data = tomllib.loads(file.read_text(encoding="utf-8"))
        elif file.suffix.lower() in {".yaml", ".yml"}:
            data = yaml.safe_load(file.read_text(encoding="utf-8"))
        else:
            raise ConfigurationError(
                f"unsupported configuration format '{file.suffix}': use .yaml, .yml or .toml"
            )
    except (yaml.YAMLError, tomllib.TOMLDecodeError) as exc:
        raise ConfigurationError(f"cannot parse {file.name}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigurationError(f"{file.name} must contain a mapping at the top level")
    try:
        return MigrationConfig.model_validate(data)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()
        )
        raise ConfigurationError(f"invalid configuration in {file.name}: {details}") from exc


def config_hash(config: MigrationConfig) -> str:
    """Stable SHA-256 of the configuration content (no secrets are ever inside)."""
    canonical = config.model_dump_json(exclude_none=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
