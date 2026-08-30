# ADR-0006: Apache-2.0 license and DCO contribution model

**Status**: accepted (pending final legal sign-off) · **Date**: 2026-08-31

## Context

The project needs a permissive license that enterprises can adopt and a
low-friction inbound-rights mechanism.

## Decision

Apache License 2.0 (explicit patent grant, enterprise-friendly), copyright
Wealthreader S.L. Contributions under the Developer Certificate of Origin
(`git commit -s`) instead of a CLA — lower friction, adequate provenance.
"ALL WR" remains a Wealthreader trademark; "power tools" appears only as a
tagline, never as a product identity. All dependencies are
permissively licensed (MIT/BSD/Apache/PSF); no third-party notices file is
required yet.

## Consequences

If legal review ever requires a CLA, the DCO check is replaced, documented
in CONTRIBUTING and announced. License review is part of every release
checklist.
