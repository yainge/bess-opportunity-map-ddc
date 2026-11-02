"""Sensitivity of the illustrative scenario rankings to the chosen weights.

Two checks, both built on the pure ``score_scenario`` function:

* **Weight perturbation** - every weight is multiplied by an independent random factor in
  [1 - rel, 1 + rel] (default plus or minus 20%) for ``n_draws`` draws. For each node we
  report its base rank, the median and 5th-95th percentile of its rank across draws, and
  how often it stays in the top ``top_k``.
* **Leave one indicator out** - each indicator is dropped in turn and the top ``top_k``
  is compared with the base top ``top_k`` (overlap count and Jaccard index).

A node that stays near the top under both checks is a robust candidate; one that only
ranks well under the exact base weights depends on an assumption. Neither check makes the
weights "correct" - they show how much the ranking depends on them.
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from bess_catalonia.scoring.model import score_scenario


def _ranks(df: pd.DataFrame, weights: dict, cfg: dict, scenario: str) -> pd.Series:
    res = score_scenario(
        df, weights, cfg["indicators"],
        min_weight_coverage=float(cfg.get("min_weight_coverage", 0.5)),
        exclude_if_true=cfg.get("exclude_if_true", []),
        scenario=scenario,
    )
    return res.set_index("node_id")["rank"]


def rank_stability(df: pd.DataFrame, cfg: dict, scenario: str, n_draws: int = 500,
                   rel: float = 0.2, top_k: int = 10, seed: int = 42) -> pd.DataFrame:
    """Rank distribution per node under random multiplicative weight perturbation."""
    base_w = cfg["scenarios"][scenario]["weights"]
    base = _ranks(df, base_w, cfg, scenario)
    rng = np.random.default_rng(seed)
    names = list(base_w)
    draws = np.empty((n_draws, len(base)))
    for d in range(n_draws):
        factors = rng.uniform(1 - rel, 1 + rel, len(names))
        w = {n: base_w[n] * f for n, f in zip(names, factors, strict=True)}
        draws[d] = _ranks(df, w, cfg, scenario).reindex(base.index).astype(float).to_numpy()
    ranked = ~np.isnan(draws)
    with np.errstate(invalid="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN columns = unranked nodes
        out = pd.DataFrame({
            "node_id": base.index,
            "scenario": scenario,
            "base_rank": base.to_numpy(),
            "median_rank": np.nanmedian(np.where(ranked, draws, np.nan), axis=0),
            "rank_p05": np.nanpercentile(np.where(ranked, draws, np.nan), 5, axis=0),
            "rank_p95": np.nanpercentile(np.where(ranked, draws, np.nan), 95, axis=0),
            "share_top_k": ((draws <= top_k) & ranked).mean(axis=0).round(3),
        })
    out["top_k"] = top_k
    out["rel_perturbation"] = rel
    out["n_draws"] = n_draws
    return out.sort_values(["base_rank", "node_id"], na_position="last").reset_index(drop=True)


def leave_one_out(df: pd.DataFrame, cfg: dict, scenario: str, top_k: int = 10) -> pd.DataFrame:
    """Top-k overlap with the base ranking when each indicator is dropped in turn."""
    base_w = cfg["scenarios"][scenario]["weights"]
    base = _ranks(df, base_w, cfg, scenario)
    base_top = set(base[base <= top_k].index)
    rows = []
    for name in base_w:
        w = {n: v for n, v in base_w.items() if n != name}
        if not w:
            continue
        r = _ranks(df, w, cfg, scenario)
        top = set(r[r <= top_k].index)
        union = base_top | top
        rows.append({
            "scenario": scenario,
            "dropped_indicator": name,
            "dropped_weight": base_w[name],
            "top_k": top_k,
            "overlap": len(base_top & top),
            "jaccard": round(len(base_top & top) / len(union), 3) if union else np.nan,
            "entered_top_k": ";".join(sorted(top - base_top)),
            "left_top_k": ";".join(sorted(base_top - top)),
        })
    return pd.DataFrame(rows)


def run_all(df: pd.DataFrame, cfg: dict, **kwargs) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Both checks for every scenario in the scoring configuration."""
    top_k = kwargs.get("top_k", 10)
    stab = [rank_stability(df, cfg, s, **kwargs) for s in cfg["scenarios"]]
    loo = [leave_one_out(df, cfg, s, top_k=top_k) for s in cfg["scenarios"]]
    return pd.concat(stab, ignore_index=True), pd.concat(loo, ignore_index=True)
