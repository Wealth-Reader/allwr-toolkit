"""Allowlist-based HTML sanitizer for source-provided rich text.

Source systems hand us arbitrary HTML (ticket bodies, task notes, comments).
Before it is sent to ALL WR it is reduced to a small allowlist of structural
tags; scripts, styles, event handlers and javascript: URLs are removed.
"""

from __future__ import annotations

import html
from html.parser import HTMLParser

_ALLOWED_TAGS = {
    "p",
    "br",
    "b",
    "strong",
    "i",
    "em",
    "u",
    "s",
    "ul",
    "ol",
    "li",
    "a",
    "blockquote",
    "code",
    "pre",
    "h1",
    "h2",
    "h3",
    "h4",
    "hr",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "img",
}
_VOID_TAGS = {"br", "hr", "img"}
_DROP_WITH_CONTENT = {"script", "style", "iframe", "object", "embed", "noscript"}
_ALLOWED_ATTRS: dict[str, set[str]] = {
    "a": {"href", "title"},
    "img": {"src", "alt", "title", "width", "height"},
}
_SAFE_URL_PREFIXES = ("http://", "https://", "mailto:")


def _safe_url(value: str) -> bool:
    return value.strip().lower().startswith(_SAFE_URL_PREFIXES)


class _Sanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self._drop_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _DROP_WITH_CONTENT:
            self._drop_depth += 1
            return
        if self._drop_depth or tag not in _ALLOWED_TAGS:
            return
        kept: list[str] = []
        for name, value in attrs:
            if name.startswith("on") or value is None:
                continue
            if name in _ALLOWED_ATTRS.get(tag, set()):
                if name in {"href", "src"} and not _safe_url(value):
                    continue
                kept.append(f' {name}="{html.escape(value, quote=True)}"')
        closing = " /" if tag in _VOID_TAGS else ""
        self.out.append(f"<{tag}{''.join(kept)}{closing}>")

    def handle_endtag(self, tag: str) -> None:
        if tag in _DROP_WITH_CONTENT:
            self._drop_depth = max(0, self._drop_depth - 1)
            return
        if self._drop_depth or tag not in _ALLOWED_TAGS or tag in _VOID_TAGS:
            return
        self.out.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if not self._drop_depth:
            self.out.append(html.escape(data))


def sanitize_html(raw: str | None) -> str:
    """Return a sanitized version of *raw* limited to the tag allowlist."""
    if not raw:
        return ""
    parser = _Sanitizer()
    parser.feed(raw)
    parser.close()
    return "".join(parser.out)
