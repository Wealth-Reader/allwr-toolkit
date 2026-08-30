"""Minimal Freshdesk REST API v2 client: auth, pagination, rate limits, streaming."""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path
from typing import Any

import httpx

from allwr_toolkit import USER_AGENT
from allwr_toolkit.core.errors import ConfigurationError, SourceError

FRESHDESK_KEY_ENV = "ALLWR_TOOLKIT_FRESHDESK_API_KEY"
_MAX_PAGES = 1000  # Freshdesk caps list pagination; guard against loops.


class FreshdeskClient:
    def __init__(
        self,
        domain: str,
        *,
        api_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
        max_retries: int = 6,
    ) -> None:
        if not domain:
            raise ConfigurationError("Freshdesk connector requires source.domain")
        key = api_key or os.environ.get(FRESHDESK_KEY_ENV, "")
        if not key:
            raise ConfigurationError(
                f"no Freshdesk API key: set the {FRESHDESK_KEY_ENV} environment variable"
            )
        base = domain if "." in domain else f"{domain}.freshdesk.com"
        self._client = httpx.Client(
            base_url=f"https://{base}/api/v2",
            timeout=60.0,
            transport=transport,
            auth=(key, "X"),
            headers={"User-Agent": USER_AGENT},
        )
        self._max_retries = max_retries
        self.domain = base

    def close(self) -> None:
        self._client.close()

    def _sleep(self, seconds: float) -> None:  # patchable in tests
        time.sleep(seconds)

    def _get(self, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
        for attempt in range(self._max_retries):
            try:
                response = self._client.get(path, params=params)
            except httpx.HTTPError as exc:
                if attempt == self._max_retries - 1:
                    raise SourceError(f"network error calling Freshdesk: {exc}") from exc
                self._sleep(2.0 * (attempt + 1))
                continue
            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", "10") or 10)
                self._sleep(retry_after)
                continue
            if response.status_code in {500, 502, 503, 504}:
                self._sleep(2.0 * (attempt + 1))
                continue
            if response.status_code == 404:
                raise SourceError(f"Freshdesk 404 on {path}", code="freshdesk_not_found")
            if response.status_code >= 400:
                raise SourceError(
                    f"Freshdesk HTTP {response.status_code} on {path}",
                    code=f"freshdesk_http_{response.status_code}",
                )
            return response
        raise SourceError(
            f"Freshdesk retries exhausted on {path}", code="freshdesk_retries_exhausted"
        )

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self._get(path, params).json()

    def paginate(self, path: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page = 1
        base_params = dict(params or {})
        base_params.setdefault("per_page", 100)
        while page <= _MAX_PAGES:
            base_params["page"] = page
            payload = self.get_json(path, base_params)
            if not isinstance(payload, list) or not payload:
                break
            items.extend(payload)
            if len(payload) < int(base_params["per_page"]):
                break
            page += 1
        return items

    # -- typed helpers -------------------------------------------------------

    def list_tickets(self, *, include_closed: bool = True) -> list[dict[str, Any]]:
        # updated_since far in the past returns everything, closed included.
        return self.paginate(
            "/tickets",
            {"updated_since": "1970-01-01T00:00:00Z", "order_by": "updated_at"},
        )

    def get_ticket(self, ticket_id: int | str) -> dict[str, Any]:
        payload = self.get_json(f"/tickets/{ticket_id}")
        return payload if isinstance(payload, dict) else {}

    def list_conversations(self, ticket_id: int | str) -> list[dict[str, Any]]:
        return self.paginate(f"/tickets/{ticket_id}/conversations")

    def list_contacts(self) -> list[dict[str, Any]]:
        return self.paginate("/contacts")

    def list_companies(self) -> list[dict[str, Any]]:
        return self.paginate("/companies")

    def list_agents(self) -> list[dict[str, Any]]:
        return self.paginate("/agents")

    def download_attachment(
        self, url: str, dest: Path, *, expected_size: int | None = None
    ) -> Path:
        """Stream an attachment to *dest*; verify size when known."""
        digest = hashlib.sha256()
        with self._client.stream("GET", url) as response:
            if response.status_code >= 400:
                raise SourceError(
                    f"attachment download failed with HTTP {response.status_code}",
                    code="freshdesk_attachment_failed",
                )
            with open(dest, "wb") as handle:
                for chunk in response.iter_bytes(chunk_size=1 << 16):
                    handle.write(chunk)
                    digest.update(chunk)
        size = dest.stat().st_size
        if expected_size is not None and size != expected_size:
            dest.unlink(missing_ok=True)
            raise SourceError(
                f"attachment size mismatch: expected {expected_size}, got {size}",
                code="freshdesk_attachment_size_mismatch",
            )
        return dest
