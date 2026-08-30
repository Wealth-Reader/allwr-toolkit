"""Contract tests for the Freshdesk connector (all HTTP mocked)."""

from pathlib import Path

import httpx
import pytest
import respx

from allwr_toolkit.connectors.freshdesk.client import FreshdeskClient
from allwr_toolkit.connectors.freshdesk.connector import FreshdeskConnector
from allwr_toolkit.core.errors import ConfigurationError, SourceError

BASE = "https://example.freshdesk.com/api/v2"

TICKET = {
    "id": 3001,
    "subject": "Cannot log in",
    "description": "<div>I cannot log in<script>x()</script></div>",
    "status": 5,
    "priority": 3,
    "type": "Incident",
    "tags": ["login"],
    "requester_id": 7001,
    "responder_id": 8001,
    "company_id": 9001,
    "created_at": "2024-01-10T08:00:00Z",
    "updated_at": "2024-01-12T09:00:00Z",
    "cc_emails": ["cc.person@example.com"],
    "attachments": [
        {
            "id": 4001,
            "name": "screenshot.png",
            "size": 10,
            "content_type": "image/png",
            "attachment_url": "https://files.example.com/screenshot.png",
        }
    ],
}
CONVERSATIONS = [
    {
        "id": 5001,
        "private": False,
        "user_id": 8001,
        "body": "<div>We are looking into it</div>",
        "body_text": "We are looking into it",
        "created_at": "2024-01-10T09:00:00Z",
    },
    {
        "id": 5002,
        "private": True,
        "user_id": 8001,
        "body": "<div>Internal note: reset their session</div>",
        "body_text": "Internal note: reset their session",
        "created_at": "2024-01-10T10:00:00Z",
    },
]
AGENTS = [{"id": 8001, "contact": {"name": "Agent Doe", "email": "agent@example.com"}}]
CONTACTS = [{"id": 7001, "name": "Customer Roe", "email": "customer@example.com"}]


@pytest.fixture(autouse=True)
def key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLWR_TOOLKIT_FRESHDESK_API_KEY", "synthetic_key")
    monkeypatch.setattr(FreshdeskClient, "_sleep", lambda self, s: None)


def mock_account() -> None:
    respx.get(f"{BASE}/tickets").mock(return_value=httpx.Response(200, json=[TICKET]))
    respx.get(f"{BASE}/tickets/3001/conversations").mock(
        return_value=httpx.Response(200, json=CONVERSATIONS)
    )
    respx.get(f"{BASE}/agents").mock(return_value=httpx.Response(200, json=AGENTS))
    respx.get(f"{BASE}/contacts").mock(return_value=httpx.Response(200, json=CONTACTS))


def test_domain_required() -> None:
    with pytest.raises(ConfigurationError, match="domain"):
        FreshdeskClient("")
    assert FreshdeskConnector({}).validate_configuration()


@respx.mock
def test_auth_uses_api_key_basic_auth() -> None:
    route = respx.get(f"{BASE}/agents").mock(return_value=httpx.Response(200, json=[]))
    FreshdeskClient("example").list_agents()
    assert route.calls[0].request.headers["Authorization"].startswith("Basic ")


@respx.mock
def test_pagination_stops_on_short_page() -> None:
    route = respx.get(f"{BASE}/contacts")
    route.side_effect = [
        httpx.Response(200, json=[{"id": i} for i in range(100)]),
        httpx.Response(200, json=[{"id": 100}]),
    ]
    items = FreshdeskClient("example").list_contacts()
    assert len(items) == 101
    assert route.call_count == 2


@respx.mock
def test_ticket_to_canonical_preserves_privacy_and_identity() -> None:
    mock_account()
    connector = FreshdeskConnector({"domain": "example"})
    records = list(connector.iter_records())
    assert len(records) == 1
    task = records[0]
    # Source identity preserved.
    assert task.source.record_id == "3001"
    assert task.source.url == "https://example.freshdesk.com/a/tickets/3001"
    # Closed ticket -> completed.
    assert task.completed is True
    # Sanitized description.
    assert task.description_html is not None and "<script" not in task.description_html
    # Conversations: the private note stays private.
    by_id = {c.source_id: c for c in task.comments}
    assert by_id["5001"].is_private is False
    assert by_id["5002"].is_private is True
    # CC emails are reported as unsupported, not silently dropped.
    assert any(f.field == "cc_emails" for f in connector.unsupported_fields)
    # Attachment metadata kept for streaming download later.
    assert task.attachments[0].download_url is not None


@respx.mock
def test_import_path_never_calls_freshdesk_write_endpoints() -> None:
    """Reading tickets must be GET-only: no replies, no notes, no notifications."""
    mock_account()
    connector = FreshdeskConnector({"domain": "example"})
    list(connector.iter_records())
    assert all(call.request.method == "GET" for call in respx.calls)


@respx.mock
def test_attachment_download_streams_and_checks_size(tmp_path: Path) -> None:
    respx.get("https://files.example.com/screenshot.png").mock(
        return_value=httpx.Response(200, content=b"0123456789")
    )
    client = FreshdeskClient("example")
    dest = client.download_attachment(
        "https://files.example.com/screenshot.png",
        tmp_path / "screenshot.png",
        expected_size=10,
    )
    assert dest.read_bytes() == b"0123456789"


@respx.mock
def test_attachment_size_mismatch_rejected(tmp_path: Path) -> None:
    respx.get("https://files.example.com/screenshot.png").mock(
        return_value=httpx.Response(200, content=b"short")
    )
    client = FreshdeskClient("example")
    with pytest.raises(SourceError, match="size mismatch"):
        client.download_attachment(
            "https://files.example.com/screenshot.png",
            tmp_path / "screenshot.png",
            expected_size=10,
        )
    assert not (tmp_path / "screenshot.png").exists()
