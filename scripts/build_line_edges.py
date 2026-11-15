"""Approximate node-to-node line topology from the PyPSA-Eur OSM prebuilt network.

Usage:
    uv run python scripts/build_line_edges.py

Reads data/raw/grid/pypsa_eur_osm/{buses,lines,transformers}.csv (Zenodo, ODbL) and
data/processed/grid/grid_nodes.csv. Each REE node is matched to the nearest OSM bus of the
same voltage level (one-to-one, within --max-km). Two REE nodes are linked when a line or
transformer joins their buses directly, or through OSM buses that match no REE node (tee points,
substations missing from the REE list). Writes data/interim/grid/line_edges.csv and
line_node_matches.csv. This is OSM-derived adjacency, not official REE topology.
"""

from __future__ import annotations

import argparse
from collections import deque
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment
from scipy.spatial.distance import cdist

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data/raw/grid/pypsa_eur_osm"
OUT = ROOT / "data/interim/grid"
CRS = "EPSG:25831"
BBOX = (-0.6, 39.9, 4.0, 43.5)  # Catalonia plus a margin so border loops stay connected


def vclass(v: float) -> int:
    return 400 if v >= 300 else 220 if v >= 180 else 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--max-km", type=float, default=10.0, help="max node-to-bus match distance")
    ap.add_argument("--max-hops", type=int, default=2,
                    help="max unmatched OSM buses a link may pass through")
    args = ap.parse_args()

    nodes = pd.read_csv(ROOT / "data/processed/grid/grid_nodes.csv")
    nodes = gpd.GeoDataFrame(nodes, geometry=gpd.points_from_xy(nodes.lon, nodes.lat),
                             crs="EPSG:4326").to_crs(CRS)
    nodes["vclass"] = nodes.voltage_kv.map(vclass)

    buses = pd.read_csv(SRC / "buses.csv")
    buses = buses[(buses.dc == "f") & buses.x.between(BBOX[0], BBOX[2])
                  & buses.y.between(BBOX[1], BBOX[3])].copy()
    buses["vclass"] = buses.voltage.map(vclass)
    buses = buses[buses.vclass > 0]
    buses = gpd.GeoDataFrame(buses, geometry=gpd.points_from_xy(buses.x, buses.y),
                             crs="EPSG:4326").to_crs(CRS)

    # 1. One-to-one match of REE nodes to same-voltage OSM buses, minimising total distance
    #    (node coordinates are approximate, so plain nearest-bus matching collides).
    parts = []
    for vc, g in nodes.groupby("vclass"):
        bb = buses[buses.vclass == vc]
        d = cdist(np.column_stack([g.geometry.x, g.geometry.y]),
                  np.column_stack([bb.geometry.x, bb.geometry.y])) / 1000
        r, c = linear_sum_assignment(np.where(d <= args.max_km, d, 1e6))
        ok = d[r, c] <= args.max_km
        parts.append(pd.DataFrame({"node_id": g.node_id.to_numpy()[r[ok]],
                                   "bus_id": bb.bus_id.to_numpy()[c[ok]],
                                   "match_km": d[r, c][ok].round(2)}))
    match = pd.concat(parts)
    match = nodes[["node_id", "voltage_kv"]].merge(match, on="node_id", how="left")
    bus_nodes = match.dropna(subset=["bus_id"]).groupby("bus_id").node_id.apply(list).to_dict()

    # 2. Bus graph from lines and transformers inside the window.
    keep = set(buses.bus_id)
    adj: dict[str, set[str]] = {b: set() for b in keep}
    for name in ("lines", "transformers"):
        e = pd.read_csv(SRC / f"{name}.csv", usecols=["bus0", "bus1"], quotechar="'")
        e = e[e.bus0.isin(keep) & e.bus1.isin(keep)]
        for a, b in zip(e.bus0, e.bus1, strict=True):
            adj[a].add(b)
            adj[b].add(a)

    # 3. Link REE nodes whose buses connect directly or through unmatched buses only.
    edges = set()
    for start, here in bus_nodes.items():
        for i, a in enumerate(here):               # several REE nodes on one OSM bus
            for b in here[i + 1:]:
                edges.add((*sorted((a, b)), 0))
        seen, queue = {start}, deque([(start, 0)])
        while queue:
            bus, hops = queue.popleft()
            for nxt in adj[bus]:
                if nxt in seen:
                    continue
                seen.add(nxt)
                if nxt in bus_nodes:
                    for a in here:
                        for b in bus_nodes[nxt]:
                            edges.add((*sorted((a, b)), hops))
                elif hops < args.max_hops:
                    queue.append((nxt, hops + 1))
    ed = (pd.DataFrame(sorted(edges), columns=["from_node_id", "to_node_id", "unmatched_hops"])
          .sort_values("unmatched_hops").drop_duplicates(["from_node_id", "to_node_id"]))

    OUT.mkdir(parents=True, exist_ok=True)
    match.to_csv(OUT / "line_node_matches.csv", index=False)
    ed.to_csv(OUT / "line_edges.csv", index=False)

    linked = set(ed.from_node_id) | set(ed.to_node_id)
    print(f"nodes: {len(nodes)}  matched to an OSM bus: {match.bus_id.notna().sum()}  "
          f"with at least one line: {len(linked)}")
    print(f"edges: {len(ed)}  (direct: {(ed.unmatched_hops == 0).sum()}, "
          f"via unmatched buses: {(ed.unmatched_hops > 0).sum()})")
    print("unmatched:", ", ".join(match[match.bus_id.isna()].node_id) or "none")
    print("match distance km:", match.match_km.describe().round(2).to_dict())
    print("hops:", ed.unmatched_hops.value_counts().sort_index().to_dict())


if __name__ == "__main__":
    main()
