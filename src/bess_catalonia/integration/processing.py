"""Integration stage: one master dataset with one row per canonical grid node.

Grid nodes are the analytical unit. Every other domain is attached when its processed output
exists (partial integration); otherwise its columns stay null. Join logic:

* congestion  - attribute join on node_id via the auditable node_matching table
* gis         - attribute join on node_id
* renewables  - spatial: capacity of valid, de-duplicated installations within R km
* demand      - spatial, area-weighted: latest-year municipal demand x share of the
                municipality's area inside the R km buffer (needs the municipalities
                layer). Assumes demand is uniform within a municipality. A proxy for local
                demand, NOT nodal load; buffers of nearby nodes overlap.

Milestones (docs/methodology.md): M1 grid + ERNI, M2 + renewables & demand, M3 + land.
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd

from bess_catalonia.gis import spatial
from bess_catalonia.io import read_vector, write_csv, write_gpkg, write_parquet
from bess_catalonia.pipeline import RunContext, StageResult
from bess_catalonia.quality import QualityReport
from bess_catalonia.schemas import order_columns

DOMAINS = ("congestion", "renewables", "demand", "gis")


def normalise_municipality_code(codes: pd.Series) -> pd.Series:
    """Return 5-digit INE municipality codes.

    ICGC / Idescat boundaries use a 6-digit code (5-digit INE code + 1 check digit,
    e.g. 080018 for Abrera), while ICAEN demand uses the 5-digit INE code (08001).
    Six-digit codes lose their check digit; shorter codes are left-padded with zeros.
    """
    s = codes.astype("string").str.strip().str.replace(r"\.0$", "", regex=True)
    s = s.where(s.str.len() != 6, s.str[:5])
    return s.str.zfill(5)


def _join_attributes(nodes, table: pd.DataFrame, report: QualityReport, label: str):
    dup = table["node_id"].duplicated()
    if dup.any():
        report.error("duplicate_node_id", f"{label}: duplicate node_id in processed output",
                     int(dup.sum()))
        return nodes
    unknown = ~table["node_id"].isin(nodes["node_id"])
    if unknown.any():
        report.warning("unmatched", f"{label}: rows whose node_id is not a grid node (dropped)",
                       int(unknown.sum()), table.loc[unknown, "node_id"].tolist())
    cols = [c for c in table.columns if c != "node_id" and c not in nodes.columns]
    report.metrics[f"{label}_nodes_joined"] = int(table["node_id"].isin(nodes["node_id"]).sum())
    return nodes.merge(table[["node_id", *cols]], on="node_id", how="left")


def add_renewables(nodes, ctx: RunContext, radius_km: float, report: QualityReport):
    path = ctx.upstream_file("renewables", "renewable_installations.gpkg")
    inst = gpd.read_file(path, layer="renewable_installations")
    inst = inst[~inst["duplicate_source_id"].astype(bool)]
    tag = f"{int(radius_km) if float(radius_km).is_integer() else radius_km}km"
    for category, col in (("operating", f"renewable_mw_{tag}"),
                          ("pipeline", f"renewable_pipeline_mw_{tag}")):
        subset = inst[inst["status_category"] == category]
        nodes[col] = spatial.sum_points_within(nodes, subset, "capacity_mw", radius_km).values
    report.metrics["renewable_installations_used"] = len(inst)
    report.info("renewables", f"Capacity summed within {radius_km} km; overlapping catchments "
                "count an installation for every node in range")
    return nodes


def add_demand(nodes, ctx: RunContext, radius_km: float, report: QualityReport):
    mun_cfg = ctx.config.spatial["municipalities"]
    if not ctx.available(mun_cfg["dataset"]):
        report.warning("demand", "Municipal boundaries unavailable - demand cannot be placed "
                       "in space; nearby_demand columns left null")
        return nodes
    summary = pd.read_csv(ctx.upstream_file("demand", "demand_municipal_summary.csv"),
                          dtype={"municipality_code": str})
    mun = read_vector(ctx.dataset(mun_cfg["dataset"]), ctx.config.analysis_crs, report)
    code = mun_cfg["code_column"]
    mun[code] = normalise_municipality_code(mun[code])
    summary["municipality_code"] = normalise_municipality_code(summary["municipality_code"])
    joined = mun.merge(summary, left_on=code, right_on="municipality_code", how="left")
    no_demand = joined["total_mwh"].isna()
    report.metrics["demand_municipalities_matched"] = int((~no_demand).sum())
    if no_demand.all():
        report.error("demand_match", "No municipal boundary matched any demand row - check "
                     "that both sides use the same municipality code format",
                     int(no_demand.sum()), mun[code].head(5).tolist())
        return nodes
    if no_demand.any():
        report.warning("demand_match", "Municipalities without demand data", int(no_demand.sum()))
    orphan = ~summary["municipality_code"].isin(mun[code])
    if orphan.any():
        report.warning("demand_match", "Demand rows without a municipal boundary",
                       int(orphan.sum()), summary.loc[orphan, "municipality_code"].tolist())
    tag = f"{int(radius_km) if float(radius_km).is_integer() else radius_km}km"
    buffers = spatial.make_buffers(nodes, radius_km)
    nodes[f"nearby_demand_mwh_{tag}"] = spatial.area_weighted_sum(
        buffers, joined, "total_mwh").values
    nodes[f"nearby_industrial_demand_mwh_{tag}"] = spatial.area_weighted_sum(
        buffers, joined, "industrial_mwh").values
    report.metrics["demand_year"] = ",".join(str(y) for y in sorted(summary["year"].unique()))
    report.info("demand", "Municipal annual demand allocated by buffer area share (proxy; "
                "lower bound where sectors are suppressed or data is missing)")
    return nodes


def integrate(ctx: RunContext) -> tuple[gpd.GeoDataFrame, QualityReport]:
    report = QualityReport(dataset="integrated_nodes", stage="integrate")
    radius = float(ctx.config.project["integration"]["aggregation_radius_km"])
    nodes = gpd.read_file(ctx.upstream_file("grid", "grid_nodes.gpkg"), layer="grid_nodes")
    if nodes["node_id"].duplicated().any():
        report.error("duplicate_node_id", "Duplicate node_id in grid output")
        return nodes, report
    report.metrics["grid_nodes"] = len(nodes)
    included = ["grid"]

    if ctx.has_output("congestion"):
        summary = pd.read_csv(ctx.upstream_file("congestion", "congestion_node_summary.csv"))
        matching = pd.read_csv(ctx.upstream_file("congestion", "node_matching.csv"))
        nodes = _join_attributes(nodes, summary, report, "congestion")
        for status, n in matching["match_status"].value_counts().items():
            report.metrics[f"erni_source_nodes_{status}"] = int(n)
        included.append("congestion")
    if ctx.has_output("renewables"):
        nodes = add_renewables(nodes, ctx, radius, report)
        included.append("renewables")
    if ctx.has_output("demand"):
        before = set(nodes.columns)
        nodes = add_demand(nodes, ctx, radius, report)
        if set(nodes.columns) - before:
            included.append("demand")
    if ctx.has_output("gis"):
        metrics = pd.read_csv(ctx.upstream_file("gis", "gis_node_metrics.csv"))
        nodes = _join_attributes(nodes, metrics, report, "gis")
        included.append("gis")
    for d in DOMAINS:
        if d not in included:
            report.info("partial", f"Domain '{d}' not integrated (no processed output yet)")

    indicators = [c for c in ctx.config.scoring.get("indicators", {})]
    present = [c for c in indicators if c in nodes.columns]
    nodes["dq_indicator_completeness"] = (
        nodes[present].notna().sum(axis=1) / len(indicators) if indicators else 1.0).round(3)
    report.metrics["domains_included"] = ",".join(included)
    report.metrics["milestone"] = milestone(set(included))
    report.add_completeness(nodes, indicators)
    lineage = {d: (ctx.manifest(d) or {}).get("run_id") for d in ["grid", *DOMAINS]}
    report.metrics["upstream_runs"] = ", ".join(f"{k}={v}" for k, v in lineage.items() if v)
    nodes = order_columns(nodes, "integrated_nodes").sort_values("node_id")
    return gpd.GeoDataFrame(nodes.reset_index(drop=True), geometry="geometry"), report


def milestone(included: set[str]) -> str:
    if {"grid", "congestion", "renewables", "demand", "gis"} <= included:
        return "M3: grid + ERNI + renewables + demand + land feasibility"
    if {"grid", "congestion", "renewables", "demand"} <= included:
        return "M2: grid + ERNI + renewables + demand"
    if {"grid", "congestion"} <= included:
        return "M1: grid access + ERNI"
    return "M0: grid only (partial)"


def run(ctx: RunContext) -> StageResult:
    nodes, report = integrate(ctx)
    outputs = ctx.write_report(report)
    report.raise_if_errors()
    out = ctx.stage_dir("integrate")
    outputs += [write_gpkg({"nodes_integrated": nodes}, out / "nodes_integrated.gpkg"),
                write_csv(nodes, out / "nodes_integrated.csv"),
                write_parquet(nodes, out / "nodes_integrated.parquet")]
    return StageResult(outputs=outputs,
                       record_counts={"nodes": len(nodes), "columns": nodes.shape[1]},
                       warnings=report.warnings)
