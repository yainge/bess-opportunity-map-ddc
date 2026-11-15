#!/usr/bin/env python
"""Trial v2 of the BESS location typology using Fernando's matched REE node table (Nov 2026).

Differences from build_typology.py (kept as a record):
  * Node attributes come from data/processed/grid_topology/ree_nodes_matched.csv (OSM-matched,
    hand-reviewed coordinates; REE access-capacity files of 3 Nov 2026) instead of Polo's sheet.
  * Nearest REE node per pixel is recomputed from the new coordinates (cutoff 20 km).
  * The three old node variables (access capacity, occupation share, storage room) are replaced.
    "Available" capacity is zero at 112 of 117 nodes, so it carries no information for clustering.
    Instead the clustering uses two node-activity variables: generation MW granted at the node and
    storage MW granted + pending (injection mode). Room for storage, tender nodes and nodes under
    construction are drawn as symbols on the map, not used as features.
  * Everything else (pixel features, k selection, profiles, battery overlay) is unchanged.

Run from the repo root:
    experiments/heatmap/.venv/bin/python experiments/typology/build_typology_v2.py
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import folium
import geopandas as gpd
import matplotlib
import numpy as np
import pandas as pd
import rasterio
from matplotlib import pyplot as plt
from matplotlib.colors import ListedColormap
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.warp import calculate_default_transform, reproject
from scipy.spatial import cKDTree
from sklearn.cluster import KMeans
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sklearn.preprocessing import StandardScaler

matplotlib.use("Agg")
ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
NODES = ROOT / "data" / "processed" / "grid_topology" / "ree_nodes_matched.csv"
GRID = ROOT / "experiments" / "heatmap" / "output" / "heatmap_grid_500m.gpkg"
HERE = Path(__file__).resolve().parent
OUT = HERE / "output_v2_nodes_nov2026"
OUT.mkdir(exist_ok=True)
CRS = "EPSG:25831"
CELL = 500
SEED = 42
NODE_CUTOFF_M = 20_000  # beyond this, node attributes are set to 0 (no node "serves" the pixel)
T0 = time.time()
log = lambda m: print(f"[{time.time() - T0:5.0f}s] {m}", flush=True)

log("loading pixel grid")
cells = gpd.read_file(GRID)
cells = cells.drop(columns=[c for c in ["nearest_ree_node", "access_capacity_nearest_node_mw"] if c in cells])
log(f"{len(cells):,} land pixels")

# ------------------------------------------------------------------ REE nodes (Fernando's table)
n = pd.read_csv(NODES)
nodes = gpd.GeoDataFrame(n, geometry=gpd.points_from_xy(n.lon, n.lat), crs="EPSG:4326").to_crs(CRS)
f0 = lambda c: pd.to_numeric(nodes[c], errors="coerce").fillna(0)
nodes["gen_granted_mw"] = f0("gen_granted_MW")
nodes["storage_queue_mw"] = f0("storage_granted_MW_genfile") + f0("storage_pending_MW_genfile")
nodes["storage_room_mw"] = np.maximum(f0("storage_available_MPE_RdT_MW (generation mode)"),
                                      f0("storage_available_MPE_RdT_MW (demand mode)"))
nodes["tender"] = nodes["tender_node (nudo de concurso)"].astype(str).str.upper().eq("SI")
nodes["under_construction"] = nodes["under_construction"].astype(bool)
log(f"{len(nodes)} REE nodes | room for storage at {(nodes.storage_room_mw > 0).sum()} | tender {nodes.tender.sum()} "
    f"| under construction {nodes.under_construction.sum()}")

tree = cKDTree(np.c_[nodes.geometry.x, nodes.geometry.y])
dist, idx = tree.query(np.c_[cells.x, cells.y])
cells["nearest_ree_node"] = nodes.ree_node.to_numpy()[idx]
cells["dist_ree_node_km"] = dist / 1000
within = dist <= NODE_CUTOFF_M
for col in ["gen_granted_mw", "storage_queue_mw", "storage_room_mw"]:
    cells[f"node_{col}"] = np.where(within, nodes[col].to_numpy()[idx], 0.0)
cells["node_under_construction"] = np.where(within, nodes.under_construction.to_numpy()[idx], False)
log(f"pixels within {NODE_CUTOFF_M // 1000} km of a node: {within.mean():.0%}")

# ------------------------------------------------------------------ features for the typology
FEATS = {
    "dist_substation_km": "capped",
    "dist_substation_400kv_km": "capped",
    "node_gen_granted_mw": "log",
    "node_storage_queue_mw": "log",
    "renewable_operating_mw_10km": "log",
    "renewable_pipeline_mw_10km": "log",
    "demand_mwh_10km": "log",
    "distribution_load_mw_10km": "log",
    "dist_distribution_substation_km": "capped",
}
X = pd.DataFrame(index=cells.index)
for f, tr in FEATS.items():
    v = cells[f].astype(float).fillna(0)
    X[f] = np.log1p(v) if tr == "log" else (np.minimum(v, 50) if tr == "capped" else v)
Xs = StandardScaler().fit_transform(X)

# ------------------------------------------------------------------ choose k
rng = np.random.default_rng(SEED)
sample = rng.choice(len(Xs), 15000, replace=False)
rows_k = []
for k in range(3, 9):
    km = KMeans(n_clusters=k, n_init=10, random_state=SEED).fit(Xs)
    sil = silhouette_score(Xs[sample], km.labels_[sample])
    aris = []
    for b in range(5):
        i = rng.choice(len(Xs), len(Xs) // 2, replace=False)
        km_b = KMeans(n_clusters=k, n_init=5, random_state=SEED + b + 1).fit(Xs[i])
        aris.append(adjusted_rand_score(km.labels_[sample], km_b.predict(Xs[sample])))
    rows_k.append({"k": k, "silhouette": round(sil, 3), "stability_ari": round(float(np.mean(aris)), 3),
                   "inertia": round(km.inertia_)})
    log(f"k={k} silhouette {sil:.3f} stability {np.mean(aris):.3f}")
kdf = pd.DataFrame(rows_k)
kdf.to_csv(OUT / "k_selection.csv", index=False)
print(kdf.to_string(index=False))
ok = kdf[(kdf.k >= 4) & (kdf.stability_ari >= 0.7)]
K = int((ok if len(ok) else kdf[kdf.k >= 4]).sort_values("silhouette", ascending=False).k.iloc[0])
log(f"chosen k = {K}")
km = KMeans(n_clusters=K, n_init=20, random_state=SEED).fit(Xs)
cells["cluster"] = km.labels_

# ------------------------------------------------------------------ profiles
raw_cols = list(FEATS) + ["node_storage_room_mw", "dist_ree_node_km", "suitable_land_share_1km", "excluded"]
prof = cells.groupby("cluster")[raw_cols].median(numeric_only=True)
prof["n_pixels"] = cells.groupby("cluster").size()
prof["area_share"] = (prof.n_pixels / len(cells)).round(3)
prof["share_pixels_node_with_room"] = cells.groupby("cluster")["node_storage_room_mw"].apply(lambda s: (s > 0).mean()).round(3)
z = pd.DataFrame(km.cluster_centers_, columns=list(FEATS)).round(2)
z.index.name = "cluster"
prof.round(2).to_csv(OUT / "cluster_profiles_median.csv")
z.to_csv(OUT / "cluster_centroids_zscore.csv")
print("\nmedian profile per cluster:\n", prof.round(2).T.to_string())
print("\nz-score centroids:\n", z.T.to_string())
# which nodes dominate each cluster (by pixel count)
dom = (cells[within].groupby(["cluster", "nearest_ree_node"]).size().rename("px").reset_index()
       .sort_values(["cluster", "px"], ascending=[True, False]).groupby("cluster").head(6))
dom.to_csv(OUT / "cluster_dominant_nodes.csv", index=False)
print("\nnodes with most pixels per cluster:\n", dom.groupby("cluster").nearest_ree_node.apply(lambda s: ", ".join(s)).to_string())

# ------------------------------------------------------------------ existing BESS projects by type
bess = gpd.read_file(RAW / "storage" / "ENERGIA_BATERIES_STANDALONE_20261105.gpkg").to_crs(CRS)
bess = bess[bess.ESTAT != "No autoritzat"]
sites = gpd.GeoDataFrame(geometry=list(bess.geometry.union_all().geoms), crs=CRS)
j = gpd.sjoin(bess[["POTENCIA", "geometry"]], sites.reset_index(), predicate="intersects")
sites["mw"] = j.groupby("index")["POTENCIA"].sum().reindex(sites.index).fillna(0).to_numpy()
pts = sites.copy(); pts["geometry"] = pts.representative_point()
hit = gpd.sjoin(pts, cells[["cluster", "nearest_ree_node", "node_storage_room_mw", "geometry"]], how="left", predicate="within")
hit = hit[~hit.index.duplicated()]
bess_by = hit.groupby("cluster").agg(n_sites=("mw", "size"), mw=("mw", "sum"))
bess_by["site_share"] = (bess_by.n_sites / bess_by.n_sites.sum()).round(3)
bess_by["area_share"] = prof.area_share
bess_by["ratio_sites_vs_area"] = (bess_by.site_share / bess_by.area_share).round(2)
bess_by.to_csv(OUT / "bess_projects_by_cluster.csv")
print("\nexisting battery projects per cluster:\n", bess_by.to_string())
print(f"\nbattery sites whose nearest node has room for storage: {(hit.node_storage_room_mw > 0).sum()} of {len(hit)}")

# ------------------------------------------------------------------ names (edit after reading profiles)
names_file = HERE / "cluster_names_v2.json"
NAMES = json.loads(names_file.read_text()) if names_file.exists() else {}
cells["type"] = cells.cluster.map(lambda c: NAMES.get(str(c), f"cluster {c}"))

# ------------------------------------------------------------------ outputs
cells.to_file(OUT / "typology_grid_500m.gpkg", layer="cells", driver="GPKG")
# GeoPackage field names are case-insensitive, so keep only our derived columns plus identifiers
nodes[["ree_node", "ree_code", "kv", "method", "review_result", "under_construction", "tender", "gen_granted_mw",
       "storage_queue_mw", "storage_room_mw", "gen_unavailable_reason", "lat", "lon", "geometry"]].to_file(
    OUT / "ree_nodes_nov2026.gpkg", driver="GPKG")
minx, miny, maxx, maxy = cells.total_bounds
transform = from_origin(np.floor(minx / CELL) * CELL, np.ceil(maxy / CELL) * CELL, CELL, CELL)
ncol = int(np.ceil((maxx - np.floor(minx / CELL) * CELL) / CELL)); nrow = int(np.ceil((np.ceil(maxy / CELL) * CELL - miny) / CELL))
rows, cols = rasterio.transform.rowcol(transform, cells.x.to_numpy(), cells.y.to_numpy())
rows, cols = np.asarray(rows), np.asarray(cols)
clu_r = np.full((nrow, ncol), 255, dtype="uint8"); clu_r[rows, cols] = cells.cluster.to_numpy()
exc_r = np.zeros((nrow, ncol), dtype=bool); exc_r[rows, cols] = cells.excluded.to_numpy().astype(bool)
with rasterio.open(OUT / "typology_500m.tif", "w", driver="GTiff", height=nrow, width=ncol, count=1, dtype="uint8",
                   nodata=255, crs=CRS, transform=transform, compress="deflate") as dst:
    dst.write(clu_r, 1)

palette = ["#1b9e77", "#d95f02", "#7570b3", "#e7298a", "#66a61e", "#e6ab02", "#a6761d", "#666666"][:K]
cmap = ListedColormap(palette)
fig, ax = plt.subplots(figsize=(11, 10))
extent = (transform.c, transform.c + ncol * CELL, transform.f - nrow * CELL, transform.f)
ax.imshow(np.ma.masked_equal(clu_r, 255), extent=extent, cmap=cmap, vmin=-0.5, vmax=K - 0.5, interpolation="nearest")
hatch = np.zeros((nrow, ncol, 4)); hatch[exc_r] = (0, 0, 0, 0.35)
ax.imshow(hatch, extent=extent, interpolation="nearest")
pts.plot(ax=ax, color="white", edgecolor="black", markersize=22, zorder=5)
built = nodes[~nodes.under_construction]; uc = nodes[nodes.under_construction]
built.plot(ax=ax, color="black", markersize=10, marker="s", zorder=6)
uc.plot(ax=ax, facecolor="none", edgecolor="black", markersize=40, marker="s", linewidth=1.2, zorder=6)
room = nodes[nodes.storage_room_mw > 0]
room.plot(ax=ax, facecolor="none", edgecolor="#00b7ff", markersize=140, marker="o", linewidth=1.8, zorder=7)
nodes[nodes.tender].plot(ax=ax, color="#ffd400", edgecolor="black", markersize=90, marker="^", zorder=7)
handles = [plt.Rectangle((0, 0), 1, 1, color=palette[c]) for c in range(K)]
labels = [f"{c}: {NAMES.get(str(c), 'cluster ' + str(c))} ({prof.area_share[c]:.0%} of land, "
          f"{int(bess_by.n_sites.get(c, 0))} projects)" for c in range(K)]
handles += [plt.Rectangle((0, 0), 1, 1, color=(0, 0, 0, 0.35)),
            plt.Line2D([], [], color="w", markeredgecolor="k", marker="o", ms=7, ls=""),
            plt.Line2D([], [], color="k", marker="s", ms=4, ls=""),
            plt.Line2D([], [], color="none", markeredgecolor="k", marker="s", ms=7, ls=""),
            plt.Line2D([], [], color="none", markeredgecolor="#00b7ff", marker="o", ms=12, mew=1.8, ls=""),
            plt.Line2D([], [], color="#ffd400", markeredgecolor="k", marker="^", ms=9, ls="")]
labels += ["hard exclusion (darkened)", "existing battery project", "REE node (built)", "REE node under construction",
           f"node with room for storage ({len(room)})", f"tender node ({int(nodes.tender.sum())})"]
ax.legend(handles, labels, loc="upper left", bbox_to_anchor=(0.0, -0.01), fontsize=7.5, ncol=1, frameon=False,
          title="System-role type (k-means) and REE node status, Nov 2026")
ax.set_title("BESS location typology v2: node data from REE access-capacity files of 3 Nov 2026", fontsize=11)
ax.set_axis_off()
fig.savefig(OUT / "typology.png", dpi=160, bbox_inches="tight"); plt.close(fig)

# web map
t4326, w, h = calculate_default_transform(CRS, "EPSG:4326", ncol, nrow, *rasterio.transform.array_bounds(nrow, ncol, transform))
c4326 = np.full((h, w), 255, dtype="uint8")
reproject(clu_r, c4326, src_transform=transform, src_crs=CRS, dst_transform=t4326, dst_crs="EPSG:4326",
          src_nodata=255, dst_nodata=255, resampling=Resampling.nearest)
e4326 = np.zeros((h, w), dtype="float32")
reproject(exc_r.astype("float32"), e4326, src_transform=transform, src_crs=CRS, dst_transform=t4326, dst_crs="EPSG:4326",
          src_nodata=-1, dst_nodata=-1, resampling=Resampling.nearest)
rgba = np.zeros((h, w, 4))
for c in range(K):
    rgba[c4326 == c] = matplotlib.colors.to_rgba(palette[c], 0.7)
exc = np.zeros((h, w, 4)); exc[e4326 >= 0.5] = (0, 0, 0, 0.35)
plt.imsave(OUT / "_type_overlay.png", rgba); plt.imsave(OUT / "_excl_overlay.png", exc)
west, north = t4326.c, t4326.f; bounds = [[north + h * t4326.e, west], [north, west + w * t4326.a]]
m = folium.Map(location=[41.7, 1.7], zoom_start=8, tiles="OpenStreetMap")
folium.raster_layers.ImageOverlay(str(OUT / "_type_overlay.png"), bounds=bounds, name="System-role type").add_to(m)
folium.raster_layers.ImageOverlay(str(OUT / "_excl_overlay.png"), bounds=bounds, name="Hard exclusions").add_to(m)
fg = folium.FeatureGroup(name="Battery projects")
for (_, s), (_, hrow) in zip(pts.to_crs(4326).iterrows(), hit.iterrows()):
    folium.CircleMarker([s.geometry.y, s.geometry.x], radius=4, color="black", fill=True, fill_color="white", fill_opacity=1,
                        tooltip=f"{s.mw:.1f} MW | type: {NAMES.get(str(hrow.cluster), hrow.cluster)} | nearest node {hrow.nearest_ree_node}").add_to(fg)
fg.add_to(m)
fn = folium.FeatureGroup(name="REE nodes (Nov 2026)")
for _, r in nodes.to_crs(4326).iterrows():
    tip = (f"<b>{r.ree_node}</b><br>gen granted {r.gen_granted_mw:.0f} MW | storage granted+pending {r.storage_queue_mw:.0f} MW"
           f"<br>room for storage {r.storage_room_mw:.0f} MW | reason: {r.gen_unavailable_reason}"
           f"{' | TENDER NODE' if r.tender else ''}{' | UNDER CONSTRUCTION' if r.under_construction else ''}")
    if r.under_construction:
        folium.RegularPolygonMarker([r.geometry.y, r.geometry.x], number_of_sides=4, radius=7, color="black", fill=False, weight=1.5, tooltip=tip).add_to(fn)
    else:
        folium.RegularPolygonMarker([r.geometry.y, r.geometry.x], number_of_sides=4, radius=4, color="black", fill=True, fill_color="black", fill_opacity=1, tooltip=tip).add_to(fn)
    if r.storage_room_mw > 0:
        folium.CircleMarker([r.geometry.y, r.geometry.x], radius=11, color="#00b7ff", fill=False, weight=2.5, tooltip=tip).add_to(fn)
    if r.tender:
        folium.RegularPolygonMarker([r.geometry.y, r.geometry.x], number_of_sides=3, radius=9, color="black", fill=True, fill_color="#ffd400", fill_opacity=1, tooltip=tip).add_to(fn)
fn.add_to(m)
folium.LayerControl(collapsed=False).add_to(m)
items = "".join(f'<div><span style="background:{palette[c]};padding:0 10px;margin-right:6px">&nbsp;</span>'
                f'{NAMES.get(str(c), "cluster " + str(c))} <small>({prof.area_share[c]:.0%} of land, '
                f'{int(bess_by.n_sites.get(c, 0))} projects)</small></div>' for c in range(K))
m.get_root().html.add_child(folium.Element(
    f'<div style="position:fixed;bottom:20px;left:20px;z-index:1000;background:white;padding:10px 12px;border:1px solid #999;'
    f'font:12px sans-serif;max-width:360px"><b>BESS location typology v2 (local trial)</b><br>k-means, k={K}, per 500 m pixel. '
    f'Node data: REE access-capacity files of 3 Nov 2026, coordinates matched to OpenStreetMap. Darkened = protected / flood / urban.'
    f'<br>{items}<div style="margin-top:6px">&#9632; REE node &nbsp; &#9633; under construction &nbsp; '
    f'<span style="color:#00b7ff">&#9675;</span> room for storage &nbsp; <span style="color:#d4a800">&#9650;</span> tender node</div></div>'))
m.save(OUT / "typology.html")
json.dump({"k": K, "n_pixels": int(len(cells)), "features": list(FEATS), "node_source": str(NODES.relative_to(ROOT)),
           "node_cutoff_km": NODE_CUTOFF_M / 1000, "k_selection": rows_k,
           "nodes_with_storage_room": int((nodes.storage_room_mw > 0).sum()), "tender_nodes": int(nodes.tender.sum()),
           "under_construction": int(nodes.under_construction.sum())}, open(OUT / "metrics.json", "w"), indent=2)
log(f"done -> {OUT}")
