"""Connector discovery: built-ins plus ``allwr_toolkit.connectors`` entry points."""

from __future__ import annotations

from collections.abc import Iterable
from importlib import metadata as importlib_metadata

from allwr_toolkit.connectors.base.sdk import SourceConnector
from allwr_toolkit.core.errors import ConfigurationError

ENTRY_POINT_GROUP = "allwr_toolkit.connectors"


def _builtin_connectors() -> dict[str, type[SourceConnector]]:
    # Imported lazily to avoid import cycles.
    from allwr_toolkit.connectors.asana.connector import AsanaConnector
    from allwr_toolkit.connectors.freshdesk.connector import FreshdeskConnector

    return {"asana": AsanaConnector, "freshdesk": FreshdeskConnector}


def available_connectors() -> dict[str, type[SourceConnector]]:
    """All discoverable connectors, keyed by connector id.

    Entry points let third parties ship connectors as separate packages; a
    built-in with the same id always wins to prevent shadowing.
    """
    connectors: dict[str, type[SourceConnector]] = {}
    entry_points: Iterable[importlib_metadata.EntryPoint]
    try:
        entry_points = importlib_metadata.entry_points(group=ENTRY_POINT_GROUP)
    except Exception:  # pragma: no cover - defensive against broken metadata
        entry_points = ()
    for entry_point in entry_points:
        try:
            loaded = entry_point.load()
        except Exception:  # noqa: S112 # nosec B112 # pragma: no cover - broken plugin tolerated
            continue
        if isinstance(loaded, type) and issubclass(loaded, SourceConnector):
            connectors[entry_point.name] = loaded
    connectors.update(_builtin_connectors())
    return connectors


def get_connector(connector_id: str) -> type[SourceConnector]:
    connectors = available_connectors()
    if connector_id not in connectors:
        known = ", ".join(sorted(connectors))
        raise ConfigurationError(f"unknown connector '{connector_id}' (available: {known})")
    return connectors[connector_id]
