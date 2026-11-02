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
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import Pipeline

from bess_catalonia.gis.spatial import sum_points_within


def make_labels(
    nodes: gpd.GeoDataFrame,
    installations: gpd.GeoDataFrame,
    radius_km: float,
    status_category: str = "operating",
) -> pd.Series:
    """Binary label per node: 1 if ≥1 ``status_category`` installation is within ``radius_km``."""
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
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Fit a Random Forest on (nodes, labels) and score all nodes.

    Probabilities are out-of-fold (stratified k-fold): each node is scored by a model that
    did not see it during training. In-sample probabilities would mostly reproduce the
    training labels, so unlabelled nodes could never be flagged as opportunities.
    If either class has fewer than 2 members, cross-validation is impossible and the
    in-sample fit is used instead (``cv_folds`` = 0 in the returned metrics).

    Returns
    -------
    predictions : DataFrame
        node_id, ml_label, ml_opportunity_prob, ml_opportunity
    feature_importance : DataFrame
        feature, importance, rank (from a final model fitted on all trainable nodes)
    metrics : dict
        cv_folds and, when cross-validation ran, cv_roc_auc
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

    metrics: dict = {"cv_folds": 0}
    probs = np.full(len(nodes), np.nan)
    classes, counts = np.unique(y[trainable], return_counts=True)
    n_folds = int(min(5, counts.min())) if len(classes) == 2 else 0
    if n_folds >= 2:
        cv = StratifiedKFold(n_splits=n_folds, shuffle=True,
                             random_state=int(model_cfg.get("random_state", 42)))
        oof = cross_val_predict(pipe, X[trainable], y[trainable], cv=cv,
                                method="predict_proba")[:, 1]
        probs[trainable] = oof
        metrics["cv_folds"] = n_folds
        metrics["cv_roc_auc"] = round(float(roc_auc_score(y[trainable], oof)), 3)
    else:
        X_imp = pipe.named_steps["impute"].transform(X[trainable])
        in_sample = pipe.named_steps["clf"].predict_proba(X_imp)
        classes_ = list(pipe.named_steps["clf"].classes_)
        probs[trainable] = in_sample[:, classes_.index(1)] if 1 in classes_ else 0.0
    prob_col = pd.Series(np.round(probs, 4), index=nodes.index)

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

    return predictions, feat_imp, metrics
