# Security model

Non-negotiable principles, enforced by tests:

1. **Dry-run by default.** No command writes to ALL WR unless explicitly
   asked with `--no-dry-run` (plus confirmation or `--yes`).
2. **Plan-gated writes.** Apply requires a plan file; its SHA-256 hash and
   its target identity are re-verified immediately before writing.
3. **No implicit production target.** There is no default base URL; the
   declared environment is shown before apply.
4. **Idempotency.** Deterministic idempotency keys + server-side
   `external_ref` idempotency + local state. Re-runs do not duplicate.
5. **Resume, not restart.** Interruption and cancellation leave a resumable
   checkpointed state.
6. **No silent data loss.** Unsupported fields and skipped records are
   reported; high-severity warnings block apply unless explicitly accepted.
7. **Honest cleanup.** A deterministic manifest of created records; never a
   fake "full rollback".
8. **Safe retries.** Only transient failures retry; backoff with jitter;
   `Retry-After` honored; bounded attempts.
9. **Secrets hygiene.** Credentials only via environment variables; redacted
   from logs, errors and reports; never stored in state; state and report
   files are owner-only.
10. **MCP writes are opt-in on the server** — see [MCP](mcp.md).

Report vulnerabilities privately — see `SECURITY.md` in the repository root.
