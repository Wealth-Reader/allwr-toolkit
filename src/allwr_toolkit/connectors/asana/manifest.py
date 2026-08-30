"""Selection manifest: the curated list of Asana GIDs to migrate.

The manifest is a tab-separated text file, one top-level task per line, whose
first column is the original Asana GID. Lines starting with ``#`` are
comments, ``##`` headers group projects, and deleting or commenting a line
excludes that task. The manifest is a migration input: never commit one that
contains real company data.
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, Field

from allwr_toolkit.core.errors import ConfigurationError

_GID_LINE = re.compile(r"^(\d{6,})(?:\t|$)")
_LOOKS_LIKE_GID_PREFIX = re.compile(r"^\d+\S*")


class SelectionManifest(BaseModel):
    path: str
    selected: list[str] = Field(default_factory=list)
    duplicates: list[str] = Field(default_factory=list)
    invalid_lines: list[int] = Field(default_factory=list, description="1-based line numbers.")
    total_lines: int = 0

    @property
    def selected_set(self) -> set[str]:
        return set(self.selected)


def read_selection_manifest(path: str | Path) -> SelectionManifest:
    """Parse a selection manifest.

    - a line whose first tab-separated column is a numeric GID selects it;
    - ``#`` comments, ``##`` section headers and blank lines are ignored;
    - duplicated GIDs are reported (only the first occurrence counts);
    - a non-comment line that starts with something GID-like but fails
      validation is reported as invalid instead of being dropped silently.
    """
    file = Path(path)
    if not file.is_file():
        raise ConfigurationError(f"selection manifest not found: {file}")
    manifest = SelectionManifest(path=str(file))
    seen: set[str] = set()
    for line_number, raw_line in enumerate(file.read_text(encoding="utf-8").splitlines(), start=1):
        manifest.total_lines = line_number
        line = raw_line.rstrip("\n")
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _GID_LINE.match(line)
        if match is None:
            if _LOOKS_LIKE_GID_PREFIX.match(stripped):
                manifest.invalid_lines.append(line_number)
            continue
        gid = match.group(1)
        if gid in seen:
            manifest.duplicates.append(gid)
            continue
        seen.add(gid)
        manifest.selected.append(gid)
    return manifest
