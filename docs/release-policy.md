# Release policy

Semantic Versioning.

- **v0.1.0** — repository foundation, migration core, CLI, initial Asana and
  Freshdesk importers, MCP server (alpha).
- **v0.2.0** — stable connector SDK + external connector template.
- **v0.3.0** — expanded MCP operations + generic CSV/JSON importer.
- **v1.0.0** — stable public contracts (CLI, configuration, plan/report
  formats, state schema, SDK).

Before 1.0.0 breaking changes are possible but must be documented in the
changelog, reflected in state-schema compatibility, announced in release
notes, and avoided when a backwards-compatible alternative exists. Releases
are cut from protected `v*` tags only; artifacts ship with checksums and an
SBOM. PyPI publishing waits for approved naming and release policy and will
use OIDC trusted publishing.
