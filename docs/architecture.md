# Architecture

Layers, in data-flow order:

```text
source connector  ->  canonical model  ->  mapping  ->  planning
       |                                                  |
   (reads only)                                     migration-plan.json
                                                          |
        state (SQLite) <->  execution engine  ->  ALL WR API client
                                   |
                               reporting
```

- **Connectors** (`connectors/`) read a source faithfully: auth, pagination,
  rate limits, typed errors, capability declaration. They never write to
  ALL WR.
- **Canonical model** (`core/models.py`) is the neutral intermediate
  representation; nothing maps a source directly to API requests.
- **Mapping** (`core/mapping.py`) resolves users, statuses and priorities
  from configuration and records every decision.
- **Planning** (`core/planning.py`) turns canonical records into a hashed,
  reviewable plan.
- **Execution** (`core/execution.py`) is the only writer, always behind a
  verified plan, with idempotency, retries, cancellation and checkpoints.
- **State** (`core/state.py`) is a schema-versioned SQLite file holding ids,
  statuses and attempts — never tokens, never record bodies.
- **Reporting** (`core/reporting.py`) produces the bundle described in
  [reports](reports.md).
- **CLI and MCP** are thin shells over the same workflow functions, so both
  interfaces enforce identical safety rules.

Decisions and their reasons live in the [ADRs](adr/0001-python-and-tooling.md).
This layering is what makes future connectors (Jira, Trello, ClickUp,
Monday, Notion, Linear, Basecamp, Zendesk, HubSpot, CSV, JSON) additions,
not restructurings.
