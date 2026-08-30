# ALL WR Toolkit

Open-source migration, integration and automation tools for
[ALL WR](https://www.allwr.io) - power tools for migrating, integrating and
automating ALL WR.

ALL WR is an Open Finance and business operations platform by Wealthreader.
This toolkit exists so that moving into ALL WR - and automating it - is
something anyone can do, audit and extend: it demonstrates that ALL WR is an
open platform you can migrate to, integrate with and automate through its
public API and its MCP interface.

## Components

| Component | Status | What it does |
|---|---|---|
| Asana Importer | Beta | Import projects, tasks, comments and attachments |
| Freshdesk Importer | Beta | Import tickets, contacts and conversations |
| CLI | Alpha | Plan and execute migrations |
| MCP Server | Alpha | Let AI agents inspect and operate migration workflows safely |

## Installation

Requires Python 3.11 or newer.

```bash
pip install allwr-toolkit           # once published; from source today:
pip install .
# with the MCP server:
pip install '.[mcp]'
```

## Quick start: a dry run

Migrations are configuration-driven and **dry-run by default**. Nothing is
written anywhere until you explicitly apply a validated plan.

```bash
# 1. Describe what the connector needs
allwr-toolkit connectors describe asana

# 2. Inspect the source (read-only)
allwr-toolkit migrate asana inspect --config migration.yaml

# 3. Build a plan (writes only the local plan file)
allwr-toolkit migrate asana plan --config migration.yaml --out migration-plan.json

# 4. Dry-run the plan: zero writes, full report
allwr-toolkit migrate asana apply --config migration.yaml --plan migration-plan.json
```

## Applying for real

```bash
allwr-toolkit migrate asana apply \
  --config migration.yaml \
  --plan migration-plan.json \
  --no-dry-run --yes
```

> **Safety warning.** `--no-dry-run` writes to the ALL WR tenant configured in
> `migration.yaml`. The toolkit shows the exact target (base URL, project,
> record and write counts) before writing, verifies the plan hash, is
> idempotent on re-runs, and can resume after interruption - but you are
> responsible for pointing it at the right tenant. There is no default target
> on purpose.

Credentials are provided through environment variables only (see
`.env.example`); they never go on the command line and are redacted from logs
and reports.

## Documentation

Full documentation lives in [`docs/`](docs/index.md): quickstart,
configuration, the migration lifecycle (Inspect → Validate → Plan → Review →
Apply → Verify → Report), connector guides and limitations, the MCP security
model, and how to write your own connector.

## Contributing

Contributions are welcome - from bug reports to new source connectors. Read
[CONTRIBUTING.md](CONTRIBUTING.md) first; AI agents must also follow
[AGENTS.md](AGENTS.md). Connector proposals have their own issue form.

## Reporting security issues

Please do not open public issues for vulnerabilities. Use GitHub's private
vulnerability reporting on this repository - see [SECURITY.md](SECURITY.md).

## License

[Apache License 2.0](LICENSE). Copyright Wealthreader S.L.
