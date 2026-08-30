# Cleanup and rollback

The toolkit is honest about rollback: it never claims to restore a previous
state. What it gives you is a **deterministic cleanup manifest** —
`migration-cleanup.json`, also available via
`allwr-toolkit migration cleanup-plan <run-id>` — listing exactly the records
created by that run and nothing else.

Deleting those records in ALL WR removes everything the migration created.
Records that already existed, or that were touched by other runs, are never
in the manifest.
