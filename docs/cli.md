# CLI reference

Global flags: `--json` (machine output), `--verbose`, `--debug` (warns that
extra operational metadata may be logged).

| Command | Purpose |
|---|---|
| `allwr-toolkit version` | Print the version |
| `allwr-toolkit doctor [--config F]` | Check setup and configuration |
| `allwr-toolkit connectors list` | List available connectors |
| `allwr-toolkit connectors describe <id>` | Capabilities, config, limitations |
| `allwr-toolkit migrate <id> inspect --config F` | Summarize the source (read-only) |
| `allwr-toolkit migrate <id> plan --config F --out P` | Build and save a plan |
| `allwr-toolkit migrate <id> apply --config F --plan P [--no-dry-run] [--yes]` | Dry-run (default) or apply |
| `allwr-toolkit migration status <run-id>` | Run status from state |
| `allwr-toolkit migration resume <run-id> --config F --plan P` | Resume from checkpoint |
| `allwr-toolkit migration cancel <run-id>` | Cancel; state stays resumable |
| `allwr-toolkit migration report <run-id> --plan P` | Generate the report bundle |
| `allwr-toolkit migration cleanup-plan <run-id>` | Print the cleanup manifest |
| `allwr-toolkit mcp serve` | Run the MCP server on stdio |

Secrets are never CLI arguments — see [authentication](authentication.md).
Exit codes are documented in [troubleshooting](troubleshooting.md).
