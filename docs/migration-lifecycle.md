# Migration lifecycle

Every migration follows the same cycle; no step reads and writes arbitrary
data in one opaque process.

1. **Inspect** — summarize the source (read-only, no target access).
2. **Validate** — configuration and connector checks.
3. **Plan** — build the canonical records and write `migration-plan.json`:
   run id, source and target identity, counts, operations, unsupported
   fields, warnings and a SHA-256 hash of the whole plan.
4. **Review** — a human reads the plan (and its warnings) before anything
   is written.
5. **Apply** — the engine executes the plan against ALL WR. Dry-run is the
   default; real writes verify the plan hash and target first.
6. **Verify** — results are checked against the plan and recorded in state.
7. **Report** — a report bundle is produced (see [reports](reports.md)).

State (SQLite) checkpoints every record, which is what makes
[resuming](resuming.md) and idempotent re-runs possible.
