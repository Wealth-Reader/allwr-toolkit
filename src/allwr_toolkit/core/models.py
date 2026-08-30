"""Canonical migration model.

Source connectors never talk to ALL WR directly: they translate the source
system into these canonical records, and the execution engine translates the
canonical records into ALL WR API operations. The canonical model preserves
enough source information for auditing, re-execution, deduplication and
troubleshooting.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Severity(StrEnum):
    INFO = "info"
    MEDIUM = "medium"
    HIGH = "high"


class SourceRef(BaseModel):
    """Stable identity of a record in its source system."""

    model_config = ConfigDict(frozen=True)

    system: str = Field(description="Source system id, e.g. 'asana' or 'freshdesk'.")
    scope: str = Field(description="Workspace gid, account domain or equivalent boundary.")
    record_type: str = Field(description="Source record type, e.g. 'task' or 'ticket'.")
    record_id: str = Field(description="Source record id (Asana gid, Freshdesk ticket id...).")
    url: str | None = Field(default=None, description="Permalink in the source system.")

    @property
    def external_ref(self) -> str:
        """The value stored in ALL WR as the stable external reference."""
        return self.record_id


class CanonicalUser(BaseModel):
    source_id: str | None = None
    name: str | None = None
    email: str | None = None


class CanonicalAttachment(BaseModel):
    source_id: str
    name: str
    size_bytes: int | None = None
    content_type: str | None = None
    created_at: datetime | None = None
    download_url: str | None = None
    local_path: str | None = Field(
        default=None, description="Path inside an offline export, when already downloaded."
    )
    external_url: str | None = Field(
        default=None, description="Set when the file is hosted outside the source (link only)."
    )
    checksum_sha256: str | None = None

    @property
    def is_external_link(self) -> bool:
        return self.external_url is not None and self.local_path is None


class CanonicalComment(BaseModel):
    source_id: str
    author: CanonicalUser | None = None
    created_at: datetime | None = None
    body_html: str | None = None
    body_text: str | None = None
    is_private: bool = Field(
        default=True,
        description="Private notes must never become customer-visible in the target.",
    )


class CanonicalChecklistItem(BaseModel):
    """A title-only subtask that becomes a checklist entry in the target."""

    source_id: str | None = None
    title: str
    completed: bool = False
    assignee: CanonicalUser | None = None
    due_date: str | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None
    created_by: CanonicalUser | None = None


class CustomFieldValue(BaseModel):
    name: str
    value: str | None = None
    field_type: str | None = None


class CanonicalSection(BaseModel):
    source_id: str
    name: str


class CanonicalProject(BaseModel):
    source_id: str
    name: str
    archived: bool = False
    sections: list[CanonicalSection] = Field(default_factory=list)


class CanonicalCompany(BaseModel):
    source_id: str
    name: str
    domains: list[str] = Field(default_factory=list)


class CanonicalContact(BaseModel):
    source_id: str
    name: str | None = None
    email: str | None = None
    company_id: str | None = None
    deleted: bool = False


class CanonicalTask(BaseModel):
    """A task-like unit of migration (Asana task, or a converted ticket)."""

    source: SourceRef
    title: str
    description_html: str | None = None
    completed: bool = False
    created_at: datetime | None = None
    modified_at: datetime | None = None
    completed_at: datetime | None = None
    due_date: str | None = None
    start_date: str | None = None
    assignee: CanonicalUser | None = None
    created_by: CanonicalUser | None = None
    completed_by: CanonicalUser | None = None
    projects: list[str] = Field(
        default_factory=list, description="Names of source projects this task belongs to."
    )
    tags: list[str] = Field(default_factory=list)
    custom_fields: list[CustomFieldValue] = Field(default_factory=list)
    followers: list[CanonicalUser] = Field(default_factory=list)
    comments: list[CanonicalComment] = Field(default_factory=list)
    attachments: list[CanonicalAttachment] = Field(default_factory=list)
    checklist: list[CanonicalChecklistItem] = Field(default_factory=list)
    subtasks: list[CanonicalTask] = Field(
        default_factory=list,
        description="Rich subtasks migrated as full tasks linked via subtask_of.",
    )
    source_metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Extra source facts preserved verbatim for auditing (no secrets).",
    )


class ConversationKind(StrEnum):
    PUBLIC_REPLY = "public_reply"
    PRIVATE_NOTE = "private_note"


class CanonicalConversation(BaseModel):
    source_id: str
    kind: ConversationKind
    author: CanonicalUser | None = None
    created_at: datetime | None = None
    body_html: str | None = None
    body_text: str | None = None
    attachments: list[CanonicalAttachment] = Field(default_factory=list)

    @property
    def is_private(self) -> bool:
        return self.kind is ConversationKind.PRIVATE_NOTE


class CanonicalTicket(BaseModel):
    """A helpdesk ticket (Freshdesk) before conversion into a task unit."""

    source: SourceRef
    subject: str
    description_html: str | None = None
    status: str | None = None
    priority: str | None = None
    ticket_type: str | None = None
    tags: list[str] = Field(default_factory=list)
    requester: CanonicalContact | None = None
    company: CanonicalCompany | None = None
    assignee: CanonicalUser | None = None
    cc_emails: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    closed: bool = False
    conversations: list[CanonicalConversation] = Field(default_factory=list)
    attachments: list[CanonicalAttachment] = Field(default_factory=list)
    source_metadata: dict[str, Any] = Field(default_factory=dict)


class UnsupportedField(BaseModel):
    """A source field the target cannot represent - reported, never dropped silently."""

    record_id: str
    field: str
    reason: str
    sample_value: str | None = None


class MigrationWarning(BaseModel):
    code: str
    severity: Severity = Severity.INFO
    message: str
    record_id: str | None = None


class MappingDecision(BaseModel):
    kind: str = Field(description="What was mapped: user, status, priority, section...")
    source_value: str
    target_value: str | None = None
    reason: str | None = None
