# Writing a connector

A connector reads one source system and emits canonical records. It never
writes to ALL WR.

## The interface

Subclass `allwr_toolkit.connectors.base.SourceConnector` and implement:
`metadata()`, `capabilities()`, `validate_configuration()`, `inspect()`,
`iter_records()`, `get_record()`; optionally override `get_attachment()`,
`estimate()`, `health_check()`.

`metadata()` must declare: connector id, display name, source product,
stability, supported record types, auth modes, required/optional
configuration, known limitations, rate-limit strategy, attachment and
incremental support, and maintainer.

## Rules

- Convert every source error into a typed error from `core/errors.py`.
- Honor rate limits (`Retry-After` on 429, backoff on 5xx).
- Preserve source ids; never merge distinct ids; emitting a record twice
  must produce identical output.
- Report unsupported fields via `UnsupportedField` — never drop data
  silently.
- Read `src/allwr_toolkit/connectors/AGENTS.md`; it is binding.

## Distribution

Built-in connectors live in this repository. Third-party connectors can be
separate packages exposing an `allwr_toolkit.connectors` entry point;
installing one runs third-party code with your credentials, so users must
treat it like any dependency they trust. Start from the Asana connector as a
reference, add synthetic fixtures and contract tests like
`tests/contract/`, and open a **connector proposal** issue first.
