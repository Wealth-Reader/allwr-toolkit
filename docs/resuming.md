# Resuming

An interrupted or cancelled run continues from its last checkpoint:

```bash
allwr-toolkit migration status <run-id> --state migration-state.db
allwr-toolkit migration resume <run-id> --config migration.yaml \
  --plan migration-plan.json --state migration-state.db
```

Resume re-verifies the same plan, then walks the plan again: records already
created are skipped locally (and would be answered as replays by the server
anyway), pending records are applied. A run interrupted at record 3,000 of
5,000 continues at 3,001 — it never restarts the import.

`migration cancel <run-id>` marks a run cancelled; it remains resumable
forever.
