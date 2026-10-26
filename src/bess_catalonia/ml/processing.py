"""ML stage: opportunity classifier trained on renewable developer siting decisions.

Requires upstream outputs from both ``integrate`` and ``renewables``.
"""

from __future__ import annotations

import geopandas as gpd

from bess_catalonia.io import write_csv
from bess_catalonia.ml.opportunity import make_labels, train_and_predict
from bess_catalonia.pipeline import RunContext, StageResult
from bess_catalonia.quality import QualityReport
from bess_catalonia.schemas import order_columns


def run(ctx: RunContext) -> StageResult:
    cfg = ctx.config.ml
    nodes = gpd.read_file(
        ctx.upstream_file("integrate", "nodes_integrated.gpkg"),
        layer="nodes_integrated",
    )
    inst = gpd.read_file(
        ctx.upstream_file("renewables", "renewable_installations.gpkg"),
        layer="renewable_installations",
    )

    report = QualityReport(dataset="ml_opportunity", stage="ml")

    label_cfg = cfg["label"]
    labels = make_labels(
        nodes,
        inst,
        radius_km=float(label_cfg["radius_km"]),
        status_category=str(label_cfg["status_category"]),
    )

    n_pos = int(labels.sum())
    n_neg = int((labels == 0).sum())
    report.metrics["labelled_positive"] = n_pos
    report.metrics["labelled_negative"] = n_neg

    if n_pos == 0:
        report.warning("no_positives",
                       "No operating renewable installations within label radius — "
                       "classifier predicts all zeros; results are illustrative only", 0)
    if n_neg == 0:
        report.warning("no_negatives",
                       "Every node has a nearby renewable project — "
                       "no latent opportunity nodes can be identified", 0)

    features = list(cfg["features"])
    present = [f for f in features if f in nodes.columns]
    absent = [f for f in features if f not in nodes.columns]
    if absent:
        report.warning("absent_features",
                       "Configured features absent from integrated data (model uses a subset)",
                       len(absent), absent)
    report.metrics["features_used"] = len(present)
    report.metrics["features_absent"] = len(absent)

    threshold = float(cfg.get("opportunity_threshold", 0.5))
    predictions, feat_imp = train_and_predict(
        nodes, labels, features, cfg["model"],
        opportunity_threshold=threshold,
    )

    n_opp = int(predictions["ml_opportunity"].sum())
    report.metrics["opportunity_nodes"] = n_opp
    report.info(
        "classifier",
        f"Random Forest trained on {len(nodes)} nodes "
        f"({n_pos} positive, {n_neg} negative); "
        f"{n_opp} opportunity node(s) above threshold {threshold}",
    )

    predictions = order_columns(predictions, "ml_predictions")
    feat_imp = order_columns(feat_imp, "ml_feature_importance")

    outputs = ctx.write_report(report)
    out = ctx.stage_dir("ml")
    outputs += [
        write_csv(predictions, out / "ml_predictions.csv"),
        write_csv(feat_imp, out / "ml_feature_importance.csv"),
    ]
    return StageResult(
        outputs=outputs,
        record_counts={
            "nodes": len(nodes),
            "opportunity_nodes": n_opp,
            "features_used": len(present),
        },
        warnings=report.warnings,
    )
