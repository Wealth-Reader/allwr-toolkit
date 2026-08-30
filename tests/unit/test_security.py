"""Redaction and HTML sanitizing."""

import logging

from allwr_toolkit.security import RedactingFilter, redact, sanitize_html


def test_redacts_allwr_keys() -> None:
    assert "wrk_" + "a1b2c3d4" not in redact("key is wrk_a1b2c3d4e5")  # audit-ok
    assert "wrk_[REDACTED]" in redact("key is wrk_a1b2c3d4e5")  # audit-ok


def test_redacts_bearer_tokens() -> None:
    out = redact("Authorization: Bearer abc123def456ghi")
    assert "abc123def456ghi" not in out


def test_redacts_asana_tokens() -> None:
    out = redact("token 1/1200000000000001:deadbeefcafe")  # audit-ok
    assert "deadbeefcafe" not in out


def test_redacts_key_value_shapes() -> None:
    out = redact("api_key=supersecretvalue and password: hunter22")
    assert "supersecretvalue" not in out
    assert "hunter22" not in out


def test_masks_emails_but_keeps_domain_shape() -> None:
    out = redact("contact alex.doe@example.com please")
    assert "alex.doe@example.com" not in out
    assert "a***@example.com" in out


def test_logging_filter_redacts_messages_and_args() -> None:
    records: list[logging.LogRecord] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    logger = logging.getLogger("redaction-test")
    logger.setLevel(logging.INFO)
    logger.addFilter(RedactingFilter())
    logger.addHandler(Capture())
    logger.info("token is %s", "wrk_verysecret123")  # audit-ok
    assert "wrk_verysecret123" not in records[0].getMessage()  # audit-ok


def test_sanitize_drops_scripts_and_event_handlers() -> None:
    out = sanitize_html(
        '<p onclick="evil()">hi</p><script>alert(1)</script><style>x</style>'
        '<a href="javascript:evil()">bad</a><a href="https://example.com">ok</a>'
    )
    assert "script" not in out
    assert "onclick" not in out
    assert "javascript:" not in out
    assert '<a href="https://example.com">ok</a>' in out


def test_sanitize_keeps_structure_and_escapes_text() -> None:
    out = sanitize_html("<p><b>bold</b> &amp; 1 < 2</p>")
    assert "<b>bold</b>" in out
    assert "&amp;" in out


def test_sanitize_handles_empty() -> None:
    assert sanitize_html(None) == ""
    assert sanitize_html("") == ""
