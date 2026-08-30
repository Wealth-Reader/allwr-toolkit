# Security review (pre-publication and per release)

Run before making the repository public, and before every release:

1. `python scripts/audit_publication.py --history` — secrets and real-data
   scan over the working tree **and the full git history**.
2. `python scripts/validate_repository_language.py` — English-only check.
3. `pip-audit` and `bandit` (also in CI) — dependency and code scanning.
4. License review: dependencies are Apache-2.0-compatible; record any new
   attribution requirements.
5. Workflow review: actions pinned to full SHAs, least-privilege
   `permissions`, no secrets exposed to fork PRs, no `pull_request_target`
   without an explicit security review.
6. Fixture review: synthetic, English, sanitized (see `tests/AGENTS.md`).
7. Repository settings review: visibility, topics, description, rulesets
   (`scripts/configure_repository.py` dry run should report no drift).
8. Record the outcome in the tracking issue; **only after this checklist
   passes may the repository visibility change to public**.
