# Applying

Apply consumes a previously generated plan:

```bash
allwr-toolkit migrate asana apply --config migration.yaml \
  --plan migration-plan.json [--no-dry-run] [--yes] \
  [--state migration-state.db] [--report-dir .]
```

- Without `--no-dry-run` it is a **dry run**: zero target writes, full report.
- With `--no-dry-run` the CLI prints the target confirmation (base URL,
  project, environment, record and write counts, attachments) and asks for
  confirmation; `--yes` is required for non-interactive use.
- Before writing anything the plan is re-verified: its hash must match its
  content, and its target must match the configuration. A tampered or stale
  plan is rejected.
- Every write carries a deterministic idempotency key derived from the source
  record id, and the ALL WR import API is idempotent on
  `(project, import_source, external_ref)` — so re-running an apply does not
  duplicate records, with the local state as a second guard.
- Rate limits are honored (`Retry-After`), transient errors retry with
  exponential backoff and jitter, permanent errors are reported and never
  blindly retried.
- Ctrl-C (or `migration cancel`) stops safely after the current atomic
  operation; the state stays resumable.
