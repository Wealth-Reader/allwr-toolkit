# Configuration

A migration is described by one YAML or TOML file, validated before anything
runs. See `examples/` for complete files.

```yaml
connector: asana          # which source connector
source: { ... }           # connector-specific (see the connector's page)
target:
  base_url: https://...   # REQUIRED, no default, https only
  project_id: 42
  section_open: 100       # optional section for open records
  section_done: 101       # optional section for completed records
  import_batch_id: 1      # optional ALL WR import batch
  environment: sandbox    # declared environment, shown before apply
mapping:
  users:                  # source user -> target user id
    - source_id: "1200000000000101"
      email: alex.doe@example.com
      target_user_id: 11
  statuses: { open: open }
  priorities: { urgent: high }
  on_unknown_user: "null" # null | skip | fail
options:
  include_completed: true
  include_attachments: true
  preserve_source_ids: true
  stop_on_data_loss: false   # escalates unsupported fields to blocking
  accepted_warnings: []      # warning codes you explicitly accept
```

Unknown keys are rejected (typos fail fast). Configuration never contains
secrets, so its hash can safely go into the plan.
