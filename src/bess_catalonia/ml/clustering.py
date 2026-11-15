"""Node clustering experiment: features-only vs geographically / electrically contiguous.

Three variants use the same features and the same Ward linkage, so the only thing that
changes is which nodes are allowed to merge:

* ``A_features``  - no constraint (clusters are node "types", scattered on the map)
* ``B_spatial``   - merges only between geographic neighbours (contiguous regions)
* ``C_grid``      - merges only along transmission lines (needs a line edge list)

Clusters are similarity groups. They do not diagnose congestion or curtailment.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import sparse
from scipy.sparse.csgraph import connected_components, minimum_spanning_tree
from scipy.spatial.distance import pdist, squareform
from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sklearn.neighbors import kneighbors_graph
from sklearn.preprocessing import StandardScaler


def prepare_features(nodes: pd.DataFrame, features: list[str], log: bool = True) -> np.ndarray:
    """Standardised feature matrix. Rows with a missing feature are an error, not zero-filled."""
    x = nodes[features].astype(float)
    if x.isna().any().any():
        bad = x.columns[x.isna().any()].tolist()
        raise ValueError(f"Missing values in clustering features: {bad}")
    if log:
        x = np.log1p(x.clip(lower=0))
    return StandardScaler().fit_transform(x)


def _connect(graph: sparse.csr_matrix, xy: np.ndarray) -> sparse.csr_matrix:
    """Symmetrise and add the shortest geographic links needed to make the graph connected."""
    g = ((graph + graph.T) > 0).astype(float)
    if connected_components(g, directed=False)[0] > 1:
        mst = minimum_spanning_tree(squareform(pdist(xy)) + 1e-9)
        g = ((g + mst + mst.T) > 0).astype(float)
    return sparse.csr_matrix(g)


def spatial_graph(xy: np.ndarray, k: int = 6) -> sparse.csr_matrix:
    """k-nearest-neighbour graph on projected coordinates (metres)."""
    k = min(k, len(xy) - 1)
    return _connect(kneighbors_graph(xy, n_neighbors=k, include_self=False), xy)


def line_graph(node_ids: pd.Series, edges: pd.DataFrame, xy: np.ndarray,
               fallback_k: int = 3) -> sparse.csr_matrix:
    """Graph from a line list (from_node_id, to_node_id).

    Nodes with no line in the list (not found in the line source) are linked to their
    ``fallback_k`` nearest geographic neighbours instead, so every node can still merge.
    """
    pos = {n: i for i, n in enumerate(node_ids)}
    e = edges[edges.from_node_id.isin(pos) & edges.to_node_id.isin(pos)]
    r = e.from_node_id.map(pos).to_numpy()
    c = e.to_node_id.map(pos).to_numpy()
    g = sparse.lil_matrix((len(pos), len(pos)))
    g[r, c] = 1
    missing = np.setdiff1d(np.arange(len(pos)), np.concatenate([r, c]))
    if len(missing) and fallback_k:
        knn = kneighbors_graph(xy, n_neighbors=min(fallback_k, len(xy) - 1)).tolil()
        g[missing] = knn[missing]
    return _connect(sparse.csr_matrix(g), xy)


def cluster(x: np.ndarray, k: int, graph: sparse.csr_matrix | None = None) -> np.ndarray:
    """Ward clustering; with ``graph`` only connected nodes may merge."""
    return AgglomerativeClustering(n_clusters=k, linkage="ward", connectivity=graph).fit_predict(x)


def spatial_coherence(labels: np.ndarray, graph: sparse.csr_matrix) -> float:
    """Share of neighbour links whose two ends are in the same cluster (1 = fully contiguous)."""
    r, c = sparse.triu(graph).nonzero()
    return float((labels[r] == labels[c]).mean())


def fragments(labels: np.ndarray, graph: sparse.csr_matrix) -> int:
    """Number of separate pieces on the map, summed over clusters (equals k when contiguous)."""
    total = 0
    for lab in np.unique(labels):
        idx = np.flatnonzero(labels == lab)
        total += connected_components(graph[idx][:, idx], directed=False)[0]
    return total


def stability(x: np.ndarray, xy: np.ndarray, k: int, base: np.ndarray, graph_fn=None,
              draws: int = 100, share: float = 0.8, seed: int = 42) -> float:
    """Mean adjusted Rand index between the full solution and re-clustered subsamples."""
    rng = np.random.default_rng(seed)
    n = len(x)
    out = []
    for _ in range(draws):
        idx = np.sort(rng.choice(n, size=int(share * n), replace=False))
        g = graph_fn(idx) if graph_fn else None
        out.append(adjusted_rand_score(base[idx], cluster(x[idx], k, g)))
    return float(np.mean(out))


def evaluate(x: np.ndarray, xy: np.ndarray, k_values: list[int], ref_graph: sparse.csr_matrix,
             graph: sparse.csr_matrix | None = None, graph_fn=None,
             draws: int = 100, share: float = 0.8, seed: int = 42) -> pd.DataFrame:
    """One row per k: fit quality, contiguity (on ``ref_graph``) and stability."""
    rows = []
    for k in k_values:
        lab = cluster(x, k, graph)
        rows.append({
            "k": k,
            "silhouette": float(silhouette_score(x, lab)),
            "spatial_coherence": spatial_coherence(lab, ref_graph),
            "map_fragments": fragments(lab, ref_graph),
            "stability_ari": stability(x, xy, k, lab, graph_fn, draws, share, seed),
            "smallest_cluster": int(np.bincount(lab).min()),
        })
    return pd.DataFrame(rows)


def relabel_by_size(labels: np.ndarray) -> np.ndarray:
    """Cluster 1 is the largest, 2 the next, ... so numbering is reproducible."""
    order = pd.Series(labels).value_counts().index
    return pd.Series(labels).map({old: i + 1 for i, old in enumerate(order)}).to_numpy()
