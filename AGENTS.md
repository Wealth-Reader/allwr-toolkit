# Instructions for AI agents

These rules are imperative. If you are an AI agent (or a human using one),
follow them exactly. Nested files add rules for their subtree:
`src/allwr_toolkit/connectors/AGENTS.md` and `tests/AGENTS.md`.

## Before editing anything

- Read `README.md`, `CONTRIBUTING.md` and the ADRs in `docs/adr/` relevant to
  the area you touch.
- English only, everywhere in this repository: code, identifiers, comments,
  docstrings, docs, fixtures, commit messages, PR text.
- Python is the default language; do not introduce other runtimes without an
  approved ADR.

## Architecture invariants (do not break)

- Follow the existing layering: connectors → canonical model → mapping →
  planning → execution → state → reporting. Never bypass the canonical model.
- Connectors read sources; only the execution engine writes to ALL WR, always
  behind a validated plan.
- Dry-run is and stays the default. Apply requires an explicit plan and
  explicit confirmation.
- Do not add destructive behavior without a reviewed design (ADR + issue).
- MCP write tools stay disabled by default; never weaken the
  `ALLWR_MCP_ALLOW_WRITES` gate.
- Do not change the state schema without a schema-version migration.
- Never drop unsupported source data silently: report it.
- Preserve backwards compatibility unless an approved breaking-change issue
  says otherwise.

## Data and secrets (zero tolerance)

- Never add credentials, tokens, personal data, customer data or internal
  Wealthreader endpoints - in any file, including tests, fixtures, examples
  and docs. Use synthetic values (`example.com`, `Alex Doe`).
- Never run migrations against real systems during development or review.
- Never use production credentials; tests never make live API calls.
- Treat exports, state files and reports as sensitive; never commit them.
- Do not read or write files outside this repository and your test tmp dirs.

## Quality gates (never subvert them)

- Never weaken or delete a test to make CI pass.
- Never lower coverage thresholds without an approved issue.
- Never silence type errors broadly (no blanket `# type: ignore`, no
  moduleignores) - fix the types.
- Never disable security checks (bandit, pip-audit, CodeQL, audit scripts)
  without an approved issue.
- Do not edit generated files by hand (e.g. `dist/`, `site/`).
- Add or update tests with every behavior change; add a regression test with
  every bug fix. Update docs on user-facing changes and `CHANGELOG.md` when
  the change is user-visible.
- Pin or constrain new dependencies and justify them; major decisions get an
  ADR in `docs/adr/`.

## Setup and verification commands (run these, report results)

```bash
make setup            # once: venv + dependencies + pre-commit
make check            # lint, type-check, tests+coverage, security, docs, build
```

`make check` is the same set of checks CI enforces. Before declaring any work
complete: run it, report the commands you ran and their results, and do not
declare success while any required check fails. Keep PRs focused; no
unrelated refactors.
