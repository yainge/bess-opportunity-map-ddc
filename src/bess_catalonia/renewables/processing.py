"""Renewables stage (owner: Isabella): existing installations and development pipeline.

Each record keeps its source id and original status text; ``status_category`` separates
``operating`` capacity from the ``pipeline`` (authorised / in permitting) using
``options.status_map`` in datasets.yaml. Unmapped statuses become ``unknown`` and are
reported - they are never counted as operating.

Records with invalid coordinates are kept in the output with ``coord_valid = False`` and
excluded from spatial aggregation.
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd

from bess_catalonia.gis.spatial import add_lonlat, in_bbox
from bess_catalonia.io import Loaded, load_standardized, points_from_xy, write_csv, write_gpkg
from bess_catalonia.pipeline import RunContext, StageResult
from bess_catalonia.quality import QualityReport
from bess_catalonia.schemas import order_columns

DATASET = "renewables_installations"
DATASET_SOLAR = "renewables_solar"
DATASET_WIND = "renewables_wind"
CATEGORIES = ("operating", "pipeline")


def load(ctx: RunContext) -> Loaded:
    split_keys = [k for k in (DATASET_SOLAR, DATASET_WIND) if ctx.available(k)]
    if split_keys:
        parts = [load_standardized(ctx.dataset(k), "renewables", "renewables_input")
                 for k in split_keys]
        combined = pd.concat([p.data for p in parts], ignore_index=True)
        report = parts[0].report
        for extra in parts[1:]:
            report.issues.extend(extra.report.issues)
            report.metrics.update(extra.report.metrics)
        report.metrics["source_rows"] = len(combined)
        return Loaded(parts[0].spec, combined, report)
    return load_standardized(ctx.dataset(DATASET), "renewables", "renewables_input")


def _categorise(status: pd.Series, status_map: dict[str, str]) -> pd.Series:
    mapped = status.astype("string").str.strip().map(
        {str(k).strip(): v for k, v in status_map.items()})
    return mapped.where(mapped.isin(CATEGORIES), "unknown").fillna("unknown")


def _coords_valid(df: pd.DataFrame, crs: str | None, bbox, report) -> pd.Series:
    has = df["x"].notna() & df["y"].notna()
    valid = pd.Series(False, index=df.index)
    if has.any():
        pts = add_lonlat(points_from_xy(df[has], "x", "y", crs, report))
        valid.loc[has] = in_bbox(pts["lon"], pts["lat"], bbox).to_numpy()
    return valid


def validate(loaded: Loaded, ctx: RunContext) -> list[QualityReport]:
    df, report = loaded.data, loaded.report
    if report.has_errors:
        return [report]
    bbox = ctx.config.project["project"]["region_bbox_wgs84"]
    valid = _coords_valid(df, loaded.spec.source_crs, bbox, report)
    if (~valid).any():
        report.warning("coordinates", "Installations with missing/out-of-region coordinates "
                       "(kept, flagged, excluded from aggregation)", int((~valid).sum()),
                       df.loc[~valid, "source_installation_id"].tolist())
    dup = df["source_installation_id"].duplicated(keep=False)
    if dup.any():
        report.warning("duplicate_source_id", "Duplicate installation ids (first kept for "
                       "aggregation)", int(dup.sum()),
                       sorted(set(df.loc[dup, "source_installation_id"])))
    cat = _categorise(df["status"], loaded.spec.options.get("status_map", {}))
    unknown = cat == "unknown"
    if unknown.any():
        report.warning("status_map", "Statuses not in options.status_map -> 'unknown'",
                       int(unknown.sum()), sorted(set(df.loc[unknown, "status"].astype(str)),
                                                  key=str))
    if df["capacity_mw"].isna().any():
        report.warning("missing_values", "Installations without capacity (kept null)",
                       int(df["capacity_mw"].isna().sum()))
    if (df["capacity_mw"] < 0).any():
        report.error("negative_capacity", "Negative capacities",
                     int((df["capacity_mw"] < 0).sum()))
    report.metrics["installations"] = len(df)
    for c in CATEGORIES:
        report.metrics[f"{c}_mw"] = round(float(df.loc[cat == c, "capacity_mw"].sum()), 2)
    report.add_completeness(df)
    return [report]


def process(loaded: Loaded, ctx: RunContext) -> gpd.GeoDataFrame:
    cfg = ctx.config
    df = loaded.data.copy()
    df["status_category"] = _categorise(df["status"], loaded.spec.options.get("status_map", {}))
    df["coord_valid"] = _coords_valid(df, loaded.spec.source_crs,
                                      cfg.project["project"]["region_bbox_wgs84"],
                                      loaded.report)
    df["duplicate_source_id"] = df["source_installation_id"].duplicated(keep="first")
    gdf = points_from_xy(df, "x", "y", loaded.spec.source_crs, loaded.report)
    gdf = gdf.to_crs(cfg.analysis_crs).drop(columns=["x", "y"])
    gdf.loc[~gdf["coord_valid"], "geometry"] = None
    return gpd.GeoDataFrame(order_columns(gdf, "renewable_installations"), geometry="geometry")


def run(ctx: RunContext) -> StageResult:
    loaded = load(ctx)
    reports = validate(loaded, ctx)
    outputs = [p for r in reports for p in ctx.write_report(r)]
    for r in reports:
        r.raise_if_errors()
    inst = process(loaded, ctx)
    out = ctx.stage_dir("renewables")
    summary = (inst.groupby(["status_category", "technology"], dropna=False)["capacity_mw"]
               .agg(["count", "sum"]).reset_index()
               .rename(columns={"count": "installations", "sum": "capacity_mw"}))
    valid = inst[inst["coord_valid"]]
    table = pd.DataFrame(inst.drop(columns="geometry")).join(add_lonlat(valid)[["lon", "lat"]])
    outputs += [write_gpkg({"renewable_installations": valid},
                           out / "renewable_installations.gpkg"),
                write_csv(table, out / "renewable_installations.csv"),
                write_csv(summary, out / "renewables_summary.csv")]
    return StageResult(
        outputs=outputs,
        record_counts={"installations": len(inst),
                       "valid_coordinates": int(inst["coord_valid"].sum()),
                       "operating": int((inst.status_category == "operating").sum()),
                       "pipeline": int((inst.status_category == "pipeline").sum())},
        warnings=loaded.report.warnings,
    )
