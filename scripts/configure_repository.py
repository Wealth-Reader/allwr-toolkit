#!/usr/bin/env python3
"""Configure the GitHub repository: settings, topics, labels and rulesets.

Repository policy is CONFIGURED, not just documented. This script is
idempotent, dry-run by default, and uses the ``gh`` CLI for authentication
(no token is ever embedded). Run with --apply to make changes.

Not configurable via API (documented here on purpose):
- organization-level secret scanning defaults (verify in the org settings);
- the "private vulnerability reporting" toggle on some plans;
- required workflows defined at the organization level.
"""

from __future__ import annotations

import argparse
import json
import subprocess  # nosec B404 - fixed executables (git, gh), no untrusted input
import sys
from typing import Any

EXPECTED_REPOS = {"wealthreader/allwr-toolkit", "Wealth-Reader/allwr-toolkit"}

DESCRIPTION = (
    "Open-source migration, integration and automation tools for ALL WR - CLI, API and MCP."
)
TOPICS = [
    "allwr",
    "allwr-api",
    "mcp",
    "mcp-server",
    "python",
    "data-migration",
    "automation",
    "integrations",
    "asana",
    "freshdesk",
    "task-management",
    "erp",
    "developer-tools",
    "open-source",
]
SETTINGS = {
    "description": DESCRIPTION,
    "has_issues": True,
    "has_wiki": False,
    "has_projects": False,
    "allow_squash_merge": True,
    "allow_merge_commit": False,
    "allow_rebase_merge": False,
    "delete_branch_on_merge": True,
    "web_commit_signoff_required": True,
}
LABELS: dict[str, tuple[str, str]] = {
    "bug": ("d73a4a", "Something is broken"),
    "enhancement": ("a2eeef", "New feature or improvement"),
    "connector": ("0e8a16", "About a specific source connector"),
    "connector-request": ("c2e0c6", "Proposal for a new connector"),
    "good-first-issue": ("7057ff", "Good for newcomers"),
    "help-wanted": ("008672", "Maintainers welcome outside help"),
    "documentation": ("0075ca", "Documentation only"),
    "security": ("b60205", "Security related"),
    "privacy": ("e11d21", "Personal data handling"),
    "dependencies": ("0366d6", "Dependency updates"),
    "breaking-change": ("d93f0b", "Changes a public contract"),
    "needs-design": ("d4c5f9", "Needs a design/ADR before implementation"),
    "needs-reproduction": ("fef2c0", "Cannot act without a reproduction"),
    "migration-core": ("1d76db", "Planning, state, execution engine"),
    "asana": ("f9d0c4", "Asana connector"),
    "freshdesk": ("f9d0c4", "Freshdesk connector"),
    "api-client": ("5319e7", "ALL WR API client"),
    "cli": ("bfd4f2", "Command line interface"),
    "mcp": ("bfd4f2", "MCP server"),
    "tests": ("c5def5", "Test suite"),
    "blocked": ("000000", "Blocked on something else"),
    "duplicate": ("cfd3d7", "Already tracked elsewhere"),
}
RULESET = {
    "name": "main",
    "target": "branch",
    "enforcement": "active",
    "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
    "rules": [
        {"type": "deletion"},
        {"type": "non_fast_forward"},
        {"type": "required_linear_history"},
        {
            "type": "pull_request",
            "parameters": {
                "required_approving_review_count": 1,
                "dismiss_stale_reviews_on_push": True,
                "require_code_owner_review": True,
                "require_last_push_approval": True,
                "required_review_thread_resolution": True,
                "allowed_merge_methods": ["squash"],
            },
        },
        {
            "type": "required_status_checks",
            "parameters": {
                "strict_required_status_checks_policy": True,
                "required_status_checks": [
                    {"context": "Quality Gate"},
                    {"context": "Security Gate"},
                ],
            },
        },
    ],
    "bypass_actors": [],
}
TAG_RULESET = {
    "name": "release-tags",
    "target": "tag",
    "enforcement": "active",
    "conditions": {"ref_name": {"include": ["refs/tags/v*"], "exclude": []}},
    "rules": [
        {"type": "deletion"},
        {"type": "non_fast_forward"},
        {"type": "update"},
    ],
    "bypass_actors": [],
}


def gh(args: list[str], *, input_data: str | None = None) -> str:
    result = subprocess.run(  # nosec B603 B607 - fixed executable, controlled args
        ["gh", *args], capture_output=True, text=True, input=input_data, check=False
    )
    if result.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:3])} failed: {result.stderr.strip()}")
    return result.stdout


def gh_json(args: list[str]) -> Any:
    output = gh(args)
    return json.loads(output) if output.strip() else None


def detect_repo() -> str:
    payload = gh_json(["repo", "view", "--json", "nameWithOwner"])
    repo = str(payload["nameWithOwner"])
    if repo not in EXPECTED_REPOS:
        raise SystemExit(
            f"refusing to configure '{repo}': expected one of {sorted(EXPECTED_REPOS)}"
        )
    return repo


def plan_settings(repo: str) -> list[dict[str, Any]]:
    current = gh_json(
        [
            "api",
            f"repos/{repo}",
            "--jq",
            "{description: .description, has_issues: .has_issues, has_wiki: .has_wiki,"
            " has_projects: .has_projects, allow_squash_merge: .allow_squash_merge,"
            " allow_merge_commit: .allow_merge_commit, allow_rebase_merge: .allow_rebase_merge,"
            " delete_branch_on_merge: .delete_branch_on_merge,"
            " web_commit_signoff_required: .web_commit_signoff_required}",
        ]
    )
    changes = []
    for key, desired in SETTINGS.items():
        if current.get(key) != desired:
            changes.append(
                {"action": "setting", "key": key, "from": current.get(key), "to": desired}
            )
    return changes


def apply_settings(repo: str) -> None:
    args = ["api", "--method", "PATCH", f"repos/{repo}"]
    for key, desired in SETTINGS.items():
        args += ["-f" if isinstance(desired, str) else "-F", f"{key}={desired}"]
    gh(args)


def plan_topics(repo: str) -> list[dict[str, Any]]:
    current = gh_json(["api", f"repos/{repo}/topics", "--jq", ".names"]) or []
    missing = [t for t in TOPICS if t not in current]
    return [{"action": "topics", "add": missing}] if missing else []


def apply_topics(repo: str) -> None:
    gh(
        ["api", "--method", "PUT", f"repos/{repo}/topics", "--input", "-"],
        input_data=json.dumps({"names": TOPICS}),
    )


def plan_labels(repo: str) -> list[dict[str, Any]]:
    current = {
        label["name"] for label in gh_json(["api", f"repos/{repo}/labels", "--paginate"]) or []
    }
    return [{"action": "label", "name": name} for name in LABELS if name not in current]


def apply_labels(repo: str) -> None:
    current = {
        label["name"] for label in gh_json(["api", f"repos/{repo}/labels", "--paginate"]) or []
    }
    for name, (color, description) in LABELS.items():
        if name in current:
            continue
        gh(
            [
                "api",
                "--method",
                "POST",
                f"repos/{repo}/labels",
                "-f",
                f"name={name}",
                "-f",
                f"color={color}",
                "-f",
                f"description={description}",
            ]
        )


def plan_rulesets(repo: str) -> list[dict[str, Any]]:
    current = {ruleset["name"] for ruleset in gh_json(["api", f"repos/{repo}/rulesets"]) or []}
    return [
        {"action": "ruleset", "name": ruleset["name"]}
        for ruleset in (RULESET, TAG_RULESET)
        if ruleset["name"] not in current
    ]


def apply_rulesets(repo: str) -> None:
    current = {ruleset["name"] for ruleset in gh_json(["api", f"repos/{repo}/rulesets"]) or []}
    for ruleset in (RULESET, TAG_RULESET):
        if ruleset["name"] in current:
            continue
        gh(
            ["api", "--method", "POST", f"repos/{repo}/rulesets", "--input", "-"],
            input_data=json.dumps(ruleset),
        )


def plan_security(repo: str) -> list[dict[str, Any]]:
    return [{"action": "security", "note": "enable vulnerability alerts + automated fixes"}]


def apply_security(repo: str) -> None:
    gh(["api", "--method", "PUT", f"repos/{repo}/vulnerability-alerts"])
    gh(["api", "--method", "PUT", f"repos/{repo}/automated-security-fixes"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="apply changes (default: dry run)")
    args = parser.parse_args()
    repo = detect_repo()
    plan: list[dict[str, Any]] = []
    plan += plan_settings(repo)
    plan += plan_topics(repo)
    plan += plan_labels(repo)
    plan += plan_rulesets(repo)
    plan += plan_security(repo)
    print(json.dumps({"repository": repo, "dry_run": not args.apply, "plan": plan}, indent=2))
    if not args.apply:
        print("Dry run only. Re-run with --apply to make these changes.")
        return 0
    apply_settings(repo)
    apply_topics(repo)
    apply_labels(repo)
    apply_rulesets(repo)
    apply_security(repo)
    print("Applied.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
