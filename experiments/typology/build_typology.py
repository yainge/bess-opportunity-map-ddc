#!/usr/bin/env python
"""Local test: data-derived typology of BESS locations by the system problem they would address.

Input: the 500 m pixel grid with features built by experiments/heatmap/build_heatmap.py.
Method: standardise grid/renewables/demand features (not land feasibility), cluster with k-means,
choose k by silhouette and bootstrap stability, profile each cluster, then overlay the existing
battery projects to see which types developers are actually targeting.

Run from the repo root:
    experiments/heatmap/.venv/bin/python experiments/typology/build_typology.py
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
from sklearn.cluster import KMeans
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sklearn.preprocessing import StandardScaler

matplotlib.use("Agg")
ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
GRID = ROOT / "experiments" / "heatmap" / "output" / "heatmap_grid_500m.gpkg"
OUT = Path(__file__).resolve().parent / "output"
OUT.mkdir(exist_ok=True)
CRS = "EPSG:25831"
CELL = 500
SEED = 42
T0 = time.time()
log = lambda m: print(f"[{time.time() - T0:5.0f}s] {m}", flush=True)

log("loading pixel grid")
cells = gpd.read_file(GRID)
log(f"{len(cells):,} land pixels")

# node-level attributes of the nearest REE node: occupation share and room for storage
ree = pd.read_excel(RAW / "Dataset_SusbtationNodes.xlsx", sheet_name="Data")
ree["occupation_share"] = 1 - ree["Not occupied margin [MW]"] / ree["Node Access Capacity [MW]"].replace(0, np.nan)
ree["occupation_share"] = ree["occupation_share"].clip(0, 1)
node_attr = ree.set_index("Node")[["occupation_share", "AvailableStorage CPE MPE [MW]", "Voltage kV"]]
node_attr.columns = ["node_occupation_share", "node_storage_room_mw", "node_voltage_kv"]
cells = cells.merge(node_attr, left_on="nearest_ree_node", right_index=True, how="left")

# ------------------------------------------------------------------ features for the typology
# System-role features only. Land feasibility (suitable land, roads, exclusions) is left out on
# purpose: it says whether a battery can be built, not what it would do.
FEATS = {
    "dist_substation_km": "capped",
    "dist_substation_400kv_km": "capped",
    "access_capacity_nearest_node_mw": "log",
    "node_occupation_share": "none",
    "node_storage_room_mw": "log",
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
    # stability: refit on bootstrap halves and compare on the common sample
    aris = []
    for b in range(5):
        idx = rng.choice(len(Xs), len(Xs) // 2, replace=False)
        km_b = KMeans(n_clusters=k, n_init=5, random_state=SEED + b + 1).fit(Xs[idx])
        aris.append(adjusted_rand_score(km.labels_[sample], km_b.predict(Xs[sample])))
    rows_k.append({"k": k, "silhouette": round(sil, 3), "stability_ari": round(float(np.mean(aris)), 3),
                   "inertia": round(km.inertia_)})
    log(f"k={k} silhouette {sil:.3f} stability {np.mean(aris):.3f}")
kdf = pd.DataFrame(rows_k)
kdf.to_csv(OUT / "k_selection.csv", index=False)
print(kdf.to_string(index=False))
# choose: best silhouette among k >= 4 with stability >= 0.7 (k=3 tends to be near/far/urban only)
ok = kdf[(kdf.k >= 4) & (kdf.stability_ari >= 0.7)]
K = int((ok if len(ok) else kdf[kdf.k >= 4]).sort_values("silhouette", ascending=False).k.iloc[0])
log(f"chosen k = {K}")

km = KMeans(n_clusters=K, n_init=20, random_state=SEED).fit(Xs)
cells["cluster"] = km.labels_

# ------------------------------------------------------------------ profiles
raw_cols = list(FEATS) + ["suitable_land_share_1km", "excluded"]
prof = cells.groupby("cluster")[raw_cols].median(numeric_only=True)
prof["n_pixels"] = cells.groupby("cluster").size()
prof["area_share"] = (prof.n_pixels / len(cells)).round(3)
# standardised centroid (z-scores) to see what distinguishes each cluster
z = pd.DataFrame(km.cluster_centers_, columns=list(FEATS)).round(2)
z.index.name = "cluster"
prof.round(2).to_csv(OUT / "cluster_profiles_median.csv")
z.to_csv(OUT / "cluster_centroids_zscore.csv")
print("\nmedian profile per cluster:\n", prof.round(2).T.to_string())
print("\nz-score centroids (what makes each cluster different):\n", z.T.to_string())

# ------------------------------------------------------------------ existing BESS projects by type
bess = gpd.read_file(RAW / "storage" / "ENERGIA_BATERIES_STANDALONE_20261105.gpkg").to_crs(CRS)
bess = bess[bess.ESTAT != "No autoritzat"]
sites = gpd.GeoDataFrame(geometry=list(bess.geometry.union_all().geoms), crs=CRS)  # 76 footprints
sites["mw"] = 0.0
j = gpd.sjoin(bess[["POTENCIA", "geometry"]], sites.reset_index(), predicate="intersects")
sites["mw"] = j.groupby("index")["POTENCIA"].sum().reindex(sites.index).fillna(0).to_numpy()
pts = sites.copy(); pts["geometry"] = pts.representative_point()
hit = gpd.sjoin(pts, cells[["cluster", "geometry"]], how="left", predicate="within")
hit = hit[~hit.index.duplicated()]
bess_by = hit.groupby("cluster").agg(n_sites=("mw", "size"), mw=("mw", "sum"))
bess_by["site_share"] = (bess_by.n_sites / bess_by.n_sites.sum()).round(3)
bess_by["area_share"] = prof.area_share
bess_by["ratio_sites_vs_area"] = (bess_by.site_share / bess_by.area_share).round(2)
bess_by.to_csv(OUT / "bess_projects_by_cluster.csv")
print("\nexisting battery projects per cluster:\n", bess_by.to_string())

# ------------------------------------------------------------------ names (edit after reading profiles)
NAMES = json.loads((Path(__file__).resolve().parent / "cluster_names.json").read_text()) \
    if (Path(__file__).resolve().parent / "cluster_names.json").exists() else {}
cells["type"] = cells.cluster.map(lambda c: NAMES.get(str(c), f"cluster {c}"))

# ------------------------------------------------------------------ outputs
cells.to_file(OUT / "typology_grid_500m.gpkg", layer="cells", driver="GPKG")
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
show = np.ma.masked_equal(clu_r, 255)
ax.imshow(show, extent=extent, cmap=cmap, vmin=-0.5, vmax=K - 0.5, interpolation="nearest")
hatch = np.zeros((nrow, ncol, 4)); hatch[exc_r] = (0, 0, 0, 0.35)
ax.imshow(hatch, extent=extent, interpolation="nearest")
pts.plot(ax=ax, color="white", edgecolor="black", markersize=24, zorder=5)
handles = [plt.Rectangle((0, 0), 1, 1, color=palette[c]) for c in range(K)]
labels = [f"{c}: {NAMES.get(str(c), 'cluster ' + str(c))} ({prof.area_share[c]:.0%} of land, "
          f"{int(bess_by.n_sites.get(c, 0))} projects)" for c in range(K)]
handles.append(plt.Rectangle((0, 0), 1, 1, color=(0, 0, 0, 0.35))); labels.append("hard exclusion (darkened)")
ax.legend(handles, labels, loc="lower left", fontsize=8, title="System-role type (k-means on grid, renewables, demand)")
ax.set_title("Data-derived typology of BESS locations in Catalonia (white = existing battery projects)", fontsize=11)
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
    folium.CircleMarker([s.geometry.y, s.geometry.x], radius=4, color="black", fill=True, fill_color="white",
                        fill_opacity=1, tooltip=f"{s.mw:.1f} MW | type: {NAMES.get(str(hrow.cluster), hrow.cluster)}").add_to(fg)
fg.add_to(m)
folium.LayerControl(collapsed=False).add_to(m)
items = "".join(f'<div><span style="background:{palette[c]};padding:0 10px;margin-right:6px">&nbsp;</span>'
                f'{NAMES.get(str(c), "cluster " + str(c))} <small>({prof.area_share[c]:.0%} of land, '
                f'{int(bess_by.n_sites.get(c, 0))} projects)</small></div>' for c in range(K))
m.get_root().html.add_child(folium.Element(
    f'<div style="position:fixed;bottom:20px;left:20px;z-index:1000;background:white;padding:10px 12px;border:1px solid #999;'
    f'font:12px sans-serif;max-width:340px"><b>BESS location typology (local test)</b><br>k-means, k={K}, on grid, '
    f'renewables and demand features per 500 m pixel. Darkened = protected / flood / urban.<br>{items}</div>'))
m.save(OUT / "typology.html")
json.dump({"k": K, "n_pixels": int(len(cells)), "features": list(FEATS), "k_selection": rows_k},
          open(OUT / "metrics.json", "w"), indent=2)
log(f"done -> {OUT}")
