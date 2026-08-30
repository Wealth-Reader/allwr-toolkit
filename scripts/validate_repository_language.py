#!/usr/bin/env python3
"""Verify that every tracked text file in the repository is written in English.

Heuristics, not linguistics: the check looks for Spanish-specific characters
and very common Spanish stopwords in code, docs and configuration. It is used
by CI and pre-commit; false positives can be suppressed with an inline
``language-ok`` marker on the same line.
"""

from __future__ import annotations

import re
import subprocess  # nosec B404 - fixed executables (git, gh), no untrusted input
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".toml",
    ".yaml",
    ".yml",
    ".json",
    ".txt",
    ".cfg",
    ".ini",
    ".html",
    ".editorconfig",
    ".gitignore",
}
SKIP_PARTS = {".venv", "site", "dist", ".git"}
MARKER = "language-ok"

# Characters that essentially never appear in English technical prose.
SPANISH_CHARS = re.compile(r"[ñÑ¿¡áéíóúÁÉÍÓÚ]")  # language-ok
# Common Spanish stopwords as whole words (lowercase comparison).
SPANISH_WORDS = re.compile(
    r"\b(el|la|los|las|una|unos|unas|para|pero|porque|hasta|desde|cuando|"  # language-ok
    r"donde|entre|sobre|también|según|aunque|mientras|tarea|tareas|archivo|"  # language-ok
    r"usuario|usuarios|proyecto|proyectos|migración|migracion|configuración)\b"  # language-ok
)


def tracked_files() -> list[Path]:
    output = subprocess.run(  # nosec B603 B607 - fixed executable, controlled args
        ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout
    return [REPO_ROOT / line for line in output.splitlines() if line]


def check_file(path: Path) -> list[str]:
    if path.suffix not in TEXT_SUFFIXES and path.name not in {"Makefile", "LICENSE"}:
        return []
    if any(part in SKIP_PARTS for part in path.parts):
        return []
    try:
        content = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []
    problems: list[str] = []
    for line_number, line in enumerate(content.splitlines(), start=1):
        if MARKER in line:
            continue
        if SPANISH_CHARS.search(line) or SPANISH_WORDS.search(line.lower()):
            relative = path.relative_to(REPO_ROOT)
            problems.append(f"{relative}:{line_number}: non-English content: {line.strip()[:90]}")
    return problems


def main() -> int:
    problems: list[str] = []
    for path in tracked_files():
        problems.extend(check_file(path))
    if problems:
        print("Repository language check FAILED (English only):")
        for problem in problems:
            print(f"  {problem}")
        return 1
    print("Repository language check passed: no non-English content detected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
