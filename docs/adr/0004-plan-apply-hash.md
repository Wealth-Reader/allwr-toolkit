# ADR-0004: Plan/apply separation with SHA-256 verification

**Status**: accepted · **Date**: 2026-08-31

## Context

The single most dangerous failure mode of a migration tool is writing the
wrong thing to the wrong place. Human review must be structurally
guaranteed, not a habit.

## Decision

Planning and applying are separate steps joined by a reviewable JSON plan.
The plan embeds the target identity, the configuration hash and a SHA-256
hash over its own canonical content. Apply (CLI and MCP alike) re-verifies:
hash intact, target matches configuration, configuration unchanged,
high-severity warnings accepted. Dry-run is the default everywhere;
non-interactive apply additionally requires `--yes`.

## Consequences

A stale, edited or mistargeted plan cannot be applied. Tests assert zero
HTTP requests in dry-run and rejection of tampered plans.
