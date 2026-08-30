# ADR-0002: Canonical migration model and connector SDK

**Status**: accepted · **Date**: 2026-08-31

## Context

Mapping each source directly to ALL WR API calls couples every connector to
the target and loses audit information. The first two connectors (Asana,
Freshdesk) must not define a pattern that Jira/Trello/CSV cannot follow.

## Decision

Sources are translated into a canonical pydantic model
(`core/models.py`) that preserves source identity, timestamps, authors,
privacy flags and unsupported-field reports. Connectors implement a small
documented interface (`connectors/base/sdk.py`) and only read. Discovery
uses `importlib.metadata` entry points (`allwr_toolkit.connectors`) so
third-party connectors can ship as separate packages; loading one is
explicitly documented as a trust decision.

## Consequences

New connectors are additions, not restructurings. The execution engine has
exactly one write path to secure and test.
