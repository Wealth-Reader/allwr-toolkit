"""Central redaction for logs and reports.

Anything that might be a credential or a personal identifier is masked before
it can reach a log line, an error message or a report file.
"""

from __future__ import annotations

import logging
import re

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # ALL WR API keys.
    (re.compile(r"\bwrk_[A-Za-z0-9]{4,}\b"), "wrk_[REDACTED]"),
    (re.compile(r"\bwrb_[A-Za-z0-9]{4,}\b"), "wrb_[REDACTED]"),
    # Bearer tokens in headers or messages.
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-/+=:]{8,}"), r"\1[REDACTED]"),
    # Asana personal access tokens (digits/digits:secret).
    (re.compile(r"\b\d/\d{6,}:[A-Za-z0-9]{6,}\b"), "[REDACTED_TOKEN]"),
    # Generic key=value credential shapes.
    (
        re.compile(r"(?i)\b(api[_-]?key|token|secret|password|authorization)\b(\s*[:=]\s*)\S+"),
        r"\1\2[REDACTED]",
    ),
    # Email addresses: keep first character and domain TLD shape only.
    (
        re.compile(r"\b([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b"),
        r"\1***@\2",
    ),
]


def redact(text: str) -> str:
    """Return *text* with credentials and emails masked."""
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class RedactingFilter(logging.Filter):
    """Logging filter that redacts every record message and its arguments."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(str(record.msg))
        if record.args:
            record.args = tuple(redact(str(a)) if isinstance(a, str) else a for a in record.args)
        return True


def install_redaction(logger: logging.Logger | None = None) -> None:
    """Attach the redacting filter to *logger* (root logger by default)."""
    target = logger or logging.getLogger()
    if not any(isinstance(f, RedactingFilter) for f in target.filters):
        target.addFilter(RedactingFilter())
