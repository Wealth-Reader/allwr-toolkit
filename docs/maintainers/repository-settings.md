# Repository settings

Repository policy is **configured, not just documented**:
`scripts/configure_repository.py` is the reproducible source of truth
(dry-run by default, `--apply` to enforce). It validates the repository
identity, then converges: description, topics, squash-only merges, branch
auto-delete, wiki off, issues on, the `main` ruleset, the `v*` tag ruleset,
labels and security toggles.

## The main ruleset

Pull requests required (direct pushes blocked); 1 approving review;
CODEOWNER review; stale approvals dismissed on push; approval required after
the last push by someone other than its author; conversations resolved; the
`Quality Gate` and `Security Gate` checks green; branch up to date; linear
history; squash merges only; force pushes and deletion blocked; no ordinary
bypass (org owners only, each use documented in an issue).

Required checks are only added once their workflow exists with a stable job
name — `Quality Gate` and `Security Gate` are aggregate jobs for exactly
that reason.

## Not configurable via API

Organization-level secret-scanning defaults, some plan-dependent security
toggles and private vulnerability reporting must be verified by hand in the
repository settings; the script prints a reminder.

## Reality of pull requests

GitHub cannot prevent someone from *opening* a PR before tests pass — and
draft PRs for early CI feedback are welcome. What the ruleset guarantees is
that nothing **merges** without green required checks and review.
