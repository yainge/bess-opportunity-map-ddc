#!/usr/bin/env python
"""Option 2: market segments of the existing stand-alone battery projects in Catalonia.

Unit: one site = one connected footprint in the Generalitat layer (rows that share a footprint,
e.g. seven 4.5 MW phases filed by seven companies, are aggregated). Each site gets project
attributes (MW, area, status, land class, procedure, promoters) and location attributes from the
500 m pixel grid and from Fernando's matched REE node table. Sites are clustered with Ward
hierarchical clustering on standardised features; k is chosen by silhouette. Each segment is then
profiled, including the authorisation rate, which is the outcome a developer cares about.

Run from the repo root:
    experiments/heatmap/.venv/bin/python experiments/segments/build_project_segments.py
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
from matplotlib import pyplot as plt
from scipy.spatial import cKDTree
from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

matplotlib.use("Agg")
ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
GRID = ROOT / "experiments" / "heatmap" / "output" / "heatmap_grid_500m.gpkg"
NODES = ROOT / "data" / "processed" / "grid_topology" / "ree_nodes_matched.csv"
HERE = Path(__file__).resolve().parent
OUT = HERE / "output"
OUT.mkdir(exist_ok=True, parents=True)
CRS = "EPSG:25831"
T0 = time.time()
log = lambda m: print(f"[{time.time() - T0:5.0f}s] {m}", flush=True)

# ------------------------------------------------------------------ sites from project rows
b = gpd.read_file(RAW / "storage" / "ENERGIA_BATERIES_STANDALONE_20261105.gpkg").to_crs(CRS)
b = b[b.ESTAT != "No autoritzat"].copy()
b["year"] = pd.to_numeric(b.EXPEDIENT.str.extract(r"(20\d\d)")[0], errors="coerce")
b["authorised"] = b.ESTAT.str.startswith("Autoritzat")
b["ministry"] = b.OFICINA.eq("Ministerio") | b.ESTAT.str.contains("Ministerio")
b["urban_land"] = b.TIPUS_SOL.ne("Sòl no urbanitzable")
b["le5mw"] = b.POTENCIA <= 5.01
sites = gpd.GeoDataFrame(geometry=list(b.geometry.union_all().geoms), crs=CRS).reset_index(names="site_id")
j = gpd.sjoin(b, sites, predicate="intersects")[["site_id", "NOM", "PROMOTOR", "POTENCIA", "SUPERFICIE", "year", "authorised",
                                                  "ministry", "urban_land", "le5mw", "TRAMIT_AMB", "ESTAT_AMB", "ESTAT", "OFICINA"]]
j = j[~j.index.duplicated()]
agg = j.groupby("site_id").agg(
    name=("NOM", lambda s: s.iloc[0]), n_rows=("NOM", "size"), mw=("POTENCIA", "sum"), mw_max_row=("POTENCIA", "max"),
    area_ha=("SUPERFICIE", "sum"), n_promoters=("PROMOTOR", "nunique"), promoter=("PROMOTOR", lambda s: s.mode().iloc[0]),
    year=("year", "min"), authorised=("authorised", "max"), any_authorised_share=("authorised", "mean"),
    ministry=("ministry", "max"), urban_land=("urban_land", "mean"), all_rows_le5mw=("le5mw", "min"),
    eia_ordinary=("ESTAT_AMB", lambda s: s.eq("Cal AIA ordinària").any() or s.eq("DIA Favorable").any()),
    status=("ESTAT", lambda s: "; ".join(sorted(set(s)))))
sites = sites.merge(agg, left_on="site_id", right_index=True)
sites["area_ha"] = np.where(sites.area_ha > 0, sites.area_ha, sites.geometry.area / 1e4)
sites["split_filing"] = (sites.n_rows > 1) & sites.all_rows_le5mw
sites["geometry_pt"] = sites.representative_point()
log(f"{len(b)} project rows -> {len(sites)} sites, {sites.mw.sum():.0f} MW; split filings (several <=5 MW rows on one site): {sites.split_filing.sum()}")

# ------------------------------------------------------------------ location attributes
cells = gpd.read_file(GRID)
pix_cols = ["dist_substation_km", "dist_substation_400kv_km", "dist_distribution_substation_km", "dist_major_road_km",
            "demand_mwh_10km", "distribution_load_mw_10km", "renewable_operating_mw_10km", "renewable_pipeline_mw_10km",
            "suitable_land_share_1km", "protected_share", "flood_share", "urban_share"]
pts = gpd.GeoDataFrame(sites[["site_id"]], geometry=sites.geometry_pt, crs=CRS)
hit = gpd.sjoin_nearest(pts, cells[pix_cols + ["geometry"]], how="left", max_distance=2000)
hit = hit[~hit.index.duplicated()]
sites = sites.merge(hit[["site_id"] + pix_cols], on="site_id", how="left")
mun = gpd.read_file(RAW / "gis" / "municipalities.gpkg").to_crs(CRS)
m = gpd.sjoin_nearest(pts, mun[["municipality_name", "geometry"]], how="left")
m = m[~m.index.duplicated()]
sites["municipality"] = m.municipality_name.to_numpy()

n = pd.read_csv(NODES)
nodes = gpd.GeoDataFrame(n, geometry=gpd.points_from_xy(n.lon, n.lat), crs="EPSG:4326").to_crs(CRS)
f0 = lambda c: pd.to_numeric(nodes[c], errors="coerce").fillna(0)
nodes["storage_queue_mw"] = f0("storage_granted_MW_genfile") + f0("storage_pending_MW_genfile")
nodes["storage_room_mw"] = np.maximum(f0("storage_available_MPE_RdT_MW (generation mode)"), f0("storage_available_MPE_RdT_MW (demand mode)"))
d, i = cKDTree(np.c_[nodes.geometry.x, nodes.geometry.y]).query(np.c_[pts.geometry.x, pts.geometry.y])
sites["nearest_node"] = nodes.ree_node.to_numpy()[i]
sites["dist_node_km"] = d / 1000
sites["node_kv"] = nodes.kv.to_numpy()[i]
sites["node_storage_queue_mw"] = nodes.storage_queue_mw.to_numpy()[i]
sites["node_storage_room_mw"] = nodes.storage_room_mw.to_numpy()[i]
sites["node_gen_reason"] = nodes.gen_unavailable_reason.fillna("").to_numpy()[i]

# ------------------------------------------------------------------ clustering
# Distances are log-scaled: three remote sites (15 km from any distribution substation) otherwise
# dominate the Ward tree. Area and node queue were tested and dropped (area duplicates MW; the
# queue is a node attribute, not a project attribute).
FEATS = {
    "mw": "log", "dist_substation_km": "log", "dist_substation_400kv_km": "log",
    "dist_distribution_substation_km": "log", "demand_mwh_10km": "log", "renewables_10km_mw": "log",
    "urban_land": "none",
}
sites["renewables_10km_mw"] = sites.renewable_operating_mw_10km.fillna(0) + sites.renewable_pipeline_mw_10km.fillna(0)
X = pd.DataFrame({f: (np.log1p(sites[f].astype(float).fillna(0)) if tr == "log" else sites[f].astype(float).fillna(0))
                  for f, tr in FEATS.items()})
Xs = StandardScaler().fit_transform(X)
rows_k = []
for k in range(2, 7):
    lab = AgglomerativeClustering(n_clusters=k, linkage="ward").fit_predict(Xs)
    rows_k.append({"k": k, "silhouette": round(float(silhouette_score(Xs, lab)), 3), "min_size": int(np.bincount(lab).min())})
kdf = pd.DataFrame(rows_k); print(kdf.to_string(index=False))
# Silhouette is flat (about 0.19 to 0.24 for k = 3..6) with 74 sites, so it cannot pick k. k = 4 is
# fixed: the smallest k at which size, urban land and distance to the transmission grid separate,
# and each segment except the remote outliers has at least 15 sites. Reported in the README.
K = 4
sites["segment"] = AgglomerativeClustering(n_clusters=K, linkage="ward").fit_predict(Xs)
# order segments by median MW so numbering is stable and readable
order = sites.groupby("segment").mw.median().sort_values().index.tolist()
sites["segment"] = sites.segment.map({old: new for new, old in enumerate(order)})
log(f"k = {K}")

# ------------------------------------------------------------------ profiles
g = sites.groupby("segment")
prof = pd.DataFrame({
    "n_sites": g.size(), "n_rows": g.n_rows.sum(), "total_mw": g.mw.sum().round(0), "median_mw": g.mw.median().round(1),
    "share_split_filing": g.split_filing.mean().round(2), "share_urban_land": g.urban_land.mean().round(2),
    "share_authorised": g.authorised.mean().round(2), "share_ministry": g.ministry.mean().round(2),
    "share_eia_ordinary": g.eia_ordinary.mean().round(2),
    "median_dist_substation_km": g.dist_substation_km.median().round(1),
    "median_dist_400kv_km": g.dist_substation_400kv_km.median().round(1),
    "median_dist_distribution_sub_km": g.dist_distribution_substation_km.median().round(1),
    "median_demand_gwh_10km": (g.demand_mwh_10km.median() / 1000).round(0),
    "median_renewables_10km_mw": g.renewables_10km_mw.median().round(0),
    "median_node_queue_mw": g.node_storage_queue_mw.median().round(0),
    "share_node_with_room": g.node_storage_room_mw.apply(lambda s: (s > 0).mean()).round(2),
    "n_promoters": g.promoter.nunique(),
    "top_promoter_share": g.promoter.apply(lambda s: s.value_counts(normalize=True).iloc[0]).round(2),
    "median_year": g.year.median(),
    "municipalities": g.municipality.apply(lambda s: ", ".join(s.value_counts().head(4).index)),
})
z = pd.DataFrame(StandardScaler().fit_transform(X), columns=list(FEATS)).groupby(sites.segment).mean().round(2)
prof.to_csv(OUT / "segment_profiles.csv"); z.to_csv(OUT / "segment_centroids_zscore.csv")
kdf.to_csv(OUT / "k_selection.csv", index=False)
print("\nsegment profiles:\n", prof.T.to_string()); print("\nz-score centroids:\n", z.T.to_string())
print(f"\noverall authorised share: {sites.authorised.mean():.2f} ({sites.authorised.sum()} of {len(sites)} sites)")

names_file = HERE / "segment_names.json"
NAMES = json.loads(names_file.read_text()) if names_file.exists() else {}
sites["segment_name"] = sites.segment.map(lambda c: NAMES.get(str(c), f"segment {c}"))
out = sites.drop(columns=["geometry_pt"])
out.to_file(OUT / "project_sites_segments.gpkg", driver="GPKG")
out.drop(columns="geometry").to_csv(OUT / "project_sites_segments.csv", index=False)

# ------------------------------------------------------------------ maps
palette = ["#1b9e77", "#d95f02", "#7570b3", "#e7298a", "#66a61e", "#e6ab02"][:K]
cat = gpd.read_file(RAW / "grid" / "osm_pypsa_transmission_catalonia_20261105.gpkg", layer="catalonia_nuts2").to_crs(CRS)
lines = gpd.read_file(RAW / "grid" / "osm_pypsa_transmission_catalonia_20261105.gpkg", layer="lines").to_crs(CRS)
fig, ax = plt.subplots(figsize=(11, 10))
cat.plot(ax=ax, color="#f2f2f2", edgecolor="#999")
lines.plot(ax=ax, color="#bbb", linewidth=0.6)
for c in range(K):
    s = sites[sites.segment == c]
    ax.scatter(s.geometry_pt.x, s.geometry_pt.y, s=12 + 3 * s.mw, color=palette[c], edgecolor="black", linewidth=0.5, alpha=0.85,
               label=f"{c}: {NAMES.get(str(c), 'segment ' + str(c))} ({len(s)} sites, {s.mw.sum():.0f} MW, {s.authorised.mean():.0%} authorised)")
ax.legend(loc="upper left", bbox_to_anchor=(0, -0.01), fontsize=8, frameon=False, title="Project segments (Ward clustering, size = MW)")
ax.set_title("Market segments of stand-alone battery projects in Catalonia (Generalitat register, Nov 2026)", fontsize=11)
ax.set_axis_off()
fig.savefig(OUT / "segments.png", dpi=160, bbox_inches="tight"); plt.close(fig)

m = folium.Map(location=[41.7, 1.7], zoom_start=8, tiles="OpenStreetMap")
for c in range(K):
    fg = folium.FeatureGroup(name=f"{c}: {NAMES.get(str(c), 'segment ' + str(c))}")
    for _, s in sites[sites.segment == c].to_crs(4326).iterrows():
        p = s.geometry_pt if hasattr(s.geometry_pt, "x") else s.geometry.representative_point()
        lon, lat = gpd.GeoSeries([sites.loc[s.name, "geometry_pt"]], crs=CRS).to_crs(4326).iloc[0].coords[0]
        tip = (f"<b>{s['name']}</b> ({s.municipality})<br>{s.mw:.1f} MW in {s.n_rows} filing(s), {s.n_promoters} promoter(s)"
               f"<br>status: {s.status}<br>land: {'urban/other' if s.urban_land >= 0.5 else 'non-urban'} | EIA ordinary: {bool(s.eia_ordinary)}"
               f"<br>nearest node {s.nearest_node} at {s.dist_node_km:.1f} km | queue {s.node_storage_queue_mw:.0f} MW | room {s.node_storage_room_mw:.0f} MW"
               f"<br>distribution substation {s.dist_distribution_substation_km:.1f} km | 400 kV {s.dist_substation_400kv_km:.1f} km")
        folium.CircleMarker([lat, lon], radius=4 + 0.12 * s.mw, color="black", weight=0.6, fill=True, fill_color=palette[c],
                            fill_opacity=0.85, tooltip=tip).add_to(fg)
    fg.add_to(m)
folium.LayerControl(collapsed=False).add_to(m)
items = "".join(f'<div><span style="background:{palette[c]};padding:0 10px;margin-right:6px">&nbsp;</span>'
                f'{NAMES.get(str(c), "segment " + str(c))} <small>({int(prof.n_sites[c])} sites, {prof.total_mw[c]:.0f} MW, '
                f'{prof.share_authorised[c]:.0%} authorised)</small></div>' for c in range(K))
m.get_root().html.add_child(folium.Element(
    f'<div style="position:fixed;bottom:20px;left:20px;z-index:1000;background:white;padding:10px 12px;border:1px solid #999;'
    f'font:12px sans-serif;max-width:380px"><b>Battery project segments (local trial)</b><br>Ward clustering of {len(sites)} sites '
    f'on size, land, grid distances, demand, renewables and node queue. Circle size = MW.<br>{items}</div>'))
m.save(OUT / "segments.html")
json.dump({"k": K, "n_sites": int(len(sites)), "n_rows": int(len(b)), "features": list(FEATS), "k_selection": rows_k},
          open(OUT / "metrics.json", "w"), indent=2)
log(f"done -> {OUT}")
