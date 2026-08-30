"""Restrictive file permissions for state and report files."""

from __future__ import annotations

import os
from pathlib import Path

_OWNER_ONLY = 0o600


def restrict(path: str | Path) -> None:
    """Make *path* readable and writable by the owner only (best effort)."""
    try:
        os.chmod(path, _OWNER_ONLY)
    except OSError:  # pragma: no cover - non-POSIX or permission oddities
        pass
