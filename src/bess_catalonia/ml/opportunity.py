"""Random-Forest opportunity classifier (Option 1: learn from developer decisions).

Labels each grid node as 1 if it has an operating renewable installation within
``radius_km``, 0 otherwise. The classifier learns which grid/land indicators
correlate with those developer choices; feature importances become data-driven
weight suggestions; predicted probabilities identify nodes that look like
developer-chosen sites but have no project nearby yet.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline

from bess_catalonia.gis.spatial import sum_points_within


def make_labels(
    nodes: gpd.GeoDataFrame,
    installations: gpd.GeoDataFrame,
    radius_km: float,
    status_category: str = "operating",
) -> pd.Series:
    """Binary label per node: 1 if ≥1 installation of ``status_category`` is within ``radius_km``."""
    subset = installations[
        (installations["status_category"] == status_category)
        & installations["coord_valid"].astype(bool)
        & installations.geometry.notna()
    ].copy()
    subset["_one"] = 1.0
    counts = sum_points_within(nodes, subset, "_one", radius_km)
    return (counts > 0).astype(int).rename("ml_label")


def train_and_predict(
    nodes: pd.DataFrame,
    labels: pd.Series,
    feature_cols: list[str],
    model_cfg: dict,
    opportunity_threshold: float = 0.5,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fit a Random Forest on (nodes, labels) and score all nodes.

    Returns
    -------
    predictions : DataFrame
        node_id, ml_label, ml_opportunity_prob, ml_opportunity
    feature_importance : DataFrame
        feature, importance, rank
    """
    available = [c for c in feature_cols if c in nodes.columns]
    X = nodes[available].to_numpy(dtype=float)
    y = labels.to_numpy(dtype=int)

    trainable = ~np.all(np.isnan(X), axis=1)

    pipe = Pipeline([
        ("impute", SimpleImputer(strategy="median")),
        ("clf", RandomForestClassifier(
            n_estimators=int(model_cfg.get("n_estimators", 300)),
            random_state=int(model_cfg.get("random_state", 42)),
            class_weight=model_cfg.get("class_weight", "balanced"),
            n_jobs=-1,
        )),
    ])
    pipe.fit(X[trainable], y[trainable])

    X_imp = pipe.named_steps["impute"].transform(X)
    probs = pipe.named_steps["clf"].predict_proba(X_imp)
    pos_idx = list(pipe.named_steps["clf"].classes_).index(1)
    prob_col = pd.Series(np.round(probs[:, pos_idx], 4), index=nodes.index)

    predictions = pd.DataFrame({
        "node_id": nodes["node_id"],
        "ml_label": labels.to_numpy(dtype=int),
        "ml_opportunity_prob": prob_col.to_numpy(),
        "ml_opportunity": (
            (prob_col >= opportunity_threshold) & (labels == 0)
        ).astype(bool).to_numpy(),
    })

    importances = pipe.named_steps["clf"].feature_importances_
    feat_imp = (
        pd.DataFrame({"feature": available, "importance": np.round(importances, 6)})
        .sort_values("importance", ascending=False)
        .reset_index(drop=True)
    )
    feat_imp["rank"] = np.arange(1, len(feat_imp) + 1, dtype=int)

    return predictions, feat_imp
