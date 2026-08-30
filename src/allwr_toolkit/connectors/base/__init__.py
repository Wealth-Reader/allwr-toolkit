"""Connector SDK: the contract every source connector implements."""

from allwr_toolkit.connectors.base.registry import available_connectors, get_connector
from allwr_toolkit.connectors.base.sdk import (
    ConnectorCapabilities,
    ConnectorMetadata,
    InspectionSummary,
    SourceConnector,
)

__all__ = [
    "ConnectorCapabilities",
    "ConnectorMetadata",
    "InspectionSummary",
    "SourceConnector",
    "available_connectors",
    "get_connector",
]
