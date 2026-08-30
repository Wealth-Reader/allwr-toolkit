# Reports

Every run (dry or real) can produce a report bundle:

| File | Content |
|---|---|
| `migration-plan.json` | The reviewed contract for the run |
| `migration-report.json` | Machine-readable results: counts, id map, errors, warnings |
| `migration-report.html` | The same, human-readable |
| `migration-errors.csv` | One row per failed operation |
| `migration-warnings.csv` | One row per warning |
| `migration-cleanup.json` | Records created by this run only |

The JSON report includes: run id, timestamps, toolkit and connector versions,
source and target identifiers, planned/created/replayed/skipped/failed
counts, attachments processed, unsupported fields, warnings, errors, the
source→target id map and cleanup information.

Reports **never** include task descriptions, ticket bodies, comments or
attachment contents, and all free text passes through redaction. Report
files are written with owner-only permissions. Treat them as sensitive
anyway: they contain identifiers.
