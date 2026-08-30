# ADR-0003: SQLite migration state store

**Status**: accepted · **Date**: 2026-08-31

## Context

Resume and idempotency need durable local state; requiring a database server
would kill the "clean machine dry run" experience.

## Decision

One SQLite file per migration effort, schema-versioned (`schema_version`
table; newer schemas are rejected with an upgrade message). Tables hold run
identity and per-record status/attempts/checksums — never tokens and never
record bodies. Files are created owner-only (0600).

## Consequences

Zero infrastructure. State can be inspected with any SQLite client. Schema
changes require an explicit migration and a version bump.
