# Contributing to ALL WR Toolkit

Thank you for considering a contribution. This document is the canonical
guide for human contributors; AI agents must additionally follow
[AGENTS.md](AGENTS.md).

## Scope of the project

The toolkit moves data **into** ALL WR (migration), talks to its public API,
and exposes safe automation through a CLI and an MCP server. In scope:
source connectors, the migration core, the API client, CLI, MCP, docs and
tests. Out of scope for now: GUIs, hosted services, bidirectional sync.

## Kinds of contribution

- Bug reports and reproductions
- Bug fixes and small improvements
- New source connectors (open a **connector proposal** issue first)
- Documentation improvements
- Test coverage improvements

## Before you start

1. Search the [issue tracker](https://github.com/wealthreader/allwr-toolkit/issues).
2. For anything non-trivial, open an issue first and get a green light -
   especially for new connectors and breaking changes (which require a
   `breaking-change` issue and an ADR).
3. Every PR should be linked to an issue, except trivial documentation fixes.

## Development setup

Requires Python 3.11+ (CI tests 3.11 through 3.14).

```bash
git clone https://github.com/wealthreader/allwr-toolkit
cd allwr-toolkit
make setup          # creates .venv and installs '.[dev,mcp]' + pre-commit
```

## Running the checks (the same ones CI runs)

```bash
make format         # ruff format + autofixes
make check          # lint + type-check + tests + security + docs + build
```

Individually: `make lint`, `make type-check`, `make test`, `make security`,
`make docs`, `make build`.

## Expectations for every pull request

- English everywhere: code, comments, commits, PR text.
- Tests accompany every behavior change; bug fixes include a regression test.
- Documentation and `CHANGELOG.md` updated for user-visible changes.
- **Never** include real customer data, personal data, credentials or
  internal endpoints - not in code, fixtures, examples or screenshots.
  Fixtures are synthetic and obviously fake (see `tests/AGENTS.md`).
- Keep PRs focused and reviewably small; avoid unrelated refactors.
- Migration safety invariants hold: dry-run stays the default, apply stays
  plan-gated, idempotency and resume keep working, no silent data loss.
- Declare in the PR description whether migration behavior or mappings change.
- All required checks green; at least one approving review (CODEOWNERS apply);
  conversations resolved before merge. Draft PRs are welcome for early CI
  feedback.

## Developer Certificate of Origin (DCO)

We use the [DCO](https://developercertificate.org/) instead of a CLA. Sign
off every commit (`git commit -s`), which adds a `Signed-off-by:` trailer
certifying you have the right to contribute the change under the project
license. Contributions are licensed under Apache-2.0.

## Breaking changes

Public contracts (CLI, configuration format, plan/report formats, state
schema, connector SDK) may change before v1.0.0, but every breaking change
must be documented in the changelog, reflected in state-schema
compatibility, called out in release notes and avoided when a
backwards-compatible alternative exists.

## Code of conduct and security

By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).
Security issues go through [SECURITY.md](SECURITY.md), never public issues.

## Definition of done

A contribution is done when: the linked issue's problem is solved, tests
prove it, docs and changelog reflect it, `make check` passes locally, CI is
green and review feedback is addressed.
