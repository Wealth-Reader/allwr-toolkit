# Governance

ALL WR Toolkit is an open-source project stewarded by Wealthreader S.L.

## Roles

- **Users** use the toolkit and report issues.
- **Contributors** send pull requests, triage issues, improve docs.
- **Maintainers** (listed in `MAINTAINERS.md`) review and merge, set
  direction, and cut releases.
- **Steward (Wealthreader S.L.)** owns the trademark "ALL WR", the GitHub
  organization and the final say on project scope.

## Decision making

Day-to-day decisions happen in issues and pull requests by lazy consensus:
a change is accepted when a maintainer approves it and no maintainer objects.
Significant technical decisions are recorded as ADRs in `docs/adr/`.
Disagreements are resolved by maintainer majority; if tied, the steward
decides.

## Changes to public contracts

Breaking changes to CLI, configuration, plan/report formats, state schema or
the connector SDK require an approved `breaking-change` issue and an ADR
(see `CONTRIBUTING.md`).

## Changes to this document

By pull request, approved by the maintainers and the steward.
