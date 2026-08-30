# Maintainers

## Current maintainers

| Maintainer | GitHub | Areas |
|---|---|---|
| David Lozano | [@davidwealthreader](https://github.com/davidwealthreader) | All areas (lead) |

Wealthreader S.L. sponsors and stewards the project.

## Ownership areas

- **Migration core** (planning, state, execution): lead maintainer
- **ALL WR API client**: lead maintainer
- **Connectors** (asana, freshdesk, SDK): lead maintainer; connector
  contributors may be granted per-connector review rights
- **CLI and MCP**: lead maintainer
- **CI, security and releases**: lead maintainer

## Responsibilities

- Review pull requests within a reasonable time (target: first response
  within one week).
- Hold the safety invariants: dry-run default, plan-gated apply, idempotency,
  no silent data loss, MCP write gating.
- Triage issues and security reports; security reports take priority.
- Cut releases (see `docs/maintainers/release-process.md`); only maintainers
  or release automation may create `v*` tags.

## Adding and removing maintainers

New maintainers are invited by consensus of the current maintainers after a
track record of quality contributions and reviews. Maintainers who become
inactive for an extended period may be moved to an emeritus list. Disputes
are resolved as described in `GOVERNANCE.md`.

## Bus factor

The single-maintainer situation is acknowledged and mitigated by: everything
required to build, test and release being automated and documented in this
repository; repository settings reproducible via
`scripts/configure_repository.py`; and organization owners retaining
administrative access.

Security contact: use GitHub private vulnerability reporting (see
`SECURITY.md`). No personal contact details are published.
