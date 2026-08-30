# Freshdesk connector

Imports Freshdesk tickets (open, closed and archived-equivalent),
conversations, contacts, companies and attachments into ALL WR.

## Configuration

```yaml
connector: freshdesk
source:
  domain: yourcompany     # yourcompany.freshdesk.com
  include_closed: true
```

API key via `ALLWR_TOOLKIT_FRESHDESK_API_KEY`.

## Behavior decisions

- **Private notes stay private**: the public/private flag of every
  conversation is preserved and private notes map to internal-only comments.
- **No emails to requesters**: importing only reads Freshdesk (GET) and
  writes to ALL WR — it cannot trigger Freshdesk notifications.
- **No impersonation**: when an author cannot be mapped to an ALL WR user,
  the original author is preserved as explicit legacy metadata.
- Source ticket ids and URLs are preserved as stable external references.
- Statuses and priorities map via configuration; resolved/closed tickets
  become completed tasks.
- Attachments are streamed to disk (never fully in memory) with size
  verification; download failures are reported and never corrupt the
  migration state.
- Deleted contacts and agents are tolerated (preserved by id).
- HTML bodies are sanitized with an allowlist (scripts, styles, event
  handlers and unsafe URLs removed).

## Limitations

CC recipients cannot be represented on the target task and are reported as
unsupported. Freshdesk custom fields are preserved as source metadata only.
