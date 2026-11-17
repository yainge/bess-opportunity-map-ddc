"""Node-to-node line topology from Fernando's matched grid workbook.

Usage:
    uv run python scripts/build_line_edges_topology.py

Reads data/processed/grid_topology/Catalonia_grid_connections_final.xlsx: sheet REE_nodes
(REE node -> OSM substation site_id) and sheet Connections (site_a, site_b joined by a 220 or
400 kV line). Two REE nodes are linked when their substations are connected by a line, or when
they share a substation (for example the 220 kV and 400 kV nodes of one site). Writes
data/interim/grid/line_edges.csv (from_node_id, to_node_id, link) for variant C of
scripts/clustering_experiment.py. Built from OpenStreetMap lines matched to REE nodes; it is
adjacency, not an electrical model.
"""

from __future__ import annotations

import re
from itertools import combinations
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
BOOK = ROOT / "data/processed/grid_topology/Catalonia_grid_connections_final.xlsx"
OUT = ROOT / "data/interim/grid/line_edges.csv"


def node_id(name: str) -> str:
    """Canonical id used by the grid stage: REE-<slug of source_node_id>."""
    return "REE-" + re.sub(r"[^A-Z0-9]+", "_", str(name).upper()).strip("_")


def main() -> None:
    nodes = pd.read_excel(BOOK, sheet_name="REE_nodes")[["ree_node", "site_id"]]
    conns = pd.read_excel(BOOK, sheet_name="Connections")[["site_a", "site_b", "voltage_kv"]]
    nodes = nodes.dropna(subset=["site_id"])
    nodes["node_id"] = nodes["ree_node"].map(node_id)
    by_site = nodes.groupby("site_id")["node_id"].apply(list).to_dict()

    edges = set()
    for site_nodes in by_site.values():
        for a, b in combinations(sorted(site_nodes), 2):
            edges.add((a, b, "same substation"))
    for a_site, b_site, kv in conns.itertuples(index=False):
        for a in by_site.get(a_site, []):
            for b in by_site.get(b_site, []):
                if a != b:
                    lo, hi = sorted((a, b))
                    edges.add((lo, hi, f"{int(kv)} kV line"))
    out = (pd.DataFrame(sorted(edges), columns=["from_node_id", "to_node_id", "link"])
           .drop_duplicates(subset=["from_node_id", "to_node_id"]))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT, index=False)
    linked = set(out.from_node_id) | set(out.to_node_id)
    print(f"wrote {OUT.relative_to(ROOT)}: {len(out)} links, {len(linked)} of "
          f"{len(nodes)} located nodes linked; by type: {out.link.value_counts().to_dict()}")


if __name__ == "__main__":
    main()
