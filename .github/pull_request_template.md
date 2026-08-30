## What and why

<!-- Problem being solved, approach taken. Link the issue: Fixes #NNN -->

## Security and privacy impact

<!-- Any change to credentials handling, redaction, data flows? "None" is fine. -->

## Migration behavior

- [ ] This PR changes migration behavior or mappings (explain above if checked)

## Checklist

- [ ] Tests added or updated for every behavior change
- [ ] Dry-run remains the default; apply remains plan-gated
- [ ] Idempotency preserved (re-runs do not duplicate)
- [ ] Resume from checkpoint preserved
- [ ] No silent data loss (unsupported data is reported)
- [ ] No secrets, credentials or real customer/employee data anywhere
- [ ] Fixtures are synthetic, English and sanitized
- [ ] Documentation updated for user-facing changes
- [ ] CHANGELOG.md updated if user-visible
- [ ] Backwards compatible, or an approved breaking-change issue is linked
- [ ] `make check` passes locally
- [ ] Connector limitations documented where applicable
- [ ] Commits are signed off (DCO, `git commit -s`)
