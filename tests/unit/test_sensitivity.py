"""Weight-sensitivity checks."""

import numpy as np
import pandas as pd

from bess_catalonia.scoring.sensitivity import leave_one_out, rank_stability, run_all

CFG = {
    "indicators": {
        "a": {"direction": "higher_better", "normalization": "minmax", "missing": "reweight"},
        "b": {"direction": "higher_better", "normalization": "minmax", "missing": "reweight"},
    },
    "min_weight_coverage": 0.5,
    "exclude_if_true": [],
    "scenarios": {"s": {"weights": {"a": 0.8, "b": 0.2}}},
}


def _df():
    # N0 dominates on both indicators, so it should stay first under any perturbation.
    return pd.DataFrame({"node_id": [f"N{i}" for i in range(6)],
                         "a": [10, 8, 6, 4, 2, 0], "b": [10, 0, 2, 4, 6, 8]})


def test_rank_stability_keeps_a_dominant_node_on_top():
    out = rank_stability(_df(), CFG, "s", n_draws=50, rel=0.2, top_k=1)
    top = out.set_index("node_id").loc["N0"]
    assert top["base_rank"] == 1
    assert top["share_top_k"] == 1.0
    assert top["rank_p95"] == 1


def test_rank_stability_is_deterministic():
    a = rank_stability(_df(), CFG, "s", n_draws=20, seed=1)
    b = rank_stability(_df(), CFG, "s", n_draws=20, seed=1)
    pd.testing.assert_frame_equal(a, b)


def test_leave_one_out_reports_overlap():
    loo = leave_one_out(_df(), CFG, "s", top_k=2)
    assert set(loo["dropped_indicator"]) == {"a", "b"}
    assert loo["overlap"].between(0, 2).all()
    # Dropping the dominant indicator "a" leaves ranking by "b": N0 and N5 on top.
    row = loo.set_index("dropped_indicator").loc["a"]
    assert row["entered_top_k"] == "N5"


def test_run_all_shapes():
    stab, loo = run_all(_df(), CFG, n_draws=10, top_k=3)
    assert len(stab) == 6 and len(loo) == 2
    assert not np.isnan(stab["median_rank"]).any()
