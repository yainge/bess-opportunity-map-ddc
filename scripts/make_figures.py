"""Presentation figures from the real-mode results (static PNGs for slides).

Usage:
    uv run python scripts/sensitivity.py --mode real      # first, for the sensitivity tables
    uv run python scripts/make_figures.py --mode real

Writes <results_root>/figures/*.png. Scores use ILLUSTRATIVE weights (config/scoring.yaml);
every figure says so. Colors follow a validated colorblind-safe categorical palette.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import yaml  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
BLUE, ORANGE, MUTED = "#2a78d6", "#eb6834", "#a3a29b"
BLUES = ["#dbe9fa", "#a9cbf2", "#6fa6e6", "#2a78d6", "#1b56a0"]
SCEN = {"renewable_absorption": "Renewable absorption",
        "connection_readiness": "Connection readiness",
        "load_grid_support": "Load and grid support"}
FEAT = {"suitable_land_ha_5km": "Suitable land within 5 km",
        "nearby_demand_mwh_10km": "Nearby demand within 10 km",
        "distance_to_major_road_km": "Distance to major road",
        "generation_available_mw": "Generation access capacity",
        "demand_available_mw": "Demand access capacity",
        "bess_headroom_proxy_mw": "BESS headroom proxy",
        "erni_12m_gwh": "ERNI (no data yet)",
        "renewable_mw_10km": "Operating renewables, 10 km",
        "renewable_pipeline_mw_10km": "Pipeline renewables, 10 km"}
NOTE = "Illustrative weights, not validated. Screening only, not a connection or siting study."
ML_NOTE = ("Exploratory. The label is where renewables were built, not where batteries add "
           "value. Nearby nodes are correlated, so the AUC is optimistic.")

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "font.family": "DejaVu Sans", "font.size": 10, "text.color": INK,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": False,
})


def node_label(node_id: str) -> str:
    return node_id.replace("REE-", "").replace("_", " ").title().replace("Asc ", "Ascó ")


def _finish(fig, title: str, subtitle: str, path: Path, note: str = NOTE) -> Path:
    h = fig.get_figheight()
    fig.suptitle(title, x=0.01, y=1 - 0.08 / h, ha="left", va="top", fontsize=14,
                 fontweight="bold")
    fig.text(0.01, 1 - 0.42 / h, subtitle, ha="left", va="top", fontsize=10, color=INK2)
    fig.text(0.01, 0.06 / h, note, ha="left", va="bottom", fontsize=8, color=INK2)
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return path


def rank_stability(stab: pd.DataFrame, out: Path) -> Path:
    fig, axes = plt.subplots(1, 3, figsize=(13, 5.2), sharex=True)
    fig.subplots_adjust(left=0.13, right=0.99, top=0.8, bottom=0.12, wspace=0.75)
    for ax, (key, title) in zip(axes, SCEN.items(), strict=True):
        g = stab[(stab.scenario == key)].dropna(subset=["base_rank"]).nsmallest(10, "base_rank")
        y = np.arange(len(g))[::-1]
        ax.hlines(y, g.rank_p05, g.rank_p95, color=BLUE, lw=2, alpha=0.45)
        ax.scatter(g.median_rank, y, s=36, color=BLUE, zorder=3, edgecolor=SURFACE, lw=2)
        ax.set_yticks(y, [node_label(n) for n in g.node_id])
        ax.set_title(title, loc="left", fontsize=11, color=INK)
        ax.set_xlim(0.5, 17)
        ax.xaxis.grid(True, color=GRID, lw=0.8)
        ax.set_axisbelow(True)
        ax.set_xlabel("Rank (1 = best)")
    return _finish(fig, "Top 10 rankings barely move when weights change by ±20%",
                   "Dot = median rank over 500 random weight draws, line = 5th to 95th "
                   "percentile", out / "fig_rank_stability.png")


def leave_one_out(loo: pd.DataFrame, out: Path) -> Path:
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.6))
    fig.subplots_adjust(left=0.165, right=0.98, top=0.78, bottom=0.16, wspace=1.15)
    for ax, (key, title) in zip(axes, SCEN.items(), strict=True):
        g = loo[loo.scenario == key].sort_values("overlap")
        y = np.arange(len(g))
        colors = [MUTED if d == "erni_12m_gwh" else BLUE for d in g.dropped_indicator]
        ax.barh(y, g.overlap, color=colors, height=0.6)
        for yi, v in zip(y, g.overlap, strict=True):
            ax.text(v + 0.2, yi, f"{v}/10", va="center", fontsize=9, color=INK2)
        ax.set_yticks(y, [FEAT.get(d, d) for d in g.dropped_indicator])
        ax.set_xlim(0, 11.5)
        ax.set_xticks([0, 5, 10])
        ax.set_title(title, loc="left", fontsize=11, color=INK)
        ax.set_xlabel("Top-10 nodes kept")
    return _finish(fig, "But dropping one indicator can reshuffle the top 10",
                   "Nodes still in the top 10 when each indicator is removed. "
                   "ERNI changes nothing because it has no data yet.",
                   out / "fig_leave_one_out.png")


def robust_nodes(scores: pd.DataFrame, out: Path) -> Path:
    s = scores.dropna(subset=["rank"])
    top_any = s[s["rank"] <= 10].node_id.unique()
    m = (s[s.node_id.isin(top_any)].pivot(index="node_id", columns="scenario", values="rank")
         .reindex(columns=list(SCEN)))
    m = m.loc[m.apply(lambda r: (r <= 10).sum() * 100 - r.fillna(200).mean(), axis=1)
              .sort_values(ascending=False).index]
    h = 0.32 * len(m) + 1.9
    fig, ax = plt.subplots(figsize=(8.5, h))
    fig.subplots_adjust(left=0.3, right=0.98, top=1 - 1.25 / h, bottom=0.35 / h)
    bins = [0, 3, 10, 20, 40, 1e9]
    for i, (_node, row) in enumerate(m.iterrows()):
        for j, val in enumerate(row):
            if np.isnan(val):
                ax.add_patch(plt.Rectangle((j, i), 0.96, 0.9, color=GRID))
                ax.text(j + 0.48, i + 0.45, "excl.", ha="center", va="center", fontsize=8,
                        color=INK2)
                continue
            k = int(np.digitize(val, bins)) - 1
            col = BLUES[::-1][k]
            ax.add_patch(plt.Rectangle((j, i), 0.96, 0.9, color=col))
            ax.text(j + 0.48, i + 0.45, int(val), ha="center", va="center", fontsize=9,
                    color=SURFACE if k <= 1 else INK)
    ax.set_xlim(0, 3)
    ax.set_ylim(len(m), 0)
    ax.set_xticks(np.arange(3) + 0.48, list(SCEN.values()))
    ax.xaxis.tick_top()
    ax.set_yticks(np.arange(len(m)) + 0.45, [node_label(n) for n in m.index])
    ax.tick_params(length=0)
    for sp in ax.spines.values():
        sp.set_visible(False)
    return _finish(fig, "Which nodes rank well in more than one scenario?",
                   "Rank of every node that reaches a top 10. "
                   "Shades: 1-3, 4-10, 11-20, 21-40, 41+. excl. = excluded",
                   out / "fig_robust_nodes.png")


def ml_importance(imp: pd.DataFrame, out: Path) -> Path:
    g = imp.sort_values("importance")
    fig, ax = plt.subplots(figsize=(8, 4))
    fig.subplots_adjust(left=0.33, right=0.95, top=0.8, bottom=0.2)
    ax.barh([FEAT.get(f, f) for f in g.feature], g.importance, color=BLUE, height=0.6)
    for yi, v in enumerate(g.importance):
        ax.text(v + 0.005, yi, f"{v:.2f}", va="center", fontsize=9, color=INK2)
    ax.set_xlabel("Random Forest feature importance")
    return _finish(fig, "What the ML model learned from where renewables were built",
                   "Label: operating renewable plant within 10 km of the node "
                   "(44 of 117 nodes). Cross-validated ROC AUC 0.90.",
                   out / "fig_ml_importance.png", note=ML_NOTE)


def ml_pipeline_check(preds: pd.DataFrame, nodes: pd.DataFrame, out: Path) -> Path:
    d = preds.merge(nodes[["node_id", "renewable_pipeline_mw_10km"]], on="node_id")
    d = d[d.ml_label == 0]
    groups = [("Not flagged", d[~d.ml_opportunity], MUTED),
              ("Flagged by ML", d[d.ml_opportunity], ORANGE)]
    fig, ax = plt.subplots(figsize=(8, 4.2))
    fig.subplots_adjust(left=0.2, right=0.95, top=0.8, bottom=0.2)
    rng = np.random.default_rng(0)
    for i, (_name, g, col) in enumerate(groups):
        v = g.renewable_pipeline_mw_10km.to_numpy()
        ax.scatter(v, i + rng.uniform(-0.15, 0.15, len(v)), s=40, color=col,
                   edgecolor=SURFACE, lw=1.5, zorder=3)
        med = np.median(v)
        ax.vlines(med, i - 0.3, i + 0.3, color=INK, lw=2, zorder=4)
        ax.text(med, i + 0.36, f"median {med:.1f} MW (n = {len(v)})", ha="center",
                fontsize=9, color=INK)
    ax.set_yticks([0, 1], [g[0] for g in groups])
    ax.set_ylim(-0.6, 1.8)
    ax.set_xlabel("Pipeline renewable capacity within 10 km (MW)")
    ax.xaxis.grid(True, color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    return _finish(fig, "Nodes the model flags already attract pipeline projects",
                   "Nodes with no operating plant nearby. Pipeline capacity was not used "
                   "to train the model.", out / "fig_ml_pipeline_check.png", note=ML_NOTE)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mode", choices=["demo", "real"], default="real")
    args = ap.parse_args()
    paths = yaml.safe_load((ROOT / "config" / "project.yaml").read_text())["modes"][args.mode]
    proc, res = ROOT / paths["processed_root"], ROOT / paths["results_root"]
    out = res / "figures"
    out.mkdir(parents=True, exist_ok=True)
    nodes = pd.read_csv(proc / "integrate" / "nodes_integrated.csv")
    scores = pd.read_csv(proc / "score" / "scores_long.csv")
    written = [robust_nodes(scores, out)]
    tables = res / "tables"
    if (tables / "sensitivity_rank_stability.csv").exists():
        written += [rank_stability(pd.read_csv(tables / "sensitivity_rank_stability.csv"), out),
                    leave_one_out(pd.read_csv(tables / "sensitivity_leave_one_out.csv"), out)]
    if (proc / "ml" / "ml_predictions.csv").exists():
        written += [ml_importance(pd.read_csv(proc / "ml" / "ml_feature_importance.csv"), out),
                    ml_pipeline_check(pd.read_csv(proc / "ml" / "ml_predictions.csv"), nodes, out)]
    for p in written:
        print(p)


if __name__ == "__main__":
    main()
