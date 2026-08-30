"""Typed HTTP client for the ALL WR Tasks import-mode API.

All access to the target API goes through this one client: authentication,
timeouts, retries with backoff and jitter, Retry-After handling, idempotency
keys, correlation ids, error normalization and redacted logging live here and
nowhere else.
"""

from __future__ import annotations

import logging
import os
import random
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel

from allwr_toolkit import USER_AGENT
from allwr_toolkit.core.errors import (
    ConfigurationError,
    PermanentError,
    RateLimitedError,
    TargetError,
    TransientError,
)
from allwr_toolkit.security import install_redaction, redact

logger = logging.getLogger(__name__)
install_redaction(logger)

API_KEY_ENV = "ALLWR_TOOLKIT_ALLWR_API_KEY"
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class CreateResult(BaseModel):
    """Outcome of a write; ``replayed`` means the server had it already."""

    id: int | None = None
    replayed: bool = False
    raw: dict[str, Any] = {}


class TaskPayload(BaseModel):
    project_id: int
    title: str
    section_id: int | None = None
    description_html: str | None = None
    assigned_user_id: int | None = None
    created_by_user_id: int | None = None
    start_date: str | None = None
    due_date: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    completed_at: str | None = None
    import_source: str | None = None
    external_ref: str | None = None
    import_batch_id: int | None = None
    watchers: list[int] = []
    subtasks: list[dict[str, Any]] = []


class CommentPayload(BaseModel):
    body_html: str
    comment_type: str = "internal"
    created_at: str | None = None
    author_user_id: int | None = None
    legacy_author_name: str | None = None
    client_request_id: str
    import_batch_id: int | None = None


class AllwrClient:
    """Client for one ALL WR Tasks API base URL.

    The base URL is a required argument on purpose: the toolkit never assumes
    a production tenant as an implicit default.
    """

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | None = None,
        timeout: float = 60.0,
        max_retries: int = 5,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not base_url:
            raise ConfigurationError("AllwrClient requires an explicit base_url")
        key = api_key or os.environ.get(API_KEY_ENV, "")
        if not key:
            raise ConfigurationError(
                f"no ALL WR API key: set the {API_KEY_ENV} environment variable"
            )
        self.base_url = base_url.rstrip("/")
        self._max_retries = max_retries
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            transport=transport,
            headers={
                "Authorization": f"Bearer {key}",
                "User-Agent": USER_AGENT,
            },
        )
        self.requests_sent = 0

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> AllwrClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- transport ---------------------------------------------------------

    def _sleep(self, seconds: float) -> None:  # patchable in tests
        time.sleep(seconds)

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        correlation_id = uuid.uuid4().hex
        last_error: Exception | None = None
        for attempt in range(self._max_retries):
            if attempt:
                # Jitter is not cryptographic.
                backoff = min(30.0, (2.0**attempt) + random.uniform(0, 1))  # noqa: S311 # nosec B311
                self._sleep(backoff)
            try:
                response = self._client.request(
                    method,
                    path,
                    json=json_body,
                    files=files,
                    data=data,
                    headers={"X-Correlation-Id": correlation_id},
                )
                self.requests_sent += 1
            except httpx.HTTPError as exc:
                last_error = TransientError(f"network error calling {path}: {exc}")
                logger.warning("network error on %s (attempt %d)", path, attempt + 1)
                continue
            if response.status_code == 429:
                retry_after = _parse_retry_after(response.headers.get("Retry-After"))
                last_error = RateLimitedError(f"rate limited on {path}", retry_after=retry_after)
                self._sleep(retry_after if retry_after is not None else 5.0)
                continue
            if response.status_code in _RETRYABLE_STATUS:
                last_error = TransientError(
                    f"transient HTTP {response.status_code} on {path}",
                    code=f"http_{response.status_code}",
                )
                continue
            payload = _json_or_error(response, path)
            if response.status_code >= 400:
                raise TargetError(
                    redact(str(payload.get("message") or payload.get("error") or path)),
                    code=str(payload.get("error") or f"http_{response.status_code}"),
                    status_code=response.status_code,
                )
            return payload
        raise last_error if last_error else PermanentError(f"retries exhausted on {path}")

    # -- operations --------------------------------------------------------

    def ping(self) -> bool:
        """Cheap read used by doctor/health checks."""
        self._request("GET", "/users")
        return True

    def list_users(self) -> list[dict[str, Any]]:
        payload = self._request("GET", "/users")
        users = payload.get("users", payload.get("data", []))
        return users if isinstance(users, list) else []

    def create_task(self, task: TaskPayload) -> CreateResult:
        payload = self._request("POST", "/tasks", json_body=task.model_dump(exclude_none=True))
        raw_task = payload.get("task") or {}
        return CreateResult(
            id=raw_task.get("id"), replayed=bool(payload.get("replayed")), raw=payload
        )

    def add_comment(self, task_id: int, comment: CommentPayload) -> CreateResult:
        payload = self._request(
            "POST",
            f"/tasks/{task_id}/comments",
            json_body=comment.model_dump(exclude_none=True),
        )
        raw_comment = payload.get("comment") or {}
        return CreateResult(
            id=raw_comment.get("id"), replayed=bool(payload.get("replayed")), raw=payload
        )

    def upload_attachment(
        self,
        task_id: int,
        file_path: str | Path,
        *,
        file_name: str,
        client_request_id: str,
        created_at: str | None = None,
    ) -> CreateResult:
        """Upload one attachment, streaming the file from disk."""
        fields: dict[str, Any] = {
            "task_id": str(task_id),
            "visibility": "internal",
            "client_request_id": client_request_id,
        }
        if created_at:
            fields["created_at"] = created_at
        with open(file_path, "rb") as handle:
            payload = self._request(
                "POST",
                "/attachments/upload",
                data=fields,
                files={"file": (file_name, handle, "application/octet-stream")},
            )
        return CreateResult(replayed=bool(payload.get("replayed")), raw=payload)

    def create_relationship(
        self, task_id: int, target_task_id: int, relation_type: str = "subtask_of"
    ) -> CreateResult:
        payload = self._request(
            "POST",
            f"/tasks/{task_id}/relationships",
            json_body={"target_task_id": target_task_id, "relation_type": relation_type},
        )
        return CreateResult(raw=payload)

    def patch_import_batch(self, batch_id: int, fields: dict[str, Any]) -> None:
        self._request("PATCH", f"/import-batches/{batch_id}", json_body=fields)


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


def _json_or_error(response: httpx.Response, path: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise TargetError(
            f"non-JSON response ({response.status_code}) from {path}",
            code="invalid_response",
            status_code=response.status_code,
        ) from exc
    if not isinstance(payload, dict):
        raise TargetError(
            f"unexpected response shape from {path}",
            code="invalid_response",
            status_code=response.status_code,
        )
    return payload
