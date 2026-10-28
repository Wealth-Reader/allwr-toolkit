# MCP server

`allwr-toolkit mcp serve` runs a Model Context Protocol server (stdio) so AI
agents can operate migrations **safely**.

## Multi-agent auto-setup and doctor

Register `allwr-toolkit` across all detected AI agents with one command:

```bash
# Preview changes without modifying any files
allwr-toolkit mcp setup --dry-run

# Apply registration across all detected clients
allwr-toolkit mcp setup --yes
# or via uvx:
uvx --from 'allwr-toolkit[mcp]' allwr-toolkit mcp setup --yes

# Configure specific client(s) even before their first launch
allwr-toolkit mcp setup --client claude_code,cursor,codex --yes

# Verify MCP dependencies and client registrations
allwr-toolkit mcp doctor
allwr-toolkit mcp doctor --client all
```

### Supported MCP clients

`allwr-toolkit mcp setup` and `allwr-toolkit mcp doctor` support 25 local client
configurations (`claude_code`, `claude_desktop`, `codex`, `cursor`, `gemini_cli`,
`windsurf`, `devin`, `opencode`, `antigravity`, `copilot_cli`, `commandcode`,
`qwen_code`, `kimi`, `vscode`, `trae`, `workbuddy`, `grok_build`, `omp`, `pi`,
`hermes`, `qoder`, `droid`, `zcode`, `dsh`, `freebuff`) plus manual remediation
guidance for `grok_bot`.

### Safe configuration writes

- **Read-only by default**: generated client configurations invoke
  `allwr-toolkit mcp serve` without setting `ALLWR_MCP_ALLOW_WRITES=true`.
- **Ownership protection**: if an existing `allwr-toolkit` entry points to an
  unrelated command, setup refuses to overwrite it and reports a `conflict`.
- **Backups and recovery rotation**: modifying an existing file writes
  `<config>.allwr-toolkit.backup` first, and rotates any differing prior backup
  to `<config>.allwr-toolkit.backup.<sha256>.recovery`.
- **Non-interactive safety**: running `allwr-toolkit mcp setup` without `--yes`
  in `--json` or non-TTY mode returns `status="needs_confirmation"` (exit code
  `2`) without touching disk.

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
