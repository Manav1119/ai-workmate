"""Approved analytical schema (the allowlist).

Only these tables and columns can appear in generated SQL. ``dataset_id`` is deliberately
absent: dataset isolation is enforced by row-level security on the read-only role, so
generated SQL never needs (and is not allowed) to reference it.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text

APPROVED_SCHEMA = "analytics"

APPROVED_TABLES: dict[str, dict[str, str]] = {
    "campaigns": {
        "campaign_id": "Campaign identifier (join key). One row per campaign.",
        "campaign_name": "Human-readable campaign name.",
        "platform": "Ad platform, e.g. 'Google Ads', 'Meta', 'TikTok', 'LinkedIn'.",
        "objective": "Campaign objective, e.g. 'Conversions', 'Leads', 'Sales', 'Awareness'.",
        "start_date": "Campaign start date.",
        "status": "'active' or 'paused'.",
    },
    "campaign_daily_metrics": {
        "date": "Reporting date in the dataset's reporting timezone. Grain: one row per campaign per date.",
        "campaign_id": "FK to campaigns.campaign_id.",
        "spend": "Media cost in USD (additive).",
        "impressions": "Ad impressions (additive).",
        "clicks": "Link clicks (additive).",
        "conversions": "Attributed conversion events, de-duplicated at source (additive).",
        "revenue": "Attributed conversion value in USD (additive).",
    },
}

RELATIONSHIPS = [
    "campaign_daily_metrics.campaign_id -> campaigns.campaign_id (many-to-one)",
]

# Fallback types used if information_schema is unavailable (e.g. unit tests without DB).
DEFAULT_TYPES: dict[str, dict[str, str]] = {
    "campaigns": {
        "campaign_id": "text", "campaign_name": "text", "platform": "text", "objective": "text",
        "start_date": "date", "status": "text",
    },
    "campaign_daily_metrics": {
        "date": "date", "campaign_id": "text", "spend": "numeric", "impressions": "bigint",
        "clicks": "bigint", "conversions": "bigint", "revenue": "numeric",
    },
}


@dataclass(frozen=True)
class Catalog:
    types: dict[str, dict[str, str]]

    def qualify_schema(self) -> dict:
        return {APPROVED_SCHEMA: {t: dict(cols) for t, cols in self.types.items()}}

    def describe(self) -> dict:
        return {
            "schema": APPROVED_SCHEMA,
            "tables": [
                {
                    "name": t,
                    "columns": [
                        {"name": c, "type": self.types[t][c], "description": APPROVED_TABLES[t][c]}
                        for c in APPROVED_TABLES[t]
                    ],
                }
                for t in APPROVED_TABLES
            ],
            "relationships": RELATIONSHIPS,
        }

    def prompt_text(self) -> str:
        lines = []
        for t, cols in APPROVED_TABLES.items():
            lines.append(f"TABLE {APPROVED_SCHEMA}.{t}")
            for c, desc in cols.items():
                lines.append(f"  - {c} {self.types[t][c]}: {desc}")
        lines.append("RELATIONSHIPS: " + "; ".join(RELATIONSHIPS))
        return "\n".join(lines)


def default_catalog() -> Catalog:
    return Catalog({t: dict(c) for t, c in DEFAULT_TYPES.items()})


def discover_catalog(conn) -> Catalog:
    """Schema discovery: read real column types for the approved tables, intersected with the allowlist."""
    rows = conn.execute(
        text(
            "SELECT table_name, column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = :s AND table_name = ANY(:t)"
        ),
        {"s": APPROVED_SCHEMA, "t": list(APPROVED_TABLES)},
    ).all()
    types: dict[str, dict[str, str]] = {t: {} for t in APPROVED_TABLES}
    for t, c, dt in rows:
        if c in APPROVED_TABLES.get(t, {}):
            types[t][c] = {"character varying": "text", "double precision": "float"}.get(dt, dt)
    for t, cols in APPROVED_TABLES.items():
        missing = set(cols) - set(types[t])
        if missing:
            raise RuntimeError(f"approved columns missing from database: {t}.{sorted(missing)}")
    return Catalog(types)
