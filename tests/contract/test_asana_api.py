"""Contract tests for the Asana API client (all HTTP mocked)."""

import httpx
import pytest
import respx

from allwr_toolkit.connectors.asana.api import API_BASE, AsanaApiClient
from allwr_toolkit.core.errors import ConfigurationError, SourceError


@pytest.fixture(autouse=True)
def token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLWR_TOOLKIT_ASANA_TOKEN", "1/1200000000000001:synthetic")  # audit-ok
    monkeypatch.setattr(AsanaApiClient, "_sleep", lambda self, s: None)


def test_requires_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALLWR_TOOLKIT_ASANA_TOKEN")
    with pytest.raises(ConfigurationError, match="Asana token"):
        AsanaApiClient()


@respx.mock
def test_pagination_follows_offsets() -> None:
    route = respx.get(f"{API_BASE}/tasks/1/stories")
    route.side_effect = [
        httpx.Response(
            200,
            json={"data": [{"gid": "1"}], "next_page": {"offset": "abc"}},
        ),
        httpx.Response(200, json={"data": [{"gid": "2"}], "next_page": None}),
    ]
    client = AsanaApiClient()
    items = client.paginate("/tasks/1/stories", {"opt_fields": "gid"})
    assert [i["gid"] for i in items] == ["1", "2"]
    assert "offset=abc" in str(route.calls[1].request.url)


@respx.mock
def test_rate_limited_then_success() -> None:
    route = respx.get(f"{API_BASE}/users")
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "3"}),
        httpx.Response(200, json={"data": []}),
    ]
    client = AsanaApiClient()
    assert client.paginate("/users", {}) == []
    assert route.call_count == 2


@respx.mock
def test_client_error_raises_source_error() -> None:
    respx.get(f"{API_BASE}/tasks/9").mock(return_value=httpx.Response(404, json={}))
    client = AsanaApiClient()
    with pytest.raises(SourceError, match="404"):
        client.get_task("9")


@respx.mock
def test_get_task_assembles_stories_attachments_subtasks() -> None:
    respx.get(f"{API_BASE}/tasks/7").mock(
        return_value=httpx.Response(
            200, json={"data": {"gid": "7", "name": "A task", "num_subtasks": 1}}
        )
    )
    respx.get(f"{API_BASE}/tasks/7/stories").mock(
        return_value=httpx.Response(200, json={"data": [{"gid": "s1", "type": "comment"}]})
    )
    respx.get(f"{API_BASE}/attachments").mock(
        return_value=httpx.Response(200, json={"data": [{"gid": "a1", "name": "f"}]})
    )
    respx.get(f"{API_BASE}/tasks/7/subtasks").mock(
        return_value=httpx.Response(200, json={"data": [{"gid": "8", "name": "sub"}]})
    )
    client = AsanaApiClient()
    task = client.get_task("7")
    assert task["stories"][0]["gid"] == "s1"
    assert task["attachments"][0]["gid"] == "a1"
    assert task["subtask_gids"] == ["8"]
