"""Minimal Asana API client for live mode: pagination and rate limits only."""

from __future__ import annotations

import os
import time
from typing import Any

import httpx

from allwr_toolkit import USER_AGENT
from allwr_toolkit.core.errors import ConfigurationError, SourceError

ASANA_TOKEN_ENV = "ALLWR_TOOLKIT_ASANA_TOKEN"  # noqa: S105 # nosec B105 - env var name
API_BASE = "https://app.asana.com/api/1.0"

TASK_FIELDS = ",".join(
    [
        "gid",
        "name",
        "notes",
        "html_notes",
        "completed",
        "completed_at",
        "completed_by.name",
        "completed_by.gid",
        "created_at",
        "modified_at",
        "due_on",
        "due_at",
        "start_on",
        "assignee.gid",
        "assignee.name",
        "parent.gid",
        "projects.gid",
        "projects.name",
        "memberships.project.gid",
        "memberships.project.name",
        "memberships.section.gid",
        "memberships.section.name",
        "tags.name",
        "custom_fields.name",
        "custom_fields.display_value",
        "custom_fields.type",
        "followers.name",
        "followers.gid",
        "num_subtasks",
        "permalink_url",
        "created_by.gid",
        "created_by.name",
    ]
)
STORY_FIELDS = "gid,created_at,created_by.gid,created_by.name,resource_subtype,type,text,html_text"
ATTACHMENT_FIELDS = "gid,name,host,download_url,view_url,permanent_url,size,created_at,parent.gid"


class AsanaApiClient:
    def __init__(
        self,
        *,
        token: str | None = None,
        transport: httpx.BaseTransport | None = None,
        max_retries: int = 6,
    ) -> None:
        value = token or os.environ.get(ASANA_TOKEN_ENV, "")
        if not value:
            raise ConfigurationError(
                f"no Asana token: set the {ASANA_TOKEN_ENV} environment variable"
            )
        self._max_retries = max_retries
        self._client = httpx.Client(
            base_url=API_BASE,
            timeout=60.0,
            transport=transport,
            headers={"Authorization": f"Bearer {value}", "User-Agent": USER_AGENT},
        )

    def close(self) -> None:
        self._client.close()

    def _sleep(self, seconds: float) -> None:  # patchable in tests
        time.sleep(seconds)

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        for attempt in range(self._max_retries):
            try:
                response = self._client.get(path, params=params)
            except httpx.HTTPError as exc:
                if attempt == self._max_retries - 1:
                    raise SourceError(f"network error calling Asana: {exc}") from exc
                self._sleep(2.0 * (attempt + 1))
                continue
            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", "5") or 5)
                self._sleep(retry_after)
                continue
            if response.status_code in {500, 502, 503, 504}:
                self._sleep(2.0 * (attempt + 1))
                continue
            if response.status_code >= 400:
                raise SourceError(
                    f"Asana HTTP {response.status_code} on {path}",
                    code=f"asana_http_{response.status_code}",
                )
            payload = response.json()
            if not isinstance(payload, dict):
                raise SourceError("unexpected Asana response shape")
            return payload
        raise SourceError(f"Asana retries exhausted on {path}", code="asana_retries_exhausted")

    def paginate(self, path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        params = dict(params)
        params["limit"] = 100
        items: list[dict[str, Any]] = []
        while True:
            payload = self._get(path, params)
            items.extend(payload.get("data", []))
            next_page = payload.get("next_page")
            if not next_page:
                return items
            params["offset"] = next_page["offset"]

    def get_task(self, gid: str) -> dict[str, Any]:
        payload = self._get(f"/tasks/{gid}", {"opt_fields": TASK_FIELDS})
        task: dict[str, Any] = payload.get("data", {})
        task["stories"] = self.paginate(f"/tasks/{gid}/stories", {"opt_fields": STORY_FIELDS})
        task["attachments"] = self.paginate(
            "/attachments", {"parent": gid, "opt_fields": ATTACHMENT_FIELDS}
        )
        if task.get("num_subtasks"):
            subtasks = self.paginate(f"/tasks/{gid}/subtasks", {"opt_fields": TASK_FIELDS})
            task["subtask_gids"] = [s["gid"] for s in subtasks]
            self._subtask_cache = getattr(self, "_subtask_cache", {})
            for sub in subtasks:
                self._subtask_cache[sub["gid"]] = sub
        else:
            task["subtask_gids"] = []
        return task

    def get_workspace_users(self, workspace_gid: str) -> list[dict[str, Any]]:
        return self.paginate("/users", {"workspace": workspace_gid, "opt_fields": "name,email"})
