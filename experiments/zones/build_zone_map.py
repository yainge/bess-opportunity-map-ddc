#!/usr/bin/env python
"""Option 3: storage access status by REE's own capacity zones instead of geographic clusters.

REE's per-node access-capacity files assign each transmission node either to a shared-capacity
zone ("Zona con capacidad compartida", e.g. E205_SEPE) or to node-level capacity, and name the
criterion that binds. Those zones are the electrical regions that matter for a connection
request. This script builds one region per zone (Thiessen polygons of the substation sites,
dissolved by zone, clipped to Catalonia), attaches the current storage access status of its
nodes, and draws the real line connections between substations.

Sources
  * zones, static zone margins, dynamic margins, limiting criterion, demand-side reason:
    Polo's workbook, sheet "Nudos" = REE demand access-capacity file, version of ~1 Oct 2026
    (zones are structural and do not change month to month);
  * coordinates, under-construction flags, Nov 2026 capacities (injection and charging mode),
    granted/pending MW, generation-side reason, tender flag:
    data/processed/grid_topology/ree_nodes_matched.csv (Fernando, REE files of 3 Nov 2026);
  * line connections: data/processed/grid_topology/catalonia_grid.geojson (Fernando, OSM).

Run from the repo root:
    experiments/heatmap/.venv/bin/python experiments/zones/build_zone_map.py
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import folium
import geopandas as gpd
import matplotlib
import numpy as np
import openpyxl
import pandas as pd
from matplotlib import pyplot as plt
from shapely import voronoi_polygons
from shapely.geometry import MultiPoint

matplotlib.use("Agg")
ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
NODES = ROOT / "data" / "processed" / "grid_topology" / "ree_nodes_matched.csv"
GEOJSON = ROOT / "data" / "processed" / "grid_topology" / "catalonia_grid.geojson"
HERE = Path(__file__).resolve().parent
OUT = HERE / "output"
OUT.mkdir(exist_ok=True, parents=True)
CRS = "EPSG:25831"
T0 = time.time()
log = lambda m: print(f"[{time.time() - T0:5.0f}s] {m}", flush=True)

# ------------------------------------------------------------------ REE demand file (zones, criteria)
wb = openpyxl.load_workbook(RAW / "Dataset_SusbtationNodes.xlsx", read_only=True, data_only=True)
rows = [r for r in wb["Nudos"].iter_rows(min_row=4, values_only=True) if r[2] == "Cataluña"]
COLS = {0: "ree_node", 1: "ree_code", 14: "zone_static_demand", 17: "static_storage_nodal_cap_mw", 18: "zone",
        19: "static_storage_margin_mw", 20: "dyn1_margin_mw", 21: "dyn2_margin_mw", 47: "limiting_criterion_storage_mpe",
        54: "demand_side_reason", 58: "available_storage_charging_oct_mw", 60: "tender_demand_file"}
dem = pd.DataFrame([{v: r[k] for k, v in COLS.items()} for r in rows])
dem["ree_node"] = dem.ree_node.str.strip().str.upper()
dem["zone"] = dem.zone.astype(str).replace({"None": "N/A", "nan": "N/A"})
for c in ["static_storage_nodal_cap_mw", "static_storage_margin_mw", "dyn1_margin_mw", "dyn2_margin_mw", "available_storage_charging_oct_mw"]:
    dem[c] = pd.to_numeric(dem[c], errors="coerce")
log(f"REE demand file: {len(dem)} Catalan nodes, {dem.zone.ne('N/A').sum()} in shared zones ({dem.loc[dem.zone.ne('N/A'), 'zone'].nunique()} zone labels)")

# ------------------------------------------------------------------ Fernando's node table (Nov 2026)
n = pd.read_csv(NODES)
n["ree_node"] = n.ree_node.str.strip().str.upper()
f0 = lambda c: pd.to_numeric(n[c], errors="coerce").fillna(0)
n["room_injection_mw"] = f0("storage_available_MPE_RdT_MW (generation mode)")
n["room_charging_mw"] = f0("storage_available_MPE_RdT_MW (demand mode)")
n["gen_granted_mw"] = f0("gen_granted_MW")
n["storage_granted_mw"] = f0("storage_granted_MW_genfile")
n["storage_pending_mw"] = f0("storage_pending_MW_genfile")
n["tender"] = n["tender_node (nudo de concurso)"].astype(str).str.upper().eq("SI")
n["under_construction"] = n.under_construction.astype(bool)
nodes = n[["ree_node", "kv", "lat", "lon", "under_construction", "tender", "room_injection_mw", "room_charging_mw", "gen_granted_mw",
           "storage_granted_mw", "storage_pending_mw", "gen_unavailable_reason", "demand_unavailable_reason"]].merge(dem, on="ree_node", how="left")
nodes = gpd.GeoDataFrame(nodes, geometry=gpd.points_from_xy(nodes.lon, nodes.lat), crs="EPSG:4326").to_crs(CRS)
nodes["zone"] = nodes.zone.fillna("N/A")


def status_injection(r):
    if r.room_injection_mw > 0:
        return "room for storage (injection)"
    s = str(r.gen_unavailable_reason)
    if "Concurso" in s and "Margen zonal" not in s:
        return "reserved for tender (concurso)"
    if "Margen zonal" in s:
        return "zonal margin reserved for tender"
    if "Sin posibilidad" in s:
        return "no connection possible"
    return "no capacity, reason not stated"


nodes["status_injection"] = nodes.apply(status_injection, axis=1)
nodes["status_charging"] = np.where(nodes.room_charging_mw > 0, "room (charging)",
                                    np.where(nodes.demand_side_reason.astype(str).str.contains("no acordado"), "reference value not agreed",
                                             "no room / no figure"))
print(nodes.status_injection.value_counts().to_string()); print(nodes.status_charging.value_counts().to_string())

# ------------------------------------------------------------------ sites -> zone regions
nodes["site_key"] = nodes.geometry.x.round(0).astype(str) + "_" + nodes.geometry.y.round(0).astype(str)
site = nodes.groupby("site_key").agg(
    zones=("zone", lambda s: "; ".join(sorted(set(z for z in s if z != "N/A"))) or "own node"),
    nodes=("ree_node", lambda s: "; ".join(s)), x=("geometry", lambda g: g.iloc[0].x), y=("geometry", lambda g: g.iloc[0].y))
site = gpd.GeoDataFrame(site, geometry=gpd.points_from_xy(site.x, site.y), crs=CRS)
site["region_key"] = np.where(site.zones == "own node", "node: " + site.nodes, site.zones)
cat = gpd.read_file(RAW / "grid" / "osm_pypsa_transmission_catalonia_20261105.gpkg", layer="catalonia_nuts2").to_crs(CRS)
cat_geom = cat.geometry.union_all()
vor = voronoi_polygons(MultiPoint(list(site.geometry)), extend_to=cat_geom.buffer(50_000))
cells = gpd.GeoDataFrame(geometry=list(vor.geoms), crs=CRS)
cells = gpd.sjoin(cells, site[["region_key", "geometry"]], predicate="contains")[["region_key", "geometry"]]
cells["geometry"] = cells.geometry.intersection(cat_geom)
regions = cells.dissolve(by="region_key").reset_index()
log(f"{len(site)} substation sites -> {len(regions)} regions ({(regions.region_key.str.startswith('node:')).sum()} single-node, "
    f"{(~regions.region_key.str.startswith('node:')).sum()} shared zones)")

# ------------------------------------------------------------------ region table
nodes["region_key"] = nodes.site_key.map(site.region_key)
ORDER = ["room for storage (injection)", "reserved for tender (concurso)", "zonal margin reserved for tender", "no connection possible", "no capacity, reason not stated"]
g = nodes.groupby("region_key")
tab = pd.DataFrame({
    "nodes": g.ree_node.apply(lambda s: "; ".join(s)), "n_nodes": g.size(),
    "kv": g.kv.apply(lambda s: "/".join(str(int(v)) for v in sorted(set(s), reverse=True))),
    "room_injection_mw": g.room_injection_mw.max().round(0), "room_charging_mw": g.room_charging_mw.max().round(0),
    "static_zone_margin_mw": g.static_storage_margin_mw.max(), "dyn1_margin_mw": g.dyn1_margin_mw.max(),
    "limiting_criterion": g.limiting_criterion_storage_mpe.apply(lambda s: s.dropna().mode().iloc[0] if s.notna().any() else ""),
    "gen_granted_mw": g.gen_granted_mw.sum().round(0), "storage_granted_mw": g.storage_granted_mw.sum().round(0),
    "storage_pending_mw": g.storage_pending_mw.sum().round(0), "tender_nodes": g.tender.sum(),
    "under_construction": g.under_construction.sum(),
    "status": g.status_injection.apply(lambda s: sorted(s, key=ORDER.index)[0]),
    "status_charging": g.status_charging.apply(lambda s: "room (charging)" if (s == "room (charging)").any() else s.mode().iloc[0]),
    "gen_reason": g.gen_unavailable_reason.apply(lambda s: s.dropna().mode().iloc[0] if s.notna().any() else ""),
})
regions = regions.merge(tab, left_on="region_key", right_index=True, how="left")
regions["area_km2"] = (regions.geometry.area / 1e6).round(0)

# battery projects per region
b = gpd.read_file(RAW / "storage" / "ENERGIA_BATERIES_STANDALONE_20261105.gpkg").to_crs(CRS)
b = b[b.ESTAT != "No autoritzat"]
bp = gpd.GeoDataFrame(b[["POTENCIA"]], geometry=b.representative_point(), crs=CRS)
jb = gpd.sjoin(bp, regions[["region_key", "geometry"]], predicate="within")
pr = jb.groupby("region_key").agg(project_rows=("POTENCIA", "size"), project_mw=("POTENCIA", "sum"))
regions = regions.merge(pr, left_on="region_key", right_index=True, how="left").fillna({"project_rows": 0, "project_mw": 0})
regions.drop(columns="geometry").sort_values(["status", "storage_pending_mw"], ascending=[True, False]).to_csv(OUT / "zone_table.csv", index=False)
nodes.drop(columns="geometry").to_csv(OUT / "node_table.csv", index=False)
print("\nregions by status:\n", regions.groupby("status").agg(regions=("region_key", "size"), nodes=("n_nodes", "sum"),
                                                              area_km2=("area_km2", "sum"), project_rows=("project_rows", "sum"),
                                                              project_mw=("project_mw", "sum")).round(0).to_string())
print("\nregions with room for storage (injection):\n",
      regions[regions.room_injection_mw > 0][["region_key", "nodes", "room_injection_mw", "storage_pending_mw", "project_rows"]].to_string(index=False))
print("\nshared zones:\n", regions[~regions.region_key.str.startswith("node:")][["region_key", "n_nodes", "static_zone_margin_mw", "dyn1_margin_mw",
      "limiting_criterion", "status", "storage_pending_mw", "project_rows"]].to_string(index=False))

# ------------------------------------------------------------------ outputs
regions.to_file(OUT / "zones.gpkg", layer="regions", driver="GPKG")
nodes.drop(columns=["site_key"]).to_file(OUT / "zones.gpkg", layer="nodes", driver="GPKG")
COLOR = {"room for storage (injection)": "#1a9850", "reserved for tender (concurso)": "#fdae61", "zonal margin reserved for tender": "#fee08b",
         "no connection possible": "#d73027", "no capacity, reason not stated": "#bdbdbd"}
conn = gpd.read_file(GEOJSON)
conn = conn[conn.kind == "connection"].to_crs(CRS)
fig, ax = plt.subplots(figsize=(11, 10))
regions.plot(ax=ax, color=regions.status.map(COLOR), edgecolor="white", linewidth=0.8, alpha=0.9)
shared = regions[~regions.region_key.str.startswith("node:")]
shared.boundary.plot(ax=ax, color="black", linewidth=1.4)
conn.plot(ax=ax, color="#444", linewidth=np.where(conn.voltage_kv >= 400, 1.4, 0.7), alpha=0.8)
nodes[~nodes.under_construction].plot(ax=ax, color="black", markersize=10, marker="s", zorder=5)
nodes[nodes.under_construction].plot(ax=ax, facecolor="none", edgecolor="black", markersize=40, marker="s", linewidth=1.2, zorder=5)
nodes[nodes.tender].plot(ax=ax, color="#ffd400", edgecolor="black", markersize=90, marker="^", zorder=6)
bp.plot(ax=ax, color="white", edgecolor="black", markersize=14, zorder=6)
for _, r in shared.iterrows():
    c = r.geometry.representative_point()
    ax.annotate(r.region_key.replace("_SEPE", "").replace("_Bin", "b"), (c.x, c.y), fontsize=6.5, ha="center", color="black",
                bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.7))
handles = [plt.Rectangle((0, 0), 1, 1, color=v) for v in COLOR.values()]
labels = [f"{k} ({(regions.status == k).sum()} regions, {int(regions.loc[regions.status == k, 'n_nodes'].sum())} nodes)" for k in COLOR]
handles += [plt.Line2D([], [], color="black", lw=1.4), plt.Line2D([], [], color="#444", lw=1),
            plt.Line2D([], [], color="k", marker="s", ms=4, ls=""), plt.Line2D([], [], color="none", markeredgecolor="k", marker="s", ms=7, ls=""),
            plt.Line2D([], [], color="#ffd400", markeredgecolor="k", marker="^", ms=9, ls=""),
            plt.Line2D([], [], color="w", markeredgecolor="k", marker="o", ms=6, ls="")]
labels += ["REE shared-capacity zone (label = zone code)", "220/400 kV line connection (OSM)", "REE node", "node under construction",
           "tender node", "battery project (Generalitat register)"]
ax.legend(handles, labels, loc="upper left", bbox_to_anchor=(0, -0.01), fontsize=8, frameon=False,
          title="Storage access status by REE capacity zone, injection mode, REE files of 3 Nov 2026")
ax.set_title("Where can a battery get access? REE zones and node status, Catalonia", fontsize=11)
ax.set_axis_off()
fig.savefig(OUT / "zone_map.png", dpi=160, bbox_inches="tight"); plt.close(fig)

# web map
m = folium.Map(location=[41.7, 1.7], zoom_start=8, tiles="OpenStreetMap")
r4 = regions.to_crs(4326)
folium.GeoJson(r4, name="REE capacity regions",
               style_function=lambda f: {"fillColor": COLOR[f["properties"]["status"]], "color": "black" if not f["properties"]["region_key"].startswith("node:") else "white",
                                         "weight": 1.5 if not f["properties"]["region_key"].startswith("node:") else 0.6, "fillOpacity": 0.55},
               tooltip=folium.GeoJsonTooltip(fields=["region_key", "nodes", "kv", "status", "room_injection_mw", "room_charging_mw", "status_charging",
                                                     "limiting_criterion", "static_zone_margin_mw", "dyn1_margin_mw", "gen_granted_mw",
                                                     "storage_granted_mw", "storage_pending_mw", "tender_nodes", "project_rows", "project_mw", "gen_reason"],
                                             aliases=["Region", "Nodes", "kV", "Status (injection)", "Room injection MW", "Room charging MW",
                                                      "Status (charging)", "Limiting criterion (storage)", "Static zone margin MW", "Dynamic margin MW",
                                                      "Generation granted MW", "Storage granted MW", "Storage pending MW", "Tender nodes",
                                                      "Battery filings here", "Battery MW here", "REE reason (generation file)"])).add_to(m)
folium.GeoJson(conn.to_crs(4326), name="Line connections (OSM)",
               style_function=lambda f: {"color": "#333", "weight": 2 if f["properties"]["voltage_kv"] >= 400 else 1, "opacity": 0.7},
               tooltip=folium.GeoJsonTooltip(fields=["name_a", "name_b", "voltage_kv", "length_km", "confidence"])).add_to(m)
fn = folium.FeatureGroup(name="REE nodes")
for _, r in nodes.to_crs(4326).iterrows():
    tip = (f"<b>{r.ree_node}</b> | zone {r.zone}<br>{r.status_injection} | room injection {r.room_injection_mw:.0f} MW, charging {r.room_charging_mw:.0f} MW"
           f"<br>generation granted {r.gen_granted_mw:.0f} MW | storage granted {r.storage_granted_mw:.0f} MW, pending {r.storage_pending_mw:.0f} MW"
           f"<br>reason (generation file): {r.gen_unavailable_reason}<br>reason (demand file): {r.demand_side_reason}"
           f"{' | TENDER NODE' if r.tender else ''}{' | UNDER CONSTRUCTION' if r.under_construction else ''}")
    folium.RegularPolygonMarker([r.geometry.y, r.geometry.x], number_of_sides=4, radius=7 if r.under_construction else 4, color="black",
                                fill=not r.under_construction, fill_color="black", fill_opacity=1, weight=1.5, tooltip=tip).add_to(fn)
    if r.tender:
        folium.RegularPolygonMarker([r.geometry.y, r.geometry.x], number_of_sides=3, radius=9, color="black", fill=True, fill_color="#ffd400",
                                    fill_opacity=1, tooltip=tip).add_to(fn)
fn.add_to(m)
fb = folium.FeatureGroup(name="Battery projects")
for _, s in bp.to_crs(4326).iterrows():
    folium.CircleMarker([s.geometry.y, s.geometry.x], radius=3, color="black", weight=0.8, fill=True, fill_color="white", fill_opacity=1,
                        tooltip=f"{s.POTENCIA:.1f} MW").add_to(fb)
fb.add_to(m)
folium.LayerControl(collapsed=False).add_to(m)
items = "".join(f'<div><span style="background:{v};padding:0 10px;margin-right:6px">&nbsp;</span>{k}</div>' for k, v in COLOR.items())
m.get_root().html.add_child(folium.Element(
    f'<div style="position:fixed;bottom:20px;left:20px;z-index:1000;background:white;padding:10px 12px;border:1px solid #999;'
    f'font:12px sans-serif;max-width:380px"><b>Storage access by REE capacity zone (local trial)</b><br>Regions = REE shared-capacity zones '
    f'(black outline) or single nodes (white outline); colour = best storage access status of the nodes inside, injection mode, '
    f'REE files of 3 Nov 2026. Hover for figures.<br>{items}</div>'))
m.save(OUT / "zone_map.html")
json.dump({"n_nodes": int(len(nodes)), "n_regions": int(len(regions)), "shared_zones": int((~regions.region_key.str.startswith("node:")).sum()),
           "status_counts": nodes.status_injection.value_counts().to_dict(), "charging_status_counts": nodes.status_charging.value_counts().to_dict()},
          open(OUT / "metrics.json", "w"), indent=2)
log(f"done -> {OUT}")
