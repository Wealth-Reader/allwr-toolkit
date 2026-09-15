"""CI workflow invariants that Dependabot can otherwise split apart."""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SECURITY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "security.yml"
DEPENDABOT = REPO_ROOT / ".github" / "dependabot.yml"

CODEQL_USES = re.compile(
    r"uses:\s+github/codeql-action/(init|analyze)@([0-9a-f]{40})",
)


def test_codeql_init_and_analyze_use_the_same_commit() -> None:
    pins = dict(CODEQL_USES.findall(SECURITY_WORKFLOW.read_text(encoding="utf-8")))
    assert set(pins) == {"init", "analyze"}
    assert pins["init"] == pins["analyze"]


def test_dependabot_groups_codeql_action_updates() -> None:
    config = yaml.safe_load(DEPENDABOT.read_text(encoding="utf-8"))
    actions = next(
        entry for entry in config["updates"] if entry["package-ecosystem"] == "github-actions"
    )
    patterns = [
        pattern
        for group in actions.get("groups", {}).values()
        for pattern in group.get("patterns", [])
    ]
    assert any(
        fnmatch.fnmatch("github/codeql-action/init", pattern)
        and fnmatch.fnmatch("github/codeql-action/analyze", pattern)
        for pattern in patterns
    )
