"""Grid stage (owner: Polo): nodes, coordinates, voltage and access capacity.

Output ``<processed>/grid/grid_nodes.{gpkg,csv}`` - the canonical node list every other stage
joins onto. Headroom proxy:

    bess_headroom_proxy_mw = min(generation_available_mw, demand_available_mw)

computed only when both values exist, are non-negative and (if capacity dates are given)
refer to the same publication date. It is an indicative bidirectional screening metric -
NOT a guarantee that a BESS of that size can connect (see docs/assumptions.md).
"""

from __future__ import annotations

import re

import geopandas as gpd
import numpy as np
import pandas as pd

from bess_catalonia.gis.spatial import add_lonlat, in_bbox
from bess_catalonia.io import Loaded, load_standardized, points_from_xy, write_csv, write_gpkg
from bess_catalonia.pipeline import RunContext, StageResult
from bess_catalonia.quality import QualityReport
from bess_catalonia.schemas import order_columns, schema_columns

DATASET = "grid_nodes"


def slug(value) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", str(value).upper()).strip("_")


def load(ctx: RunContext) -> Loaded:
    loaded = load_standardized(ctx.dataset(DATASET), "grid", "grid_input")
    if "node_name" not in loaded.data.columns and "source_node_id" in loaded.data.columns:
        loaded.data["node_name"] = loaded.data["source_node_id"]
    return loaded


def _canonical_ids(df: pd.DataFrame, default_operator: str) -> pd.Series:
    op = df["operator"] if "operator" in df else pd.Series(pd.NA, index=df.index)
    op = op.astype("string").fillna(default_operator).map(slug)
    return op + "-" + df["source_node_id"].astype("string").map(slug)


def validate(loaded: Loaded, ctx: RunContext) -> list[QualityReport]:
    df, report = loaded.data, loaded.report
    if report.has_errors:
        return [report]
    cfg = ctx.config
    ids = _canonical_ids(df, cfg.project["grid"]["default_operator"])
    canon = [c for c in schema_columns("grid_input") if c in df.columns]
    exact_dupes = df.duplicated(subset=canon)
    if exact_dupes.any():
        report.warning("duplicate_rows", "Exact duplicate rows will be dropped",
                       int(exact_dupes.sum()), ids[exact_dupes].tolist())
    conflicting = ids[~exact_dupes].duplicated(keep=False)
    if conflicting.any():
        report.error("duplicate_node_id",
                     "Same node_id with different attributes - resolve in the source/mapping",
                     int(conflicting.sum()), sorted(set(ids[~exact_dupes][conflicting])))
    names = df.loc[~exact_dupes, "node_name"].astype("string").str.upper()
    dup_names = names.duplicated(keep=False)
    if dup_names.any():
        report.warning("duplicate_names",
                       "Several nodes share a name; names must not be used as identifiers",
                       int(dup_names.sum()), sorted(set(names[dup_names])))
    no_xy = df["x"].isna() | df["y"].isna()
    if no_xy.any():
        report.warning("missing_coordinates", "Nodes without coordinates will be dropped",
                       int(no_xy.sum()), ids[no_xy].tolist())
    if not no_xy.all():
        pts = add_lonlat(points_from_xy(df[~no_xy], "x", "y", loaded.spec.source_crs, report))
        outside = ~in_bbox(pts["lon"], pts["lat"], cfg.project["project"]["region_bbox_wgs84"])
        if outside.mean() > 0.5:
            report.error("coordinates_region",
                         f"{int(outside.sum())}/{len(pts)} nodes fall outside Catalonia - "
                         "is source_crs correct?")
        elif outside.any():
            report.warning("coordinates_region", "Nodes outside the Catalonia bbox dropped",
                           int(outside.sum()), ids[~no_xy][outside.to_numpy()].tolist())
    for col in ("generation_available_mw", "demand_available_mw"):
        if col in df:
            neg = df[col] < 0
            if neg.any():
                report.warning("negative_capacity", f"{col}: negative values set to null",
                               int(neg.sum()), ids[neg.fillna(False)].tolist())
            report.metrics[f"{col}_missing"] = int(df[col].isna().sum())
    report.metrics["nodes_in_source"] = len(df)
    return [report]


def headroom_proxy(df: pd.DataFrame, require_same_date: bool) -> tuple[pd.Series, pd.Series]:
    gen = df.get("generation_available_mw", pd.Series(np.nan, index=df.index))
    dem = df.get("demand_available_mw", pd.Series(np.nan, index=df.index))
    note = pd.Series("", index=df.index, dtype="string")
    note[gen.isna() | dem.isna()] = "generation or demand capacity missing"
    ok = gen.notna() & dem.notna() & (gen >= 0) & (dem >= 0)
    if require_same_date and {"generation_capacity_date", "demand_capacity_date"} <= set(df):
        gd, dd = df["generation_capacity_date"], df["demand_capacity_date"]
        differ = gd.notna() & dd.notna() & (gd != dd)
        note[ok & differ] = "capacity publication dates differ - values not comparable"
        ok &= ~differ
    proxy = pd.Series(np.where(ok, np.minimum(gen, dem), np.nan), index=df.index)
    return proxy, note.replace("", pd.NA)


def process(loaded: Loaded, ctx: RunContext) -> gpd.GeoDataFrame:
    cfg = ctx.config
    df = loaded.data.copy()
    canon = [c for c in schema_columns("grid_input") if c in df.columns]
    df = df.drop_duplicates(subset=canon)
    df = df[df["x"].notna() & df["y"].notna()]
    df["node_id"] = _canonical_ids(df, cfg.project["grid"]["default_operator"])
    if "operator" not in df:
        df["operator"] = cfg.project["grid"]["default_operator"]
    for col in ("generation_available_mw", "demand_available_mw"):
        if col in df:
            df.loc[df[col] < 0, col] = np.nan
    df["bess_headroom_proxy_mw"], df["headroom_note"] = headroom_proxy(
        df, cfg.project["grid"]["require_same_capacity_date"])
    gdf = points_from_xy(df, "x", "y", loaded.spec.source_crs, loaded.report)
    gdf = add_lonlat(gdf, cfg.geographic_crs)
    gdf = gdf[in_bbox(gdf["lon"], gdf["lat"], cfg.project["project"]["region_bbox_wgs84"])]
    gdf = gdf.to_crs(cfg.analysis_crs).drop(columns=["x", "y"])
    gdf = gdf.sort_values("node_id").reset_index(drop=True)
    return gpd.GeoDataFrame(order_columns(gdf, "grid_nodes"), geometry="geometry")


def run(ctx: RunContext) -> StageResult:
    loaded = load(ctx)
    reports = validate(loaded, ctx)
    outputs = [p for r in reports for p in ctx.write_report(r)]
    for r in reports:
        r.raise_if_errors()
    nodes = process(loaded, ctx)
    out = ctx.stage_dir("grid")
    outputs += [write_gpkg({"grid_nodes": nodes}, out / "grid_nodes.gpkg"),
                write_csv(nodes, out / "grid_nodes.csv")]
    return StageResult(
        outputs=outputs,
        record_counts={"nodes": len(nodes),
                       "with_headroom_proxy": int(nodes["bess_headroom_proxy_mw"].notna().sum())},
        warnings=loaded.report.warnings,
    )
