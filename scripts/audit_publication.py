#!/usr/bin/env python3
"""Publication audit: scan the repository for secrets and real-data leaks.

Run before every release and in CI. Checks tracked files (and optionally the
full git history with --history) for credential shapes and for denylisted
internal identifiers that must never appear in this public repository.
"""

from __future__ import annotations

import argparse
import re
import subprocess  # nosec B404 - fixed executables (git, gh), no untrusted input
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKIP_PARTS = {".venv", "site", "dist", ".git"}
MARKER = "audit-ok"

SECRET_PATTERNS: dict[str, re.Pattern[str]] = {
    "allwr api key": re.compile(r"\bwrk_(?!example)[A-Za-z0-9]{8,}\b"),
    "legacy billing key": re.compile(r"\bwrb_[A-Za-z0-9]{8,}\b"),
    "asana token": re.compile(r"\b\d/\d{6,}:(?!example)[A-Za-z0-9]{8,}\b"),
    "private key block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "github token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    "generic assignment": re.compile(
        r"(?i)\b(api_key|secret|password|token)\b\s*[:=]\s*[\"'](?!.*(example|synthetic|"
        r"not_a_real|placeholder|redacted|test))[A-Za-z0-9+/_\-]{16,}[\"']"
    ),
}

# Internal identifiers that must never ship in the public toolkit.
REAL_DATA_PATTERNS: dict[str, re.Pattern[str]] = {
    "internal hostname": re.compile(
        r"\b([REDACTED-HOST]|[REDACTED-HOST]|[REDACTED-HOST]|www-local\.allwr\.io)\b"  # audit-ok
    ),
    # The public homepage may be referenced; a production API/app URL may not.
    "production api url": re.compile(r"https://www\.allwr\.io/\S*(api|app|tasks)"),
    "wealthreader email": re.compile(r"\b[A-Za-z0-9._%+-]+@wealthreader\.com\b"),
}


def tracked_files() -> list[Path]:
    output = subprocess.run(  # nosec B603 B607 - fixed executable, controlled args
        ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout
    return [REPO_ROOT / line for line in output.splitlines() if line]


def scan_text(label_source: str, content: str, problems: list[str]) -> None:
    for line_number, line in enumerate(content.splitlines(), start=1):
        if MARKER in line:
            continue
        for label, pattern in {**SECRET_PATTERNS, **REAL_DATA_PATTERNS}.items():
            if pattern.search(line):
                problems.append(
                    f"{label_source}:{line_number}: possible {label}: {line.strip()[:80]}"
                )


def scan_working_tree() -> list[str]:
    problems: list[str] = []
    for path in tracked_files():
        if any(part in SKIP_PARTS for part in path.parts):
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        scan_text(str(path.relative_to(REPO_ROOT)), content, problems)
    return problems


def scan_history() -> list[str]:
    """Scan every blob in git history (slower; run before going public)."""
    problems: list[str] = []
    revisions = subprocess.run(  # nosec B603 B607 - fixed executable, controlled args
        ["git", "rev-list", "--all"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    for revision in revisions:
        show = subprocess.run(  # nosec B603 B607 - fixed executable, controlled args
            ["git", "show", "--format=", "--unified=0", revision],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        added = "\n".join(line[1:] for line in show.splitlines() if line.startswith("+"))
        scan_text(f"commit {revision[:12]}", added, problems)
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", action="store_true", help="also scan all git history")
    args = parser.parse_args()
    problems = scan_working_tree()
    if args.history:
        problems.extend(scan_history())
    if problems:
        print("Publication audit FAILED:")
        for problem in problems:
            print(f"  {problem}")
        return 1
    scope = "working tree and history" if args.history else "working tree"
    print(f"Publication audit passed ({scope}): no secrets or real data detected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
