#!/usr/bin/env python
"""Local test, variant 2: heat map fitted only near substations.

Same features and model as build_heatmap.py, but the model is fitted and applied only to land
within DOMAIN_KM of a real 220/400 kV substation. This removes the dominant "distance to
substation" signal and lets the other features decide which near-substation areas look like
developer choices. Land beyond the domain is shown as "not modelled".

Presence-background model. Positives are the 500 m pixels that contain a stand-alone battery
project from the Generalitat layer (any status except refused); every other land pixel is
background. A regularised logistic regression on per-pixel grid, renewables, demand and land
features gives the weights; the predicted probability per pixel is the heat map colour.
Hard exclusions (protected areas, T100 flood zones, urban zoning) are drawn as a red overlay,
not removed from the model.

Run from the repo root with the experiment environment:
    experiments/heatmap/.venv/bin/python experiments/heatmap/build_heatmap.py
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
import pyogrio
import rasterio
from matplotlib import pyplot as plt
from rasterio import features as rfeatures
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.warp import calculate_default_transform, reproject
from scipy import ndimage
from shapely.geometry import box
from shapely.strtree import STRtree
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

matplotlib.use("Agg")

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
OUT = Path(__file__).resolve().parent / "output_near_substation"
DOMAIN_KM = 10   # model domain: land within this distance of a 220/400 kV substation
OUT.mkdir(exist_ok=True)
CRS = "EPSG:25831"
CELL = 500          # model / map pixel (m)
FINE = 100          # rasterisation resolution for land layers (m)
RADIUS_KM = 10      # neighbourhood for MW and demand sums, same as the pipeline
SEED = 42
T0 = time.time()


def log(msg: str) -> None:
    print(f"[{time.time() - T0:6.0f}s] {msg}", flush=True)


# ----------------------------------------------------------------------------- frame
def make_frame(cat: gpd.GeoSeries, cell: int):
    minx, miny, maxx, maxy = cat.total_bounds
    minx, miny = np.floor(minx / cell) * cell, np.floor(miny / cell) * cell
    maxx, maxy = np.ceil(maxx / cell) * cell, np.ceil(maxy / cell) * cell
    ncol, nrow = int((maxx - minx) / cell), int((maxy - miny) / cell)
    transform = from_origin(minx, maxy, cell, cell)
    return transform, (nrow, ncol)


def rasterize(geoms, transform, shape, values=None, all_touched=False, dtype="float32"):
    shapes = zip(geoms, values) if values is not None else ((g, 1) for g in geoms)
    return rfeatures.rasterize(shapes, out_shape=shape, transform=transform, fill=0,
                               all_touched=all_touched, dtype=dtype)


def disc_kernel(radius_cells: float) -> np.ndarray:
    r = int(np.ceil(radius_cells))
    y, x = np.ogrid[-r:r + 1, -r:r + 1]
    return (x * x + y * y <= radius_cells * radius_cells).astype("float32")


def sum_within(raster: np.ndarray, radius_m: float, cell: int) -> np.ndarray:
    return ndimage.convolve(raster, disc_kernel(radius_m / cell), mode="constant", cval=0.0)


def fine_to_coarse_mean(fine: np.ndarray, factor: int) -> np.ndarray:
    nrow, ncol = fine.shape[0] // factor, fine.shape[1] // factor
    return fine[: nrow * factor, : ncol * factor].reshape(nrow, factor, ncol, factor).mean(axis=(1, 3))


def nearest_distance_km(points_xy: np.ndarray, geoms) -> np.ndarray:
    tree = STRtree(list(geoms))
    pts = gpd.points_from_xy(points_xy[:, 0], points_xy[:, 1])
    idx = tree.nearest(pts)
    return np.array([pts[i].distance(tree.geometries[j]) for i, j in enumerate(idx)]) / 1000


# ----------------------------------------------------------------------------- inputs
log("reading Catalonia boundary and municipalities")
muni = gpd.read_file(RAW / "gis" / "municipalities.gpkg").to_crs(CRS)
muni["municipality_code"] = muni["municipality_code"].astype(str).str.zfill(6).str[:5]
cat_geom = muni.geometry.union_all()
transform, shape = make_frame(muni.geometry, CELL)
nrow, ncol = shape
log(f"frame {nrow} rows x {ncol} cols at {CELL} m")
factor = CELL // FINE
ftransform = from_origin(transform.c, transform.f, FINE, FINE)  # same origin as the 500 m frame
fshape = (nrow * factor, ncol * factor)

land_mask = rasterize([cat_geom], transform, shape, dtype="uint8").astype(bool)
rows, cols = np.where(land_mask)
xs, ys = rasterio.transform.xy(transform, rows, cols)  # cell centres
cxy = np.column_stack([xs, ys])
log(f"{len(cxy):,} land pixels")

# --- grid: OSM transmission (lines, real substations) and REE node access capacity
log("grid features")
gpk = RAW / "grid" / "osm_pypsa_transmission_catalonia_20261105.gpkg"
lines = gpd.read_file(gpk, layer="lines").to_crs(CRS)
subs = gpd.read_file(gpk, layer="substations").to_crs(CRS)
subs = subs[~subs.bus_id.str.startswith("virtual")]
ree = pd.read_excel(RAW / "Dataset_SusbtationNodes.xlsx", sheet_name="Data")
ree_g = gpd.GeoDataFrame(ree, geometry=gpd.points_from_xy(ree["Coordinates y"], ree["Coordinates x"]),
                         crs="EPSG:4326").to_crs(CRS)
f_dist_sub = nearest_distance_km(cxy, subs.geometry)
f_dist_sub400 = nearest_distance_km(cxy, subs[subs.voltage == 400].geometry)
f_dist_line = nearest_distance_km(cxy, lines.geometry)
tree_ree = STRtree(list(ree_g.geometry))
pts = gpd.points_from_xy(cxy[:, 0], cxy[:, 1])
near_ree = tree_ree.nearest(pts)
cap = ree_g["Node Access Capacity [MW]"].fillna(0).to_numpy()
d_ree = np.array([pts[i].distance(tree_ree.geometries[j]) for i, j in enumerate(near_ree)]) / 1000
f_access_cap = np.where(d_ree <= 20, cap[near_ree], 0.0)   # nearest REE node within 20 km
f_nearest_ree_node = ree_g["Node"].to_numpy()[near_ree]

# --- renewables: operating and pipeline MW within 10 km (Isabella's files)
log("renewables features")
status_map = {"En servei": "operating", "Servei": "operating", "Autoritzat": "pipeline",
              "En tramitació": "pipeline"}
sol = pd.read_csv(RAW / "renewables" / "ENERGIA_PARCSSOLARS_MULTIPOLI_20261015.csv", sep=";",
                  encoding="utf-8-sig")
win = pd.read_csv(RAW / "renewables" / "ENERGIA_EOLICA_CATALUNYA_20261015.csv", sep=";",
                  encoding="utf-8-sig")
ren = pd.concat([
    sol.rename(columns={"POTENCIA": "mw"})[["mw", "ESTAT", "X_UTM31N", "Y_UTM31N"]],
    win.rename(columns={"POTENCIA_MW": "mw"})[["mw", "ESTAT", "X_UTM31N", "Y_UTM31N"]],
])
ren["cat"] = ren.ESTAT.map(status_map)
ren = ren.dropna(subset=["cat", "mw", "X_UTM31N", "Y_UTM31N"])
ren_g = gpd.GeoDataFrame(ren, geometry=gpd.points_from_xy(ren.X_UTM31N, ren.Y_UTM31N), crs=CRS)
ren_rasters = {}
for c in ("operating", "pipeline"):
    sub = ren_g[ren_g.cat == c]
    r = rasterize(sub.geometry, transform, shape, values=sub.mw.astype("float32"))
    ren_rasters[c] = sum_within(r, RADIUS_KM * 1000, CELL)
f_ren_op = ren_rasters["operating"][rows, cols]
f_ren_pipe = ren_rasters["pipeline"][rows, cols]

# --- demand: municipal consumption 2023 spread over municipal area, summed within 10 km;
#     e-distribución connected load within 10 km (file is EPSG:25830)
log("demand features")
dem = pd.read_csv(RAW / "demand" / "municipal_electricity_consumption_by_sector_2023.csv",
                  dtype={"muni_code": str})
dem_tot = dem.groupby("muni_code")["consumption_kwh"].sum().div(1000).rename("mwh")  # MWh
muni = muni.merge(dem_tot, left_on="municipality_code", right_index=True, how="left")
muni["mwh_per_cell"] = muni.mwh.fillna(0) / (muni.geometry.area / CELL**2)
dem_raster = rasterize(muni.geometry, transform, shape, values=muni.mwh_per_cell.astype("float32"))
f_demand_10km = sum_within(dem_raster, RADIUS_KM * 1000, CELL)[rows, cols]
edis = pd.read_csv(RAW / "demand" / "edistribucion_demand_capacity_catalonia_2026-10.csv")
edis_g = gpd.GeoDataFrame(edis, geometry=gpd.points_from_xy(edis.x, edis.y), crs="EPSG:25830").to_crs(CRS)
load_raster = rasterize(edis_g.geometry, transform, shape, values=edis_g.occ_mw.astype("float32"))
f_load_10km = sum_within(load_raster, RADIUS_KM * 1000, CELL)[rows, cols]
f_dist_distsub = nearest_distance_km(cxy, edis_g.geometry)

# --- land: suitable share within 1 km, road distance, exclusion shares
log("land features: roads")
roads = gpd.read_file(RAW / "gis" / "roads.gpkg").to_crs(CRS)
roads = roads[roads.road_class.isin(["motorway", "primary"])]
f_dist_road = nearest_distance_km(cxy, roads.geometry)

log("land features: exclusion layers")
excl = {}
for name, path, layer_filter in (
    ("protected", RAW / "gis" / "protected_areas.gpkg", None),
    ("flood", RAW / "gis" / "flood_zones.gpkg", None),
    ("urban", RAW / "gis" / "zoning.gpkg", ("zone_class", ["urban_residential", "urban_core"])),
):
    g = gpd.read_file(path).to_crs(CRS)
    if layer_filter:
        g = g[g[layer_filter[0]].isin(layer_filter[1])]
    fine = rasterize(g.geometry, ftransform, fshape, dtype="uint8", all_touched=False)
    excl[name] = fine_to_coarse_mean(fine.astype("float32"), factor)[:nrow, :ncol]
    log(f"  {name}: {len(g):,} features, {excl[name][land_mask].mean():.1%} of land area")

log("land features: land cover (streamed rasterisation)")
lc_path = RAW / "gis" / "land_cover.gpkg"
n_feat = pyogrio.read_info(lc_path, layer="land_cover")["features"]
fine_lc = np.zeros(fshape, dtype="uint8")
chunk = 100_000
for start in range(0, n_feat, chunk):
    part = pyogrio.read_dataframe(lc_path, layer="land_cover", skip_features=start,
                                  max_features=chunk, columns=[])
    rfeatures.rasterize(((g, 1) for g in part.geometry), out=fine_lc, transform=ftransform,
                        default_value=1, all_touched=False, merge_alg=rasterio.enums.MergeAlg.replace)
    log(f"  rasterised {min(start + chunk, n_feat):,}/{n_feat:,} land-cover polygons")
suit_coarse = fine_to_coarse_mean(fine_lc.astype("float32"), factor)[:nrow, :ncol]
suit_1km = ndimage.uniform_filter(suit_coarse, size=3, mode="nearest")  # 1.5 km window
f_suit_1km = suit_1km[rows, cols]

# ----------------------------------------------------------------------------- label
log("label: stand-alone battery footprints")
bess = gpd.read_file(RAW / "storage" / "ENERGIA_BATERIES_STANDALONE_20261105.gpkg").to_crs(CRS)
bess = bess[bess.ESTAT != "No autoritzat"]
bess_sites = gpd.GeoSeries(list(bess.geometry.union_all().geoms), crs=CRS) \
    if bess.geometry.union_all().geom_type == "MultiPolygon" else gpd.GeoSeries([bess.geometry.union_all()], crs=CRS)
pos_raster = rasterize(bess.geometry, transform, shape, dtype="uint8", all_touched=True).astype(bool)
y = pos_raster[rows, cols].astype(int)
log(f"{len(bess_sites)} distinct sites -> {y.sum()} positive pixels of {len(y):,}")

# ----------------------------------------------------------------------------- model
# All computed indicators are kept in the output grid; the model uses FEATURES below.
features = pd.DataFrame({
    "dist_substation_km": f_dist_sub,
    "dist_substation_400kv_km": f_dist_sub400,
    "dist_line_km": f_dist_line,
    "access_capacity_nearest_node_mw": f_access_cap,
    "renewable_operating_mw_10km": f_ren_op,
    "renewable_pipeline_mw_10km": f_ren_pipe,
    "demand_mwh_10km": f_demand_10km,
    "distribution_load_mw_10km": f_load_10km,
    "dist_distribution_substation_km": f_dist_distsub,
    "dist_major_road_km": f_dist_road,
    "suitable_land_share_1km": f_suit_1km,
})
# log-transform heavy-tailed quantities so one extreme value does not dominate the fit
LOG_COLS = ["access_capacity_nearest_node_mw", "renewable_operating_mw_10km",
            "renewable_pipeline_mw_10km", "demand_mwh_10km", "distribution_load_mw_10km"]
# distribution_load_mw_10km (r=0.77 with demand) and dist_line_km (r=0.55 with dist_substation)
# are dropped from the model: they duplicate other features and flip signs when included.
FEATURES = ["dist_substation_km", "dist_substation_400kv_km", "access_capacity_nearest_node_mw",
            "renewable_operating_mw_10km", "renewable_pipeline_mw_10km", "demand_mwh_10km",
            "dist_distribution_substation_km", "dist_major_road_km", "suitable_land_share_1km"]
X = features[FEATURES].copy()
for c in [c for c in LOG_COLS if c in X.columns]:
    X[c] = np.log1p(X[c])
for c in [c for c in X.columns if c.startswith("dist_")]:
    X[c] = np.minimum(X[c], 50)

# ---- restrict everything to the model domain (near substations)
domain = f_dist_sub <= DOMAIN_KM
domain_r = np.zeros(shape, dtype=bool); domain_r[rows[domain], cols[domain]] = True
n_pos_out = int(y[~domain].sum())
log(f"domain: {domain.sum():,} of {len(domain):,} land pixels within {DOMAIN_KM} km of a substation; "
    f"{n_pos_out} positive pixel(s) outside the domain are dropped")
X = X.loc[domain].reset_index(drop=True); features = features.loc[domain].reset_index(drop=True)
y = y[domain]; cxy = cxy[domain]; rows = rows[domain]; cols = cols[domain]
f_nearest_ree_node = f_nearest_ree_node[domain]

def fit_model():
    return make_pipeline(StandardScaler(),
                         LogisticRegression(C=0.5, class_weight="balanced", max_iter=2000))

log("spatial block cross-validation")
block_km = 25
groups = (np.floor(cxy[:, 0] / (block_km * 1000)).astype(int) * 1000
          + np.floor(cxy[:, 1] / (block_km * 1000)).astype(int))
oof = np.full(len(y), np.nan)
for tr, te in GroupKFold(n_splits=5).split(X, y, groups):
    if y[tr].sum() == 0:
        continue
    m = fit_model().fit(X.iloc[tr], y[tr])
    oof[te] = m.predict_proba(X.iloc[te])[:, 1]
ok = ~np.isnan(oof)
auc_cv = roc_auc_score(y[ok], oof[ok])
base = -X["dist_substation_km"].to_numpy()
auc_base = roc_auc_score(y, base)
log(f"out-of-fold AUC {auc_cv:.3f}  (baseline: distance to substation alone {auc_base:.3f})")

model = fit_model().fit(X, y)
prob = model.predict_proba(X)[:, 1]
auc_in = roc_auc_score(y, prob)

# coefficients with bootstrap confidence intervals
rng = np.random.default_rng(SEED)
pos_idx, neg_idx = np.where(y == 1)[0], np.where(y == 0)[0]
boots = []
for _ in range(200):
    idx = np.concatenate([rng.choice(pos_idx, len(pos_idx)), rng.choice(neg_idx, min(20000, len(neg_idx)))])
    boots.append(fit_model().fit(X.iloc[idx], y[idx])[-1].coef_[0])
boots = np.array(boots)
coef = pd.DataFrame({
    "feature": X.columns,
    "coef_standardised": model[-1].coef_[0].round(3),
    "ci_low": np.percentile(boots, 2.5, axis=0).round(3),
    "ci_high": np.percentile(boots, 97.5, axis=0).round(3),
    "odds_ratio_per_sd": np.exp(model[-1].coef_[0]).round(2),
    "transform": ["log1p" if c in LOG_COLS else ("capped 50 km" if c.startswith("dist_") else "none")
                  for c in X.columns],
}).sort_values("coef_standardised", key=np.abs, ascending=False)
coef["significant_95"] = (coef.ci_low > 0) | (coef.ci_high < 0)
coef.to_csv(OUT / "coefficients.csv", index=False)
print(coef.to_string(index=False))

# ----------------------------------------------------------------------------- outputs
log("writing rasters and grid")
prob_r = np.full(shape, np.nan, dtype="float32"); prob_r[rows, cols] = prob
excl_share = np.maximum.reduce([excl["protected"], excl["flood"], excl["urban"]])
excluded = (excl_share >= 0.5) & land_mask
profile = dict(driver="GTiff", height=nrow, width=ncol, count=1, crs=CRS, transform=transform,
               compress="deflate")
with rasterio.open(OUT / "heatmap_prob_500m.tif", "w", dtype="float32", nodata=np.nan, **profile) as dst:
    dst.write(prob_r, 1)
with rasterio.open(OUT / "exclusion_mask_500m.tif", "w", dtype="uint8", nodata=255, **profile) as dst:
    m = np.where(land_mask, excluded.astype("uint8"), 255).astype("uint8"); dst.write(m, 1)

cells = gpd.GeoDataFrame(features.assign(
    probability=prob.round(4), label_bess_site=y, excluded=excluded[rows, cols],
    protected_share=excl["protected"][rows, cols].round(2), flood_share=excl["flood"][rows, cols].round(2),
    urban_share=excl["urban"][rows, cols].round(2), nearest_ree_node=f_nearest_ree_node,
    x=cxy[:, 0], y=cxy[:, 1]),
    geometry=[box(x - CELL / 2, yy - CELL / 2, x + CELL / 2, yy + CELL / 2) for x, yy in cxy], crs=CRS)
cells.to_file(OUT / "heatmap_grid_500m.gpkg", layer="cells", driver="GPKG")

# candidate zones: high probability, not excluded, no battery project within 10 km
log("candidate zones")
dist_bess = nearest_distance_km(cxy, bess.geometry)
cand = cells[(~cells.excluded) & (dist_bess > 10)].copy()
cand["dist_existing_bess_km"] = dist_bess[cand.index]
cand = cand.sort_values("probability", ascending=False)
# greedy thinning: keep the best pixel, drop neighbours within 10 km, repeat
keep = []
taken = np.zeros(len(cand), dtype=bool)
cxy_c = np.column_stack([cand.x, cand.y])
for i in range(len(cand)):
    if taken[i]:
        continue
    keep.append(cand.index[i])
    d = np.hypot(cxy_c[:, 0] - cxy_c[i, 0], cxy_c[:, 1] - cxy_c[i, 1])
    taken |= d < 10_000
    if len(keep) >= 20:
        break
top = cells.loc[keep].copy()
top["dist_existing_bess_km"] = dist_bess[keep].round(1)
top = gpd.sjoin_nearest(top, muni[["municipality_name", "geometry"]], how="left").drop(columns="index_right")
top = top[~top.index.duplicated(keep="first")]  # a pixel on a boundary matches two municipalities
top_out = top.drop(columns="geometry").reset_index(drop=True)
top_out.index += 1
top_out.to_csv(OUT / "candidate_zones_top20.csv", index_label="rank")
print(top_out[["municipality_name", "nearest_ree_node", "probability", "dist_substation_km",
               "access_capacity_nearest_node_mw", "renewable_operating_mw_10km",
               "renewable_pipeline_mw_10km", "dist_existing_bess_km"]].round(2).to_string())

metrics = {"domain_km": DOMAIN_KM, "n_domain_pixels": int(len(y)), "n_positive_pixels_outside_domain": n_pos_out,
           "n_land_pixels": int(land_mask.sum()), "n_positive_pixels": int(y.sum()),
           "n_bess_sites": int(len(bess_sites)), "cell_m": CELL, "auc_spatial_cv": round(auc_cv, 3),
           "auc_in_sample": round(auc_in, 3), "auc_baseline_dist_substation": round(auc_base, 3),
           "block_km": block_km, "excluded_share_of_land": round(float(excluded[land_mask].mean()), 3),
           "features": list(X.columns)}
(OUT / "metrics.json").write_text(json.dumps(metrics, indent=2))

# ----------------------------------------------------------------------------- static map
log("static map")
fig, ax = plt.subplots(figsize=(11, 10))
extent = (transform.c, transform.c + ncol * CELL, transform.f - nrow * CELL, transform.f)
im = ax.imshow(prob_r, extent=extent, cmap="viridis", vmin=0, vmax=1, interpolation="nearest")
grey = np.zeros(shape + (4,), dtype="float32"); grey[land_mask & ~domain_r] = (0.75, 0.75, 0.75, 1.0)
ax.imshow(grey, extent=extent, interpolation="nearest")
red = np.zeros(shape + (4,), dtype="float32"); red[excluded & domain_r] = (0.85, 0.1, 0.1, 0.55)
ax.imshow(red, extent=extent, interpolation="nearest")
lines.plot(ax=ax, color="white", linewidth=0.5, alpha=0.8)
bess.representative_point().plot(ax=ax, color="orange", edgecolor="black", markersize=22, zorder=5)
top.representative_point().plot(ax=ax, marker="*", color="white", edgecolor="black", markersize=140, zorder=6)
gpd.GeoSeries([cat_geom], crs=CRS).boundary.plot(ax=ax, color="black", linewidth=0.6)
cb = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02); cb.set_label("P(developer chooses this pixel)")
ax.set_title(f"BESS opportunity heat map, learned weights, fitted within {DOMAIN_KM} km of substations\n"
             f"spatial-CV AUC {auc_cv:.2f}; grey = not modelled (> {DOMAIN_KM} km); red = protected / flood / urban; "
             f"orange = battery projects; stars = top 20 candidate zones", fontsize=10)
ax.set_axis_off()
fig.savefig(OUT / "heatmap.png", dpi=160, bbox_inches="tight"); plt.close(fig)

# ----------------------------------------------------------------------------- web map
log("web map")
dst_crs = "EPSG:4326"
t4326, w, h = calculate_default_transform(CRS, dst_crs, ncol, nrow, *rasterio.transform.array_bounds(nrow, ncol, transform))
def warp(arr, dtype, nodata, resampling):
    out = np.full((h, w), nodata, dtype=dtype)
    reproject(arr.astype(dtype), out, src_transform=transform, src_crs=CRS, dst_transform=t4326,
              dst_crs=dst_crs, src_nodata=nodata, dst_nodata=nodata, resampling=resampling)
    return out
p4326 = warp(np.where(domain_r, prob_r, -1), "float32", -1, Resampling.nearest)
e4326 = warp((excluded & domain_r).astype("float32"), "float32", -1, Resampling.nearest)
g4326 = warp((land_mask & ~domain_r).astype("float32"), "float32", -1, Resampling.nearest)
rgba = plt.get_cmap("viridis")(np.clip(p4326, 0, 1)); rgba[..., 3] = np.where(p4326 >= 0, 0.75, 0)
red4326 = np.zeros((h, w, 4)); red4326[e4326 >= 0.5] = (0.85, 0.1, 0.1, 0.6)
grey4326 = np.zeros((h, w, 4)); grey4326[g4326 >= 0.5] = (0.6, 0.6, 0.6, 0.45)
plt.imsave(OUT / "_prob_overlay.png", rgba); plt.imsave(OUT / "_excl_overlay.png", red4326); plt.imsave(OUT / "_domain_overlay.png", grey4326)
west, north = t4326.c, t4326.f; east, south = west + w * t4326.a, north + h * t4326.e
bounds = [[south, west], [north, east]]
m = folium.Map(location=[41.7, 1.7], zoom_start=8, tiles="OpenStreetMap")
folium.raster_layers.ImageOverlay(str(OUT / "_prob_overlay.png"), bounds=bounds, opacity=1,
                                  name="Opportunity probability (learned weights)").add_to(m)
folium.raster_layers.ImageOverlay(str(OUT / "_excl_overlay.png"), bounds=bounds, opacity=1,
                                  name="Hard exclusions (protected / flood / urban)").add_to(m)
folium.raster_layers.ImageOverlay(str(OUT / "_domain_overlay.png"), bounds=bounds, opacity=1,
                                  name=f"Not modelled (> {DOMAIN_KM} km from a substation)").add_to(m)
folium.GeoJson(lines.to_crs(4326)[["voltage", "geometry"]],
               style_function=lambda f: {"color": "#ffffff" if f["properties"]["voltage"] == 400 else "#dddddd",
                                         "weight": 2 if f["properties"]["voltage"] == 400 else 1},
               name="Transmission lines 220/400 kV").add_to(m)
fg = folium.FeatureGroup(name="Battery projects (Generalitat)")
for _, r in bess.to_crs(4326).iterrows():
    p = r.geometry.representative_point()
    folium.CircleMarker([p.y, p.x], radius=4, color="black", fill=True, fill_color="orange", fill_opacity=0.9,
                        tooltip=f"{r.NOM} | {r.POTENCIA} MW | {r.ESTAT}").add_to(fg)
fg.add_to(m)
fg2 = folium.FeatureGroup(name="Top 20 candidate zones")
for rank, (_, r) in enumerate(top.to_crs(4326).iterrows(), 1):
    p = r.geometry.representative_point()
    folium.Marker([p.y, p.x], icon=folium.DivIcon(html=f'<div style="font:bold 12px sans-serif;color:white;'
                  f'background:#333;border-radius:10px;width:20px;height:20px;text-align:center;line-height:20px">{rank}</div>'),
                  tooltip=f"#{rank} {r.municipality_name} | p={r.probability:.2f} | nearest node {r.nearest_ree_node} "
                          f"| {r.dist_substation_km:.1f} km to substation").add_to(fg2)
fg2.add_to(m)
folium.LayerControl(collapsed=False).add_to(m)
legend = f"""<div style="position:fixed;bottom:20px;left:20px;z-index:1000;background:white;padding:10px 12px;
border:1px solid #999;font:12px sans-serif;max-width:300px">
<b>BESS opportunity heat map, variant fitted near substations (local test)</b><br>
Colour = probability that a battery developer would choose this 500 m pixel, learned from {len(bess_sites)}
existing projects by logistic regression fitted only within {DOMAIN_KM} km of a 220/400 kV substation (spatial-CV AUC {auc_cv:.2f}).<br>
<span style="background:#999;opacity:.6;padding:0 8px">&nbsp;</span> not modelled, more than {DOMAIN_KM} km from a substation<br>
<span style="background:#d91a1a;opacity:.6;padding:0 8px">&nbsp;</span> protected area, T100 flood zone or urban zoning<br>
<span style="color:orange">&#9679;</span> battery projects &nbsp; <b>1..20</b> candidate zones with no project within 10 km
</div>"""
m.get_root().html.add_child(folium.Element(legend))
m.save(OUT / "heatmap.html")
log(f"done -> {OUT}")
