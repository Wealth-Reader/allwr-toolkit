# ADR-0005: MCP server with environment-gated writes

**Status**: accepted · **Date**: 2026-08-31

## Context

AI agents are first-class users of the toolkit, but an agent must never be
able to escalate itself from "inspecting" to "migrating".

## Decision

The MCP server (official `mcp` Python SDK, pinned `<2` until we migrate to
the renamed 2.x API) registers read/planning tools unconditionally, and
write tools **only** when the server process environment sets
`ALLWR_MCP_ALLOW_WRITES=true`. Write tools are marked WRITE in their
descriptions, verify the plan hash and target like the CLI, bound their
inputs, never expose shell/filesystem/URL execution and never return raw
secrets. CLI and MCP share the same workflow functions so there is no
MCP-only code path.

## Consequences

Enabling writes is a deliberate act of the human who launches the server.
Tests assert the default tool set contains no write tools and that apply
rejects invalid plans.
