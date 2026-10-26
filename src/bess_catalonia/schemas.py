"""Canonical data contracts.

Each schema lists the standardised columns a stage reads (``*_input``) or writes. The
human-readable version is docs/data_contract.md; a test checks that both stay in sync.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from bess_catalonia.quality import QualityReport


@dataclass(frozen=True)
class Field:
    name: str
    dtype: str  # string | float | int | bool | date | geometry
    required: bool = False
    unit: str | None = None
    description: str = ""


F = Field

SCHEMAS: dict[str, list[Field]] = {
    # ---------------------------------------------------------------- grid (Polo)
    "grid_input": [
        F("source_node_id", "string", True, None, "Identifier used by the source publication"),
        F("node_name", "string", False, None, "Node / substation name as published (defaults to source_node_id if absent)"),
        F("x", "float", True, "source CRS", "X / longitude in the dataset's source_crs"),
        F("y", "float", True, "source CRS", "Y / latitude in the dataset's source_crs"),
        F("operator", "string", False, None, "REE, EDIS (e-distribución), ..."),
        F("network_level", "string", False, None, "transmission | distribution"),
        F("voltage_kv", "float", False, "kV", "Nominal voltage"),
        F("generation_available_mw", "float", False, "MW", "Available generation access capacity"),
        F("demand_available_mw", "float", False, "MW", "Available demand access capacity"),
        F("generation_capacity_date", "string", False, None, "Publication date of gen. capacity"),
        F("demand_capacity_date", "string", False, None, "Publication date of demand capacity"),
    ],
    "grid_nodes": [
        F("node_id", "string", True, None, "Canonical identifier: <operator>-<source_node_id>"),
        F("source_node_id", "string", True, None, "Original source identifier (preserved)"),
        F("node_name", "string", True),
        F("operator", "string"),
        F("network_level", "string"),
        F("voltage_kv", "float", False, "kV"),
        F("generation_available_mw", "float", False, "MW"),
        F("demand_available_mw", "float", False, "MW"),
        F("bess_headroom_proxy_mw", "float", False, "MW",
          "min(generation, demand) available capacity - indicative screening proxy only"),
        F("headroom_note", "string", False, None, "Why the proxy is null, if it is"),
        F("lon", "float", True, "deg", "EPSG:4326 longitude"),
        F("lat", "float", True, "deg", "EPSG:4326 latitude"),
        F("geometry", "geometry", True, None, "Point, EPSG:25831"),
    ],
    # ---------------------------------------------------------------- demand (Fernando)
    "demand_input": [
        F("municipality_code", "string", True, None, "INE/Idescat 5-digit municipality code"),
        F("year", "int", True),
        F("consumption_mwh", "float", True, "MWh", "Annual electricity consumption"),
        F("municipality_name", "string"),
        F("sector_code", "string"),
        F("sector_name", "string"),
        F("province", "string"),
        F("comarca", "string"),
        F("source_note", "string", False, None, "Source remarks (e.g. statistical secrecy)"),
    ],
    "demand_municipal_summary": [
        F("municipality_code", "string", True),
        F("municipality_name", "string"),
        F("year", "int", True, None, "Latest year available for the municipality"),
        F("total_mwh", "float", False, "MWh", "Sum of published sector values"),
        F("industrial_mwh", "float", False, "MWh"),
        F("n_suppressed_sectors", "int", False, None, "Sectors withheld by the source"),
        F("total_is_lower_bound", "bool", False, None, "True when any sector was suppressed"),
    ],
    # ---------------------------------------------------------------- congestion (Hsiang Wei)
    "congestion_input": [
        F("source_node_name", "string", True, None, "Node name as published by the source"),
        F("period_start", "date", True, None, "Start of the observation period (month)"),
        F("erni_mwh", "float", True, "MWh", "Non-integrated renewable energy in the period"),
        F("source_node_id", "string", False, None, "Source identifier, if published"),
        F("network_level", "string", False, None, "transmission | distribution"),
    ],
    "node_matching": [
        F("congestion_source_key", "string", True, None, "source_node_id or name if no id"),
        F("source_node_id", "string"),
        F("source_node_name", "string", True),
        F("node_id", "string", False, None, "Matched canonical node (null if not matched)"),
        F("match_method", "string", True, None, "crosswalk | source_id | name | none"),
        F("match_status", "string", True, None, "matched | ambiguous | unmatched"),
        F("match_reliability", "string", True, None, "high | medium | none"),
        F("candidates", "string", False, None, "Candidate node_ids for ambiguous matches"),
    ],
    "congestion_node_summary": [
        F("node_id", "string", True),
        F("erni_12m_gwh", "float", False, "GWh", "ERNI in the 12-month reference window"),
        F("erni_total_gwh", "float", False, "GWh", "ERNI over the full observation period"),
        F("erni_months_observed", "int", False, None, "Months with data in the 12m window"),
        F("erni_window_start", "string"),
        F("erni_window_end", "string"),
        F("erni_match_method", "string", False, None, "How the record was linked to the node"),
        F("erni_source_keys", "string", False, None, "Source keys aggregated into this node"),
    ],
    # ---------------------------------------------------------------- renewables (Isabella)
    "renewables_input": [
        F("source_installation_id", "string", True),
        F("capacity_mw", "float", True, "MW", "Installed / planned capacity"),
        F("status", "string", True, None, "Source status, mapped via options.status_map"),
        F("x", "float", True, "source CRS"),
        F("y", "float", True, "source CRS"),
        F("installation_name", "string"),
        F("technology", "string"),
    ],
    "renewable_installations": [
        F("source_installation_id", "string", True),
        F("installation_name", "string"),
        F("technology", "string"),
        F("capacity_mw", "float", False, "MW"),
        F("status", "string", True, None, "Original status text"),
        F("status_category", "string", True, None, "operating | pipeline | unknown"),
        F("coord_valid", "bool", True, None, "False if outside region or unparseable"),
        F("duplicate_source_id", "bool", True),
        F("geometry", "geometry", True, None, "Point, EPSG:25831"),
    ],
    # ---------------------------------------------------------------- gis (Yuki)
    "gis_node_metrics": [
        F("node_id", "string", True),
        F("suitable_land_ha_5km", "float", False, "ha",
          "Suitable land-cover area minus hard constraints within 5 km (one column per buffer)"),
        F("protected_area_share_5km", "float", False, "fraction", "Share of 5 km buffer"),
        F("flood_zone_share_5km", "float", False, "fraction", "Share of 5 km buffer"),
        F("protected_area_conflict", "bool", False, None,
          "Protected area within the configured conflict distance"),
        F("flood_risk_at_node", "bool", False, None, "Node point inside a flood zone"),
        F("distance_to_major_road_km", "float", False, "km"),
    ],
    # ---------------------------------------------------------------- integration
    "integrated_nodes": [
        F("node_id", "string", True),
        F("node_name", "string", True),
        F("operator", "string"),
        F("network_level", "string"),
        F("voltage_kv", "float", False, "kV"),
        F("generation_available_mw", "float", False, "MW"),
        F("demand_available_mw", "float", False, "MW"),
        F("bess_headroom_proxy_mw", "float", False, "MW"),
        F("erni_12m_gwh", "float", False, "GWh"),
        F("erni_match_method", "string"),
        F("renewable_mw_10km", "float", False, "MW", "Operating capacity within radius"),
        F("renewable_pipeline_mw_10km", "float", False, "MW", "Pipeline capacity within radius"),
        F("nearby_demand_mwh_10km", "float", False, "MWh",
          "Area-weighted annual municipal demand within radius (proxy)"),
        F("nearby_industrial_demand_mwh_10km", "float", False, "MWh"),
        F("suitable_land_ha_5km", "float", False, "ha"),
        F("protected_area_conflict", "bool"),
        F("flood_risk_at_node", "bool"),
        F("distance_to_major_road_km", "float", False, "km"),
        F("dq_indicator_completeness", "float", False, "fraction",
          "Share of scoring indicators that are non-null for this node"),
        F("lon", "float", True, "deg"),
        F("lat", "float", True, "deg"),
        F("geometry", "geometry", True, None, "Point, EPSG:25831"),
    ],
    # ---------------------------------------------------------------- ML (Team)
    "ml_predictions": [
        F("node_id", "string", True),
        F("ml_label", "int", True, None, "1 if node has an operating renewable within label radius"),
        F("ml_opportunity_prob", "float", True, "0-1", "Random Forest predicted probability"),
        F("ml_opportunity", "bool", True, None,
          "True if probability ≥ threshold and no existing project nearby"),
    ],
    "ml_feature_importance": [
        F("feature", "string", True, None, "Indicator name"),
        F("importance", "float", True, None, "Mean decrease in impurity (Gini importance)"),
        F("rank", "int", True, None, "1 = most important feature"),
    ],
    # ---------------------------------------------------------------- scoring
    "scores": [
        F("node_id", "string", True),
        F("scenario", "string", True),
        F("score", "float", False, "0-1", "Weighted normalised score (illustrative)"),
        F("rank", "int", False, None, "1 = highest score; null if unranked"),
        F("weight_coverage", "float", True, "fraction", "Share of scenario weight with data"),
        F("missing_indicators", "string", False),
        F("excluded_reason", "string", False, None, "Why the node is unranked"),
    ],
}


def schema_columns(name: str) -> list[str]:
    return [f.name for f in SCHEMAS[name]]


def check_required(df: pd.DataFrame, schema: str, report: QualityReport) -> bool:
    """Record an error for each missing required column. Returns True if all present."""
    missing = [f.name for f in SCHEMAS[schema] if f.required and f.name not in df.columns]
    if missing:
        report.error(
            "required_columns",
            f"Missing required columns {missing}. Check the column mapping in "
            "config/datasets.yaml.",
        )
        return False
    report.info("required_columns", "All required columns present")
    return True


def parse_numbers(values: pd.Series, thousands: str | None = None, decimal: str | None = None):
    """Parse numbers written as text (e.g. Catalan ``2.555.460,5``). Blank -> null."""
    s = values.astype("string").str.strip()
    if thousands:
        s = s.str.replace(thousands, "", regex=False)
    if decimal and decimal != ".":
        s = s.str.replace(decimal, ".", regex=False)
    return pd.to_numeric(s.replace("", pd.NA), errors="coerce")


def coerce_types(
    df: pd.DataFrame,
    schema: str,
    report: QualityReport,
    number_format: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Cast schema columns to their declared types. Unparseable values become null and are
    reported - they are never silently replaced by zero."""
    df = df.copy()
    nf = number_format or {}
    for f in SCHEMAS[schema]:
        if f.name not in df.columns:
            continue
        col = df[f.name]
        if f.dtype in ("float", "int"):
            before = col.notna() & col.astype("string").str.strip().ne("").fillna(False)
            parsed = (
                parse_numbers(col, nf.get("thousands"), nf.get("decimal"))
                if col.dtype == object or pd.api.types.is_string_dtype(col)
                else pd.to_numeric(col, errors="coerce")
            )
            bad = int((before & parsed.isna()).sum())
            if bad:
                report.warning("type_coercion", f"{f.name}: {bad} value(s) not numeric -> null",
                               count=bad)
            df[f.name] = parsed.astype("Int64") if f.dtype == "int" else parsed.astype(float)
        elif f.dtype == "string":
            df[f.name] = col.astype("string").str.strip().replace("", pd.NA)
        elif f.dtype == "bool":
            df[f.name] = col.astype("boolean")
        elif f.dtype == "date":
            parsed = pd.to_datetime(col, errors="coerce")
            bad = int((col.notna() & parsed.isna()).sum())
            if bad:
                report.warning("type_coercion", f"{f.name}: {bad} unparseable date(s) -> null",
                               count=bad)
            df[f.name] = parsed
    return df


def order_columns(df: pd.DataFrame, schema: str) -> pd.DataFrame:
    """Schema columns first (in contract order), then any extra columns."""
    first = [c for c in schema_columns(schema) if c in df.columns]
    return df[first + [c for c in df.columns if c not in first]]
