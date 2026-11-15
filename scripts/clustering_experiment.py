"""Node clustering experiment: features-only vs contiguous clusters (tables + figures).

Usage:
    uv run python scripts/clustering_experiment.py --mode real

Reads <results_root>/tables/nodes_integrated.csv and config/clustering.yaml.
Writes <results_root>/tables/clustering_*.csv and <results_root>/figures/fig_clustering_*.png.
Exploratory: clusters are similarity groups, not diagnoses of congestion or curtailment.
"""

from __future__ import annotations

import argparse
import textwrap
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import yaml  # noqa: E402
from scipy import sparse  # noqa: E402

from bess_catalonia.ml import clustering as cl  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SURFACE, INK, INK2, GRID, LAND = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df", "#efeeea"
# Fixed categorical order; marker shape repeats the identity so colour is never alone.
COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
MARKERS = ["o", "s", "^", "D", "v", "P", "X", "*"]
VARIANTS = {"A_features": "A. Features only", "B_spatial": "B. Geographic neighbours",
            "C_grid": "C. Transmission lines"}
FEAT = {"bess_headroom_proxy_mw": "BESS headroom proxy",
        "renewable_mw_10km": "Operating renewables, 10 km",
        "renewable_pipeline_mw_10km": "Pipeline renewables, 10 km",
        "nearby_demand_mwh_10km": "Nearby demand, 10 km",
        "nearby_industrial_demand_mwh_10km": "Industrial demand, 10 km",
        "suitable_land_ha_10km": "Suitable land, 10 km",
        "suitable_land_ha_5km": "Suitable land, 5 km",
        "distance_to_major_road_km": "Distance to major road"}
NOTE = ("Exploratory. Clusters are similarity groups, not evidence of congestion or curtailment. "
        "Lines in C are approximate (OpenStreetMap via PyPSA-Eur), not official REE topology.")

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "font.family": "DejaVu Sans", "font.size": 10, "text.color": INK,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": False,
})


def _finish(fig, title: str, subtitle: str, path: Path, note: str = NOTE) -> Path:
    h = fig.get_figheight()
    fig.suptitle(title, x=0.01, y=1 - 0.08 / h, ha="left", va="top", fontsize=14,
                 fontweight="bold")
    fig.text(0.01, 1 - 0.42 / h, subtitle, ha="left", va="top", fontsize=10, color=INK2)
    fig.text(0.01, 0.06 / h, note, ha="left", va="bottom", fontsize=8, color=INK2)
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return path


def _outline(crs: str) -> gpd.GeoSeries | None:
    src = ROOT / "data/raw/gis/icgc_municipis/municipis_5000_raw.gpkg"
    if not src.exists():
        return None
    g = gpd.read_file(src).to_crs(crs)
    return gpd.GeoSeries([g.geometry.buffer(0).union_all().simplify(300)], crs=crs)


def fig_k_selection(ev: pd.DataFrame, chosen: int, out: Path) -> Path:
    metrics = [("silhouette", "Separation (silhouette)", "higher = tighter groups"),
               ("stability_ari", "Stability (ARI, 80% resamples)", "1 = same clusters every time"),
               ("spatial_coherence", "Contiguity", "share of neighbour links inside one cluster")]
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.8))
    fig.subplots_adjust(left=0.05, right=0.84, top=0.76, bottom=0.25, wspace=0.28)
    for ax, (col, title, hint) in zip(axes, metrics, strict=True):
        for i, (v, name) in enumerate(VARIANTS.items()):
            g = ev[ev.variant == v]
            if g.empty:
                continue
            ax.plot(g.k, g[col], color=COLORS[i], lw=2, marker=MARKERS[i], ms=6,
                    markeredgecolor=SURFACE, markeredgewidth=1.5)
            if ax is axes[-1]:
                ax.text(g.k.max() + 0.2, g[col].iloc[-1], name, va="center", fontsize=9,
                        color=INK2)
        ax.axvline(chosen, color=GRID, lw=6, zorder=0)
        ax.set_title(title, loc="left", fontsize=11, color=INK)
        ax.set_xlabel(f"Number of clusters\n{hint}")
        ax.set_xticks(sorted(ev.k.unique()))
        ax.yaxis.grid(True, color=GRID, lw=0.8)
        ax.set_axisbelow(True)
        ax.set_ylim(0, max(1.0 if col != "silhouette" else 0, ev[col].max() * 1.15))
    return _finish(fig, "Contiguous clusters are more stable, at a small cost in separation",
                   f"Same features and method; only the allowed merges differ. Shaded band = "
                   f"k used in the maps ({chosen}).", out / "fig_clustering_k_selection.png")


def fig_maps(nodes: gpd.GeoDataFrame, variants: list[str], k: int, out: Path,
             links: dict | None = None) -> Path:
    links = links or {}
    xy = np.column_stack([nodes.geometry.x, nodes.geometry.y])
    outline = _outline(nodes.crs)
    fig, axes = plt.subplots(1, len(variants), figsize=(5.6 * len(variants), 6.2))
    axes = np.atleast_1d(axes)
    fig.subplots_adjust(left=0.01, right=0.99, top=0.84, bottom=0.07, wspace=0.02)
    for ax, v in zip(axes, variants, strict=True):
        if outline is not None:
            outline.plot(ax=ax, color=LAND, edgecolor=GRID, lw=1)
        lab = nodes[f"cluster_{v}"]
        for c in sorted(lab.unique()):
            g = nodes[lab == c]
            ax.scatter(g.geometry.x, g.geometry.y, s=52, color=COLORS[c - 1],
                       marker=MARKERS[c - 1], edgecolor=SURFACE, lw=1.2, zorder=3,
                       label=f"Cluster {c} ({len(g)} nodes)")
        if v in links:
            r, c = sparse.triu(links[v]).nonzero()
            ax.plot([xy[r, 0], xy[c, 0]], [xy[r, 1], xy[c, 1]], color="#a3a29b", lw=0.7,
                    zorder=2)
        ax.set_title(VARIANTS[v], loc="left", fontsize=11, color=INK)
        ax.set_aspect("equal")
        ax.set_axis_off()
        ax.legend(loc="lower right", frameon=False, fontsize=8.5, labelcolor=INK2,
                  handletextpad=0.2, borderaxespad=0)
    return _finish(fig, f"The same {len(nodes)} nodes, clustered {len(variants)} ways (k = {k})",
                   "Cluster numbers are per panel (1 = largest) and do not correspond "
                   "across panels. Grey lines in C = links used.", out / "fig_clustering_maps.png")


def fig_profiles(prof: pd.DataFrame, variant: str, features: list[str], out: Path) -> Path:
    p = prof[prof.variant == variant].set_index("cluster")
    z = p[[f"z_{f}" for f in features]].to_numpy()
    fig, ax = plt.subplots(figsize=(11, 2.3 + 0.55 * len(p)))
    h = fig.get_figheight()
    fig.subplots_adjust(left=0.19, right=0.93, top=1 - 0.95 / h, bottom=0.95 / h)
    lim = max(1.5, float(np.abs(z).max()))
    im = ax.imshow(z, cmap=matplotlib.colors.LinearSegmentedColormap.from_list(
        "div", ["#eb6834", "#f1f0ec", "#2a78d6"]), vmin=-lim, vmax=lim, aspect="auto")
    for (i, j), v in np.ndenumerate(z):
        ax.text(j, i, f"{v:+.1f}", ha="center", va="center", fontsize=9,
                color=SURFACE if abs(v) > 0.6 * lim else INK)
    ax.set_xticks(range(len(features)), [textwrap.fill(FEAT.get(f, f), 14) for f in features],
                  fontsize=8.5)
    ax.set_yticks(range(len(p)), [f"Cluster {c} ({int(n)} nodes)"
                                  for c, n in zip(p.index, p.n_nodes, strict=True)])
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_xticks(np.arange(-0.5, len(features)), minor=True)
    ax.set_yticks(np.arange(-0.5, len(p)), minor=True)
    ax.grid(which="minor", color=SURFACE, lw=2)
    ax.tick_params(which="both", length=0)
    cb = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.02)
    cb.outline.set_visible(False)
    cb.set_label("vs average node (std. dev.)", fontsize=8.5)
    return _finish(fig, f"What makes each cluster different ({VARIANTS[variant]})",
                   "Cluster mean of each feature, in standard deviations from the all-node "
                   "average (log scale). Blue = above, orange = below.",
                   out / f"fig_clustering_profiles_{variant}.png")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mode", choices=["demo", "real"], default="real")
    ap.add_argument("--k", type=int, default=None, help="force the number of clusters")
    args = ap.parse_args()

    project = yaml.safe_load((ROOT / "config/project.yaml").read_text())
    cfg = yaml.safe_load((ROOT / "config/clustering.yaml").read_text())
    results = ROOT / project["modes"][args.mode]["results_root"]
    tables, figures = results / "tables", results / "figures"
    figures.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(tables / "nodes_integrated.csv")
    nodes = gpd.GeoDataFrame(
        df, geometry=gpd.points_from_xy(df.lon, df.lat), crs=project["project"]["geographic_crs"]
    ).to_crs(project["project"]["analysis_crs"])
    features = [f for f in cfg["features"] if f in nodes.columns]
    x = cl.prepare_features(nodes, features, cfg.get("log_transform", True))
    xy = np.column_stack([nodes.geometry.x, nodes.geometry.y])

    kn = int(cfg["spatial_graph"]["k_neighbours"])
    g_spatial = cl.spatial_graph(xy, kn)
    st = cfg["stability"]
    kw = {"draws": int(st["draws"]), "share": float(st["sample_share"]),
          "seed": int(st["random_state"])}
    k_values = list(range(cfg["k_range"][0], cfg["k_range"][1] + 1))

    graphs: dict[str, tuple] = {
        "A_features": (None, None),
        "B_spatial": (g_spatial, lambda idx: cl.spatial_graph(xy[idx], kn)),
    }
    if cfg.get("line_edges_csv"):
        edges = pd.read_csv(ROOT / cfg["line_edges_csv"])
        g_line = cl.line_graph(nodes.node_id, edges, xy,
                               int(cfg.get("line_fallback_neighbours", 3)))
        graphs["C_grid"] = (g_line, lambda idx: cl._connect(g_line[idx][:, idx], xy[idx]))
        linked = set(edges.from_node_id) | set(edges.to_node_id)
        print(f"C_grid: {nodes.node_id.isin(linked).sum()} of {len(nodes)} nodes have line data; "
              f"the rest use nearest neighbours")

    ev = pd.concat([cl.evaluate(x, xy, k_values, g_spatial, g, fn, **kw).assign(variant=v)
                    for v, (g, fn) in graphs.items()], ignore_index=True)
    ev = ev[["variant", "k", "silhouette", "stability_ari", "spatial_coherence",
             "map_fragments", "smallest_cluster"]].round(3)

    # Common k: the most stable solution of the contiguous variant, among k >= 3 whose
    # smallest cluster holds at least 5% of the nodes.
    ref = ev[(ev.variant == list(graphs)[-1]) & (ev.k >= 3)
             & (ev.smallest_cluster >= 0.05 * len(nodes))]
    k = args.k or cfg.get("k_override") or int(ref.loc[ref.stability_ari.idxmax(), "k"])

    profiles = []
    for v, (g, _) in graphs.items():
        nodes[f"cluster_{v}"] = cl.relabel_by_size(cl.cluster(x, k, g))
        zdf = pd.DataFrame(x, columns=[f"z_{f}" for f in features])
        zdf["cluster"] = nodes[f"cluster_{v}"].to_numpy()
        prof = zdf.groupby("cluster").mean()
        med = nodes.groupby(f"cluster_{v}")[features].median().add_prefix("median_")
        prof = prof.join(med).assign(variant=v, n_nodes=zdf.cluster.value_counts())
        profiles.append(prof.reset_index())
    profiles = pd.concat(profiles, ignore_index=True)
    profiles = profiles[["variant", "cluster", "n_nodes"]
                        + [c for c in profiles.columns if c.startswith(("z_", "median_"))]]

    cols = ["node_id", "node_name", "voltage_kv", "lon", "lat"] + [f"cluster_{v}" for v in graphs]
    assign = pd.DataFrame(nodes[cols])
    scores_path = tables / "scores_long.csv"
    if scores_path.exists():
        s = pd.read_csv(scores_path).pivot(index="node_id", columns="scenario", values="rank")
        assign = assign.merge(s.add_prefix("rank_"), on="node_id", how="left")

    ev.to_csv(tables / "clustering_k_selection.csv", index=False)
    profiles.round(3).to_csv(tables / "clustering_profiles.csv", index=False)
    assign.to_csv(tables / "clustering_assignments.csv", index=False)

    fig_k_selection(ev, k, figures)
    fig_maps(nodes, list(graphs), k, figures,
             {"C_grid": graphs["C_grid"][0]} if "C_grid" in graphs else None)
    for v in graphs:
        fig_profiles(profiles, v, features, figures)

    print(ev.to_string(index=False))
    print(f"\nk used: {k}; features: {len(features)}; nodes: {len(nodes)}")
    print(f"Wrote tables to {tables} and figures to {figures}")


if __name__ == "__main__":
    main()
