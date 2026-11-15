# Local test: typology of BESS locations by system role

Status: experiment, untracked by git. Depends on the pixel grid produced by
`experiments/heatmap/build_heatmap.py` (`experiments/heatmap/output/heatmap_grid_500m.gpkg`).

Run:
```
experiments/heatmap/.venv/bin/python experiments/typology/build_typology.py
```

## Question

Instead of "how attractive is this pixel", ask "what would a battery here do for the system".
Each 500 m pixel is clustered on system-role features only: distance to 220/400 kV substations,
access capacity, occupation share and room for storage at the nearest REE node, operating and
pipeline renewables within 10 km, municipal demand and distribution load within 10 km, distance
to the nearest distribution substation. Land feasibility (suitable land, roads, exclusions) is
deliberately left out: it says whether a battery can be built, not what it would do.

## Method

k-means on standardised features (log for MW and MWh, distances capped at 50 km). k chosen from
3 to 8 by silhouette score and bootstrap stability (adjusted Rand index between fits on random
halves). k = 6: silhouette 0.23, stability 0.91. Silhouettes are modest for every k, which is
normal for continuous geographic gradients; the stability score is the stronger argument.
Cluster names in `cluster_names.json` were written after reading the profiles
(`output/cluster_profiles_median.csv`, `output/cluster_centroids_zscore.csv`).

## Result (2026-11-09)

| Type | Share of land | Existing battery sites (of 76) |
|---|---|---|
| Load centre: high demand and distribution load, close to substations | 30% | 72 |
| Renewable integration zone: 76 MW operating, 121 MW pipeline within 10 km, 220 kV nearby | 16% | 3 |
| Future 400 kV nodes (Isona, Els Aubals, Masdenverge, Sallente, Santa Llogaia, Vic 400, Calders): about 1 GW access, 680 MW room for storage, little load or generation, most not yet built | 16% | 0 |
| Saturated node surroundings: nearest node with the highest occupation and no room for storage | 9% | 1 |
| Remote, weak grid: nearest REE node has no access capacity | 16% | 0 |
| Mountain / protected, far from 400 kV | 13% | 0 |

95% of the battery projects sit in the load-centre type, which covers 30% of the land. The two
types where storage would address a generation-side problem, renewable integration zones and
future 400 kV nodes, hold 3 projects between them on 32% of the land.

## Outputs (`output/`)

`typology.html`, `typology.png`, `typology_500m.tif`, `typology_grid_500m.gpkg` (pixels with
features, cluster id and type), `k_selection.csv`, `cluster_profiles_median.csv`,
`cluster_centroids_zscore.csv`, `bess_projects_by_cluster.csv`, `metrics.json`.

## Caveats

- Cluster names are an interpretation of the profiles; the report must show the profiles.
- "Renewable integration" is defined by renewable concentration and node capacity, not by
  measured curtailment, which is near zero for Catalan nodes in REE's monthly ERNI reports.
- Node attributes come from the REE sheet with approximate coordinates; "occupation share" uses
  "Not occupied margin", which is already net of granted storage.
- Median occupation share is low in most clusters (most Catalan nodes are not saturated in this
  sheet), which does not match the Generalitat's October 2025 statement that most nodes lack
  capacity. Resolved on 2026-11-15, see v2 below: the sheet's "AvailableStorage" column is the
  margin under one REE criterion only, not the capacity available for requests.

## v2 trial (2026-11-15): node data from Fernando's matched table

Script `build_typology_v2.py`, outputs in `output_v2_nodes_nov2026/`. `output/` is kept as the
record of v1.

Node source: `data/processed/grid_topology/ree_nodes_matched.csv` (REE access-capacity files of
3 Nov 2026, generation and demand; coordinates matched to OpenStreetMap, 40 hand-reviewed; six
nodes flagged under construction). Polo's sheet (`Dataset_SusbtationNodes.xlsx`) was traced to
the REE demand file of about 1 Oct 2026; its "AvailableStorage CPE MPE" is the unoccupied margin
under the static storage criterion alone, and its "Not occupied margin" is a formula
(nodal capacity − "requested" − "granted"), not an REE figure. The capacity REE actually offers
for storage requests (minimum over short-circuit, static and dynamic criteria) is positive at
10 of 117 Catalan nodes, so it cannot separate pixels and is no longer a clustering feature.

Changes versus v1:
- Nearest REE node per pixel recomputed from the new coordinates (40% of pixels change node;
  battery pixels now sit a median 1.2 km from their node instead of 3.0 km).
- The three old node variables are replaced by two node-activity variables, attached within
  20 km: generation MW granted at the node, and storage MW granted + pending (injection mode).
- Room for storage, tender nodes (Puigpelat 220, Vandellòs 400, Zona Franca 220) and nodes under
  construction are drawn as symbols instead of being features.

Result: k = 4 (silhouette 0.23, stability 0.99; k = 5 is close at 0.22 / 0.97).

| Type | Share of land | Existing battery sites (of 76) |
|---|---|---|
| Load centre: high demand and distribution load, storage queue at nodes | 33% | 71 |
| Renewable integration zone: operating and pipeline renewables, active nodes | 16% | 4 |
| Mountain / Pyrenees: weak 220 kV nodes, little load or generation | 24% | 0 |
| Far from the transmission grid: nearest node distant, planned or under construction | 26% | 1 |

The headline survives: 93% of battery projects sit in the load-centre type on a third of the land.
The v1 types "saturated node surroundings" and "future 400 kV nodes with room" are gone; they
rested on Polo's columns. Only 7 of the 76 battery sites have a nearest node with room for
storage, which supports the reading that developers apply where load is, and queue for access.

Open checks on the node table: Mas Figueres 220 is name-matched to the Figueres receiving
station (Santa Llogaia 400 is 3 km away) and may be a false match; Vilanova 220 and Mata 220 are
placed inside Barcelona with no OpenStreetMap transmission substation within 5 km (indoor
stations are plausible). 43 nodes are absent from the 2023 occupancy file, so 2023 occupancy is
not used.
