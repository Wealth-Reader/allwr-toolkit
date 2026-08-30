# Privacy

- **No telemetry.** The toolkit sends data to exactly two places: the source
  API you configured and the ALL WR API you configured. Nothing else, ever.
- **TLS verified** by default; there is no generic `--insecure` switch.
- **Minimization.** Reports carry identifiers, not content; emails in logs
  and reports are masked; state stores no bodies and no tokens.
- **Local files.** Migration state and reports are written with owner-only
  permissions. Attachment temp files are cleaned up after upload; delete
  state and reports when the migration is accepted (they are inputs to
  nothing else).
- **Debug logging** may include additional operational metadata (never
  credentials); the CLI warns when `--debug` is on.
- **Repository policy.** No real customer or employee data may ever enter
  this repository — tests, fixtures, examples and docs use synthetic data
  only, and CI scans for violations.

Data retention is yours to manage: the toolkit keeps only what you see
(state file + reports) and deletes its own temporary files.
