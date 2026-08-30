# MCP server

`allwr-toolkit mcp serve` runs a Model Context Protocol server (stdio) so AI
agents can operate migrations **safely**.

## Tools

Read and planning tools (always available): `list_connectors`,
`describe_connector`, `validate_config`, `inspect_source`, `generate_plan`
(writes only the local plan file), `inspect_plan`, `migration_status`,
`migration_report`.

Write tools (registered **only** when the server environment sets
`ALLWR_MCP_ALLOW_WRITES=true`): `apply_plan`, `resume_migration`,
`cancel_migration`. Their descriptions are marked WRITE.

## Security rules

- Writes are disabled by default; only the person launching the server can
  enable them — an agent cannot from inside a session.
- `apply_plan` requires a previously generated plan and re-verifies its hash
  and target; the dry-run cycle cannot be skipped.
- A generic request to "migrate" is not approval: agents must show the plan
  and get explicit human confirmation before `apply_plan`.
- Input sizes are bounded; no tool executes shell commands, arbitrary
  filesystem access or URLs; responses never contain raw secrets.
- Every write is attributable to a migration run id.

These properties are covered by tests (`tests/integration/test_mcp.py`).
