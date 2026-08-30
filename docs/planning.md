# Planning

`allwr-toolkit migrate <connector> plan --config ... --out migration-plan.json`

The plan is the contract for apply. It contains: run id, creation time,
toolkit and connector versions, source identity (system + scope), target
identity (base URL, project, sections, environment), configuration hash,
counts, selected and excluded record ids, duplicate suspects, unsupported
fields, warnings with severities, the exact expected API operations with
their idempotency keys, an attachment volume estimate, and the plan hash.

## Warnings and blocking

- `info` and `medium` warnings inform; they never block.
- `high` warnings **block apply** unless their code is listed in
  `options.accepted_warnings`. Accepting a code is a per-configuration,
  auditable decision.

## Duplicate suspects

Records sharing a title are listed as suspects for your review, but they are
**never merged**: distinct source ids stay distinct records by design.
