"""Contract tests for the ALL WR API client (all HTTP mocked with respx)."""

import json

import httpx
import pytest
import respx

from allwr_toolkit.api.allwr import AllwrClient, CommentPayload, TaskPayload
from allwr_toolkit.core.errors import ConfigurationError, TargetError
from tests.conftest import TARGET_BASE_URL


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    sleeps: list[float] = []
    monkeypatch.setattr(AllwrClient, "_sleep", lambda self, s: sleeps.append(s))
    return sleeps


def make_client(**kwargs: object) -> AllwrClient:
    return AllwrClient(TARGET_BASE_URL, api_key="wrk_synthetic_test_key", **kwargs)  # type: ignore[arg-type]


def test_requires_base_url_and_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALLWR_TOOLKIT_ALLWR_API_KEY", raising=False)
    with pytest.raises(ConfigurationError, match="base_url"):
        AllwrClient("")
    with pytest.raises(ConfigurationError, match="API key"):
        AllwrClient(TARGET_BASE_URL)


@respx.mock
def test_create_task_payload_shape_and_headers() -> None:
    route = respx.post(f"{TARGET_BASE_URL}/tasks").mock(
        return_value=httpx.Response(201, json={"ok": True, "task": {"id": 900}})
    )
    with make_client() as client:
        result = client.create_task(
            TaskPayload(
                project_id=42,
                title="Redesign the landing page",
                import_source="asana",
                external_ref="1200000000000001",
                import_batch_id=7,
                watchers=[11],
            )
        )
    assert result.id == 900 and result.replayed is False
    request = route.calls[0].request
    body = json.loads(request.content)
    assert body["external_ref"] == "1200000000000001"
    assert body["import_source"] == "asana"
    assert body["import_batch_id"] == 7
    assert "completed_at" not in body  # exclude_none
    assert request.headers["Authorization"].startswith("Bearer ")
    assert request.headers["User-Agent"].startswith("allwr-toolkit/")
    assert request.headers["X-Correlation-Id"]


@respx.mock
def test_replayed_response_detected() -> None:
    respx.post(f"{TARGET_BASE_URL}/tasks").mock(
        return_value=httpx.Response(200, json={"ok": True, "replayed": True, "task": {"id": 900}})
    )
    with make_client() as client:
        result = client.create_task(TaskPayload(project_id=1, title="x"))
    assert result.replayed is True


@respx.mock
def test_rate_limit_honors_retry_after(no_sleep: list[float]) -> None:
    route = respx.post(f"{TARGET_BASE_URL}/tasks")
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "7"}),
        httpx.Response(201, json={"ok": True, "task": {"id": 1}}),
    ]
    with make_client() as client:
        result = client.create_task(TaskPayload(project_id=1, title="x"))
    assert result.id == 1
    assert 7.0 in no_sleep  # Retry-After respected
    assert route.call_count == 2


@respx.mock
def test_transient_5xx_retried_with_backoff(no_sleep: list[float]) -> None:
    route = respx.post(f"{TARGET_BASE_URL}/tasks")
    route.side_effect = [
        httpx.Response(503),
        httpx.Response(201, json={"ok": True, "task": {"id": 2}}),
    ]
    with make_client() as client:
        result = client.create_task(TaskPayload(project_id=1, title="x"))
    assert result.id == 2
    assert no_sleep, "backoff sleep expected before the retry"


@respx.mock
def test_permanent_4xx_not_retried() -> None:
    route = respx.post(f"{TARGET_BASE_URL}/tasks").mock(
        return_value=httpx.Response(
            422, json={"ok": False, "error": "invalid_import_user", "message": "user 99"}
        )
    )
    with make_client() as client, pytest.raises(TargetError) as excinfo:
        client.create_task(TaskPayload(project_id=1, title="x"))
    assert route.call_count == 1  # no blind retry of a permanent failure
    assert excinfo.value.code == "invalid_import_user"
    assert excinfo.value.status_code == 422


@respx.mock
def test_add_comment_carries_idempotency_key() -> None:
    route = respx.post(f"{TARGET_BASE_URL}/tasks/900/comments").mock(
        return_value=httpx.Response(201, json={"ok": True, "comment": {"id": 5}})
    )
    with make_client() as client:
        client.add_comment(
            900,
            CommentPayload(
                body_html="<p>hello</p>",
                client_request_id="asana-comment-1200000000000501",
                legacy_author_name="Former Employee",
            ),
        )
    body = json.loads(route.calls[0].request.content)
    assert body["client_request_id"] == "asana-comment-1200000000000501"
    assert body["legacy_author_name"] == "Former Employee"
    assert "author_user_id" not in body


@respx.mock
def test_upload_attachment_streams_multipart(tmp_path) -> None:  # type: ignore[no-untyped-def]
    file_path = tmp_path / "wireframe.txt"
    file_path.write_text("synthetic content", encoding="utf-8")
    route = respx.post(f"{TARGET_BASE_URL}/attachments/upload").mock(
        return_value=httpx.Response(201, json={"ok": True})
    )
    with make_client() as client:
        client.upload_attachment(
            900, file_path, file_name="wireframe.txt", client_request_id="asana-att-1"
        )
    content_type = route.calls[0].request.headers["Content-Type"]
    assert content_type.startswith("multipart/form-data")
    assert b"synthetic content" in route.calls[0].request.content


@respx.mock
def test_error_messages_are_redacted() -> None:
    fake_key = "wrk_" + "secret1234"  # concatenated so the publication audit never matches
    respx.post(f"{TARGET_BASE_URL}/tasks").mock(
        return_value=httpx.Response(
            400,
            json={"ok": False, "error": "bad", "message": f"leaked {fake_key} here"},
        )
    )
    with make_client() as client, pytest.raises(TargetError) as excinfo:
        client.create_task(TaskPayload(project_id=1, title="x"))
    assert fake_key not in str(excinfo.value)
