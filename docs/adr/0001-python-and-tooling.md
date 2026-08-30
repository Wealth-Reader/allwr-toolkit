# ADR-0001: Python 3.11+, src layout and tooling selection

**Status**: accepted · **Date**: 2026-08-31

## Context

The toolkit must be installable everywhere ALL WR customers run tooling,
attractive to external contributors, and safe to maintain.

## Decision

Python ≥3.11 (`tomllib`, modern typing), `src/` layout, PEP 621
`pyproject.toml`. Runtime dependencies kept minimal and boring: `httpx`
(HTTP), `pydantic` v2 (validated models), `typer` (CLI), `PyYAML` (config).
Development tooling: `ruff` (format+lint), `mypy --strict`, `pytest` +
`pytest-cov` + `respx` + `hypothesis`, `bandit`, `pip-audit`, `pre-commit`,
`build`+`twine`, `mkdocs-material`. Each was chosen for maintenance health,
license compatibility (all permissive) and real value — not popularity.
`uv` is a developer convenience, never an installation requirement.

## Consequences

CI runs a 3.11–3.14 matrix. No Node/JS anywhere in the toolchain.
