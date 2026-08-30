"""Freshdesk connector: tickets, conversations, contacts, companies.

Guarantees that matter here:

- private notes stay private (they map to internal-only comments and are
  flagged ``is_private`` in the canonical model);
- importing never emails requesters - the import path only writes to ALL WR;
- authors that cannot be mapped are preserved as explicit legacy metadata;
- source ticket ids and URLs are preserved as stable external references.
"""

from __future__ import annotations

import html
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from allwr_toolkit.connectors.base import (
    ConnectorCapabilities,
    ConnectorMetadata,
    InspectionSummary,
    SourceConnector,
)
from allwr_toolkit.connectors.freshdesk.client import FreshdeskClient
from allwr_toolkit.core.errors import ConfigurationError, SourceError
from allwr_toolkit.core.models import (
    CanonicalAttachment,
    CanonicalComment,
    CanonicalTask,
    CanonicalUser,
    MigrationWarning,
    SourceRef,
    UnsupportedField,
)
from allwr_toolkit.security import sanitize_html

CONNECTOR_VERSION = "0.1.0"
SYSTEM = "freshdesk"

# Freshdesk numeric codes -> human labels.
STATUS_LABELS = {2: "open", 3: "pending", 4: "resolved", 5: "closed"}
PRIORITY_LABELS = {1: "low", 2: "medium", 3: "high", 4: "urgent"}
_CLOSED_STATUSES = {4, 5}

_UNSUPPORTED_TICKET_FIELDS = {
    "cc_emails": "CC recipients cannot be represented on the target task",
    "custom_fields": "Freshdesk custom fields are preserved as metadata only",
}


class FreshdeskConnector(SourceConnector):
    def __init__(self, source_config: dict[str, Any]) -> None:
        super().__init__(source_config)
        self.domain: str = str(source_config.get("domain", ""))
        self.include_closed: bool = bool(source_config.get("include_closed", True))
        self._client: FreshdeskClient | None = None
        self._agents: dict[int, dict[str, Any]] | None = None
        self._contacts: dict[int, dict[str, Any]] | None = None
        self.unsupported_fields: list[UnsupportedField] = []
        self.warnings: list[MigrationWarning] = []

    # -- SDK ----------------------------------------------------------------

    @classmethod
    def metadata(cls) -> ConnectorMetadata:
        return ConnectorMetadata(
            connector_id="freshdesk",
            display_name="Freshdesk Importer",
            source_product="Freshdesk",
            stability="beta",
            supported_record_types=[
                "ticket",
                "conversation",
                "private_note",
                "contact",
                "company",
                "agent",
                "attachment",
                "tag",
            ],
            auth_modes=["api_key"],
            required_configuration=["domain"],
            optional_configuration=["include_closed"],
            known_limitations=[
                "CC recipients are reported as unsupported fields.",
                "Custom fields are preserved as source metadata only.",
                "Author identity that cannot be mapped is preserved as legacy "
                "metadata, never impersonated.",
                "The import never sends email to requesters.",
            ],
            rate_limit_strategy="Honors Retry-After on HTTP 429; paged at 100 per page.",
            supports_attachments=True,
            supports_incremental=False,
        )

    @classmethod
    def capabilities(cls) -> ConnectorCapabilities:
        return ConnectorCapabilities(
            record_types=["ticket"],
            supports_offline_export=False,
            supports_live_api=True,
            supports_selection_manifest=False,
            preserves_source_ids=True,
        )

    def validate_configuration(self) -> list[str]:
        problems: list[str] = []
        if not self.domain:
            problems.append("source.domain is required (e.g. 'yourcompany')")
        return problems

    @property
    def scope(self) -> str:
        return f"domain:{self.domain or 'unknown'}"

    def inspect(self) -> InspectionSummary:
        problems = self.validate_configuration()
        if problems:
            raise ConfigurationError("; ".join(problems))
        client = self.client()
        tickets = client.list_tickets(include_closed=self.include_closed)
        contacts = client.list_contacts()
        companies = client.list_companies()
        return InspectionSummary(
            scope=self.scope,
            record_counts={
                "tickets": len(tickets),
                "contacts": len(contacts),
                "companies": len(companies),
            },
            warnings=list(self.warnings),
            unsupported_fields=list(self.unsupported_fields),
        )

    def iter_records(self) -> Iterator[CanonicalTask]:
        problems = self.validate_configuration()
        if problems:
            raise ConfigurationError("; ".join(problems))
        client = self.client()
        for raw in client.list_tickets(include_closed=self.include_closed):
            status = int(raw.get("status") or 0)
            if not self.include_closed and status in _CLOSED_STATUSES:
                continue
            yield self._to_task(raw)

    def get_record(self, record_id: str) -> CanonicalTask | None:
        try:
            raw = self.client().get_ticket(record_id)
        except SourceError as exc:
            if exc.code == "freshdesk_not_found":
                return None
            raise
        return self._to_task(raw) if raw else None

    def get_attachment(self, attachment: CanonicalAttachment, dest_dir: Path) -> Path | None:
        if not attachment.download_url:
            return None
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{attachment.source_id}_{attachment.name}"[:200]
        return self.client().download_attachment(
            attachment.download_url, dest, expected_size=attachment.size_bytes
        )

    def health_check(self) -> bool:
        if self.validate_configuration():
            return False
        try:
            self.client().get_json("/agents/me")
        except SourceError:
            return False
        return True

    # -- conversion ----------------------------------------------------------

    def client(self) -> FreshdeskClient:
        if self._client is None:
            self._client = FreshdeskClient(self.domain)
        return self._client

    def _agent(self, agent_id: Any) -> CanonicalUser | None:
        if not agent_id:
            return None
        if self._agents is None:
            self._agents = {a["id"]: a for a in self.client().list_agents() if "id" in a}
        raw = self._agents.get(int(agent_id))
        if raw is None:
            # Deleted or unavailable agent: tolerated, preserved by id.
            return CanonicalUser(source_id=str(agent_id))
        contact = raw.get("contact", {})
        return CanonicalUser(
            source_id=str(agent_id), name=contact.get("name"), email=contact.get("email")
        )

    def _contact(self, contact_id: Any) -> CanonicalUser | None:
        if not contact_id:
            return None
        if self._contacts is None:
            self._contacts = {c["id"]: c for c in self.client().list_contacts() if "id" in c}
        raw = self._contacts.get(int(contact_id))
        if raw is None:
            return CanonicalUser(source_id=str(contact_id))
        return CanonicalUser(
            source_id=str(contact_id), name=raw.get("name"), email=raw.get("email")
        )

    def _attachments(self, raw_list: list[dict[str, Any]]) -> list[CanonicalAttachment]:
        return [
            CanonicalAttachment(
                source_id=str(raw.get("id")),
                name=raw.get("name") or "attachment",
                size_bytes=raw.get("size"),
                content_type=raw.get("content_type"),
                download_url=raw.get("attachment_url"),
            )
            for raw in raw_list
        ]

    def _to_task(self, raw: dict[str, Any]) -> CanonicalTask:
        from allwr_toolkit.connectors.asana.convert import parse_dt  # shared helper

        ticket_id = str(raw["id"])
        status = int(raw.get("status") or 0)
        status_label = STATUS_LABELS.get(status, str(status))
        priority_label = PRIORITY_LABELS.get(int(raw.get("priority") or 0), None)
        url = f"https://{self.client().domain}/a/tickets/{ticket_id}"
        for field, reason in _UNSUPPORTED_TICKET_FIELDS.items():
            if raw.get(field):
                self.unsupported_fields.append(
                    UnsupportedField(record_id=ticket_id, field=field, reason=reason)
                )
        requester = self._contact(raw.get("requester_id"))
        description = sanitize_html(raw.get("description") or "")
        requester_label = None
        if requester and (requester.name or requester.email):
            requester_label = requester.name or requester.email
        footer_bits = [
            f'Imported from Freshdesk ticket <a href="{html.escape(url)}">#'
            f"{html.escape(ticket_id)}</a>"
        ]
        if requester_label:
            footer_bits.append(f"Requester: {html.escape(requester_label)}")
        footer_bits.append(f"Status: {html.escape(status_label)}")
        if priority_label:
            footer_bits.append(f"Priority: {html.escape(priority_label)}")
        comments: list[CanonicalComment] = []
        for conversation in self.client().list_conversations(ticket_id):
            body = sanitize_html(conversation.get("body") or "")
            body_text = conversation.get("body_text") or None
            if not body and not (body_text or "").strip():
                continue
            author = self._agent(conversation.get("user_id")) or self._contact(
                conversation.get("user_id")
            )
            comments.append(
                CanonicalComment(
                    source_id=str(conversation.get("id")),
                    author=author,
                    created_at=parse_dt(conversation.get("created_at")),
                    body_html=body or None,
                    body_text=body_text,
                    # Freshdesk: private == internal note. It must stay private.
                    is_private=bool(conversation.get("private", False)),
                )
            )
        return CanonicalTask(
            source=SourceRef(
                system=SYSTEM,
                scope=self.scope,
                record_type="ticket",
                record_id=ticket_id,
                url=url,
            ),
            title=(raw.get("subject") or f"Ticket #{ticket_id}").strip(),
            description_html=(
                description + "\n<hr /><p><em>" + " - ".join(footer_bits) + "</em></p>"
            ),
            completed=status in _CLOSED_STATUSES,
            created_at=parse_dt(raw.get("created_at")),
            modified_at=parse_dt(raw.get("updated_at")),
            completed_at=parse_dt(raw.get("updated_at")) if status in _CLOSED_STATUSES else None,
            due_date=(raw.get("due_by") or "")[:10] or None,
            assignee=self._agent(raw.get("responder_id")),
            created_by=requester,
            tags=[t for t in raw.get("tags", []) if isinstance(t, str)],
            comments=comments,
            attachments=self._attachments(raw.get("attachments", [])),
            source_metadata={
                "freshdesk_status": status_label,
                "freshdesk_priority": priority_label,
                "freshdesk_type": raw.get("type"),
                "company_id": raw.get("company_id"),
                "custom_fields": raw.get("custom_fields") or {},
            },
        )


__all__ = ["CONNECTOR_VERSION", "PRIORITY_LABELS", "STATUS_LABELS", "FreshdeskConnector"]
