# Security Policy

## Reporting a vulnerability

Please **do not open a public issue** for anything security-sensitive.

Use GitHub's private vulnerability reporting: on this repository, go to
**Security → Report a vulnerability**. Reports go directly and privately to
the maintainers.

What to include: affected version or commit, a minimal reproduction, the
impact you believe it has, and any suggested fix. We will acknowledge the
report, keep you informed, and credit you in the advisory unless you prefer
otherwise.

## Supported versions

Before 1.0.0, only the latest released version receives security fixes.

## Scope notes

Especially interesting to us:

- anything that makes the toolkit write to an unintended target;
- bypasses of the dry-run default, the plan hash verification or the MCP
  write gate (`ALLWR_MCP_ALLOW_WRITES`);
- credential leakage into logs, state files, reports or process arguments;
- unsafe handling of source-provided HTML or attachments.

## Handling of secrets and data

The toolkit takes credentials only from environment variables, redacts
secrets and personal identifiers from logs and reports, stores no tokens in
its state database, and sends data only to the configured source and target
APIs. There is no telemetry. If you observe behavior that contradicts any of
this, treat it as a vulnerability and report it privately.
