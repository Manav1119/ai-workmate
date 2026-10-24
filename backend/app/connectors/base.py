"""Modular data-connector interface.

v1 ships two working connectors (seeded synthetic data and CSV upload). Planned
connectors are listed with status ``planned`` and are NOT implemented: the API and UI
show them as unavailable rather than pretending to connect.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class ConnectorInfo:
    key: str
    name: str
    status: Literal["available", "planned"]
    description: str
    auth: Literal["none", "oauth", "credentials"]


class DataConnector(Protocol):
    """Contract every connector implements.

    ``fetch`` must return rows at the documented grain (one row per campaign per
    reporting-timezone day) with the columns of analytics.campaign_daily_metrics, plus a
    campaigns table. Loading goes through the same validation as CSV imports.
    """

    info: ConnectorInfo

    def test_connection(self) -> bool: ...

    def fetch(self, start: str, end: str) -> tuple[list[dict], list[dict]]: ...


REGISTRY: list[ConnectorInfo] = [
    ConnectorInfo("synthetic_seed", "Synthetic demo data", "available",
                  "Deterministic synthetic marketing dataset (seed 20261018) with labelled ground-truth scenarios.", "none"),
    ConnectorInfo("csv_upload", "CSV upload", "available",
                  "Upload daily campaign metrics as CSV; validated, mapped and stored as a private dataset.", "none"),
    ConnectorInfo("meta_ads", "Meta Ads", "planned", "Not implemented in this version.", "oauth"),
    ConnectorInfo("google_ads", "Google Ads", "planned", "Not implemented in this version.", "oauth"),
    ConnectorInfo("postgres", "PostgreSQL / warehouse", "planned", "Not implemented in this version.", "credentials"),
]


def list_connectors() -> list[dict]:
    return [asdict(c) for c in REGISTRY]
