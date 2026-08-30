# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Migration core: canonical model, configuration-driven mapping, plan/apply
  lifecycle with SHA-256 plan verification, SQLite checkpoint state with
  resume, idempotent execution, cooperative cancellation and report bundle
  (JSON, HTML, CSV, cleanup manifest).
- Typed ALL WR Tasks import-mode API client (retries with backoff and jitter,
  Retry-After support, idempotency keys, correlation ids, redacted logging).
- Connector SDK with entry-point plugin discovery.
- Asana importer (beta): offline export mode and live API mode, curated GID
  selection manifest, rich-subtask vs checklist distinction, GID
  preservation.
- Freshdesk importer (beta): tickets, conversations with private notes kept
  private, contacts, companies, streamed attachments, HTML sanitization.
- `allwr-toolkit` CLI: doctor, connectors, migrate inspect/plan/apply,
  migration status/resume/cancel/report/cleanup-plan, mcp serve; JSON output
  and meaningful exit codes; dry-run by default.
- MCP server (alpha): read and planning tools by default; mutating tools only
  with `ALLWR_MCP_ALLOW_WRITES=true`; apply requires a verified plan.
- Full test suite (unit, contract, integration), quality tooling, CI/security
  workflows, documentation and governance files.
