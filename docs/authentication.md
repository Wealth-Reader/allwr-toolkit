# Authentication

All credentials come from environment variables. They are never accepted as
command-line arguments (process argument lists leak), never stored in the
migration state, and are redacted from logs and reports.

| Variable | Used by | Notes |
|---|---|---|
| `ALLWR_TOOLKIT_ALLWR_API_KEY` | target client | An ALL WR API key (`wrk_...`) with the `tasks:import` scope, created under Settings → API keys in your workspace |
| `ALLWR_TOOLKIT_ASANA_TOKEN` | asana connector (api mode) | Asana personal access token |
| `ALLWR_TOOLKIT_FRESHDESK_API_KEY` | freshdesk connector | Freshdesk API key |
| `ALLWR_MCP_ALLOW_WRITES` | MCP server | Must be exactly `true` to register write tools |

`.env.example` documents the same list; keep your real `.env` out of git (it
is ignored by default).
