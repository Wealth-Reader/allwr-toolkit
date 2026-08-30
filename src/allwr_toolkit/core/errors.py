"""Typed error hierarchy for the toolkit.

Connectors and the target client must convert raw errors (HTTP, IO, parsing)
into these types so the engine can decide what is retryable and what is not.
"""

from __future__ import annotations


class ToolkitError(Exception):
    """Base class for every error raised by the toolkit."""

    def __init__(self, message: str, *, code: str = "toolkit_error") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ConfigurationError(ToolkitError):
    """The migration configuration is invalid or incomplete."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="configuration_error")


class SourceError(ToolkitError):
    """An error reported by (or while talking to) a source system."""

    def __init__(self, message: str, *, code: str = "source_error") -> None:
        super().__init__(message, code=code)


class TargetError(ToolkitError):
    """An error reported by (or while talking to) the ALL WR target API."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "target_error",
        status_code: int | None = None,
        error_id: str | None = None,
    ) -> None:
        super().__init__(message, code=code)
        self.status_code = status_code
        self.error_id = error_id


class TransientError(ToolkitError):
    """A temporary failure that is safe to retry with backoff."""

    def __init__(self, message: str, *, code: str = "transient_error") -> None:
        super().__init__(message, code=code)


class RateLimitedError(TransientError):
    """The remote API asked us to slow down (HTTP 429)."""

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message, code="rate_limited")
        self.retry_after = retry_after


class PermanentError(ToolkitError):
    """A failure that will not go away by retrying (4xx, validation...)."""

    def __init__(self, message: str, *, code: str = "permanent_error") -> None:
        super().__init__(message, code=code)


class PlanValidationError(PermanentError):
    """The migration plan failed validation (hash, target or content)."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="plan_validation_error")


class BlockedByWarningsError(PermanentError):
    """High severity warnings block apply until explicitly accepted."""

    def __init__(self, message: str, *, warning_codes: list[str]) -> None:
        super().__init__(message, code="blocked_by_warnings")
        self.warning_codes = warning_codes


class StateError(ToolkitError):
    """The local migration state store is missing, locked or inconsistent."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="state_error")


class CancelledError(ToolkitError):
    """The run was cancelled cooperatively; state stays resumable."""

    def __init__(self, message: str = "migration cancelled") -> None:
        super().__init__(message, code="cancelled")
