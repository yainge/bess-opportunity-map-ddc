"""ML opportunity classifier: out-of-fold scoring."""

import numpy as np
import pandas as pd

from bess_catalonia.ml.opportunity import train_and_predict

MODEL = {"n_estimators": 100, "random_state": 0, "class_weight": "balanced"}


def _nodes(n=40, seed=0):
    rng = np.random.default_rng(seed)
    x = rng.uniform(0, 1, n)
    nodes = pd.DataFrame({"node_id": [f"N{i}" for i in range(n)], "f1": x,
                          "f2": rng.uniform(0, 1, n)})
    labels = pd.Series((x > 0.5).astype(int))
    return nodes, labels


def test_out_of_fold_scores_can_flag_unlabelled_look_alikes():
    nodes, labels = _nodes()
    # A node that looks exactly like the positives but has no project nearby.
    look_alike = labels[nodes["f1"] > 0.9].index[0]
    labels.loc[look_alike] = 0
    preds, imp, metrics = train_and_predict(nodes, labels, ["f1", "f2"], MODEL, 0.5)
    assert metrics["cv_folds"] >= 2
    assert 0.0 <= metrics["cv_roc_auc"] <= 1.0
    assert bool(preds.loc[look_alike, "ml_opportunity"])
    assert imp.iloc[0]["feature"] == "f1"


def test_single_class_falls_back_without_crashing():
    nodes, _ = _nodes(10)
    labels = pd.Series(np.ones(10, dtype=int))
    preds, _, metrics = train_and_predict(nodes, labels, ["f1", "f2"], MODEL, 0.5)
    assert metrics["cv_folds"] == 0
    assert not preds["ml_opportunity"].any()
