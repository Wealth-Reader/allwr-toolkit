# Instructions for AI agents working on connectors

Read the root `AGENTS.md` first; these rules are additional and specific to
`src/allwr_toolkit/connectors/`.

- A connector READS its source and emits canonical records. It never writes
  to ALL WR, never imports the execution engine, and never talks to the
  target API. If you need a write, it belongs in the execution engine behind
  a validated plan.
- Isolate the source completely: authentication, pagination, rate limiting
  and error conversion live inside the connector. Convert every source error
  into a typed error from `allwr_toolkit.core.errors`; never let raw
  exceptions escape.
- Respect rate limits: honor `Retry-After` on HTTP 429 and back off on 5xx.
  Never busy-loop.
- Preserve source identity: the source record id becomes the stable external
  reference. Never merge two records with distinct source ids, even when
  their titles are identical.
- Idempotency comes from stable identity, not from timing. Emitting the same
  record twice must produce identical canonical output.
- Declare capabilities honestly in `metadata()` and `capabilities()`. A
  limitation that is declared is a feature; a limitation that is silent is a
  data-loss bug.
- Unsupported source fields are reported through `UnsupportedField`, never
  dropped silently.
- Fixtures for connector tests are synthetic and sanitized: no real names,
  emails, ids, domains or ticket content. See `tests/AGENTS.md`.
