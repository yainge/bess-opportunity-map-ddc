"""Export stage: master GeoPackage, tables, maps and a run summary under results/<mode>/.

``results/<mode>/bess_master.gpkg`` is the file to open in QGIS (see qgis/README.md).
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd

from bess_catalonia.export.maps import (
    SYNTHETIC_NOTE,
    ml_opportunity_map_html,
    node_overview_map,
    node_overview_map_html,
    score_map,
    score_map_html,
)
from bess_catalonia.io import read_vector, write_csv, write_gpkg, write_text
from bess_catalonia.pipeline import RunContext, StageResult
from bess_catalonia.quality import QualityReport


def _context_layers(ctx: RunContext) -> dict[str, gpd.GeoDataFrame]:
    layers: dict[str, gpd.GeoDataFrame] = {}
    if ctx.has_output("gis"):
        path = ctx.upstream_file("gis", "gis_layers.gpkg")
        for name in gpd.list_layers(path)["name"]:
            layers[name] = gpd.read_file(path, layer=name)
    mun = ctx.config.spatial["municipalities"]["dataset"]
    if ctx.available(mun):
        layers["municipalities"] = read_vector(ctx.dataset(mun), ctx.config.analysis_crs,
                                               QualityReport(mun, "export"))
    acc = ctx.config.spatial["accessibility"]
    if ctx.available(acc["dataset"]):
        roads = read_vector(ctx.dataset(acc["dataset"]), ctx.config.analysis_crs,
                            QualityReport(acc["dataset"], "export"))
        if acc.get("class_column") in roads:
            roads = roads[roads[acc["class_column"]].isin(acc["major_classes"])]
        layers["roads"] = roads
    return layers


def summary_markdown(ctx: RunContext, nodes, scores) -> str:
    lines = [f"# Run summary ({ctx.mode})", "", f"Run id: `{ctx.run_id}`", ""]
    if ctx.mode == "demo":
        lines += [f"> **{SYNTHETIC_NOTE}.**", ""]
    lines += ["> Opportunity screening only. Scores use ILLUSTRATIVE weights "
              "(config/scoring.yaml) and are not validated findings.", "",
              f"- Nodes integrated: {len(nodes)}",
              f"- Mean indicator completeness: {nodes['dq_indicator_completeness'].mean():.0%}",
              ""]
    if scores is not None:
        for scen, g in scores.groupby("scenario", sort=False):
            top = g[g["rank"].notna()].sort_values("rank").head(10).merge(
                nodes[["node_id", "node_name"]], on="node_id")
            lines += [f"## {scen.replace('_', ' ').capitalize()}", "",
                      "| rank | node_id | node_name | score | weight coverage |",
                      "|---|---|---|---|---|"]
            lines += [f"| {int(r['rank'])} | {r.node_id} | {r.node_name} | {r.score:.3f} | "
                      f"{r.weight_coverage:.0%} |" for _, r in top.iterrows()]
            lines += ["", f"Unranked nodes: {int(g['rank'].isna().sum())}", ""]
    return "\n".join(lines)


def run(ctx: RunContext) -> StageResult:
    res = ctx.paths.results_root
    nodes = gpd.read_file(ctx.upstream_file("integrate", "nodes_integrated.gpkg"),
                          layer="nodes_integrated")
    scores = None
    if ctx.has_output("score"):
        scores = pd.read_csv(ctx.upstream_file("score", "scores_long.csv"))
        scores["rank"] = scores["rank"].astype("Int64")
    ml_preds = None
    if ctx.has_output("ml"):
        ml_preds = pd.read_csv(ctx.upstream_file("ml", "ml_predictions.csv"))
    context = _context_layers(ctx)

    layers = {"nodes_integrated": nodes}
    if scores is not None:
        for scen in scores["scenario"].unique():
            s = scores[scores["scenario"] == scen].drop(columns="scenario")
            layers[f"scores_{scen}"] = nodes[["node_id", "node_name", "geometry"]].merge(
                s, on="node_id")
    for name in ("suitable_land_net", "hard_constraints", "node_buffers"):
        if name in context:
            layers[name] = context[name]
    if ctx.has_output("renewables"):
        path = ctx.upstream_file("renewables", "renewable_installations.gpkg")
        layers["renewable_installations"] = gpd.read_file(path)
    if ml_preds is not None:
        ml_geo = nodes[["node_id", "node_name", "geometry"]].merge(ml_preds, on="node_id")
        layers["ml_opportunity"] = ml_geo

    outputs = [write_gpkg(layers, res / "bess_master.gpkg"),
               write_csv(nodes, res / "tables" / "nodes_integrated.csv")]
    if scores is not None:
        outputs.append(write_csv(scores, res / "tables" / "scores_long.csv"))
    maps = ctx.paths.maps_dir
    outputs.append(node_overview_map(nodes, context, ctx.mode, maps / "grid_nodes_overview.png"))
    outputs.append(node_overview_map_html(nodes, context, ctx.mode,
                                          maps / "grid_nodes_overview.html"))
    if scores is not None:
        for scen in scores["scenario"].unique():
            outputs.append(score_map(nodes, scores, scen, context, ctx.mode,
                                     maps / f"score_{scen}.png"))
            outputs.append(score_map_html(nodes, scores, scen, context, ctx.mode,
                                          maps / f"score_{scen}.html"))
    if ml_preds is not None:
        outputs.append(ml_opportunity_map_html(nodes, ml_preds, context, ctx.mode,
                                               maps / "ml_opportunity.html"))
    outputs.append(write_text(res / "summary.md", summary_markdown(ctx, nodes, scores)))
    n_maps = sum(p.suffix in (".png", ".html") for p in outputs)
    return StageResult(outputs=outputs,
                       record_counts={"gpkg_layers": len(layers), "maps": n_maps})
