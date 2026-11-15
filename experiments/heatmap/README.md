# Local test: BESS opportunity heat map with learned weights

Status: experiment, not part of the pipeline. Nothing here is tracked by git yet
(`experiments/` is untracked; raw inputs are gitignored). If the team adopts it, the plan is a
`heatmap` stage next to Yuki's node-level `ml` stage.

## Idea

Every 500 m pixel of Catalonia gets a probability that a battery developer would choose it.
The probability comes from a logistic regression fitted on the 76 stand-alone battery sites in
the Generalitat layer (`data/raw/storage/`, any status except refused) against all other land
pixels (presence-background model). The fitted coefficients are the "learned weights"; no
hand-chosen weights are used. Hard exclusions (protected areas, 100-year flood zones, urban
residential/core zoning) are drawn as a red overlay, not removed from the fit.

## Run

```
experiments/heatmap/.venv/bin/python experiments/heatmap/build_heatmap.py
```

The environment was created with `uv venv` plus geopandas, rasterio, scikit-learn, folium
(rasterio is not a project dependency yet). Inputs: `data/raw/gis/*.gpkg` (Yuki's download
script), `data/raw/grid/osm_pypsa_transmission_*.gpkg`, `Dataset_SusbtationNodes.xlsx`,
`data/raw/renewables/*.csv`, `data/raw/demand/*.csv`, `data/raw/storage/*.gpkg`. Runtime about
30 s.

## Features per pixel (centre point)

| Feature | Source | Transform |
|---|---|---|
| dist_substation_km | nearest real 220/400 kV substation, OpenStreetMap via PyPSA-Eur | capped 50 km |
| dist_substation_400kv_km | nearest 400 kV substation | capped 50 km |
| access_capacity_nearest_node_mw | "Node Access Capacity" of nearest REE node within 20 km (Polo's sheet) | log1p |
| renewable_operating_mw_10km | operating solar + wind MW within 10 km (Isabella's files) | log1p |
| renewable_pipeline_mw_10km | authorised + in-permitting MW within 10 km | log1p |
| demand_mwh_10km | 2023 municipal consumption spread over municipal area, summed within 10 km (Fernando's file) | log1p |
| dist_distribution_substation_km | nearest e-distribución substation (file is EPSG:25830) | capped 50 km |
| dist_major_road_km | nearest motorway or primary road | capped 50 km |
| suitable_land_share_1km | share of suitable land-cover classes in a 1.5 km window (MCSC 2024) | none |

Computed but not used in the model (kept in the output grid): distribution_load_mw_10km
(r = 0.77 with demand) and dist_line_km (r = 0.55 with dist_substation). Including them flipped
coefficient signs without improving validation. Not used anywhere: REE storage requested/granted
(too close to the label), "Not occupied margin" (already net of granted storage), curtailment
(no data yet).

## Validation

Spatial block cross-validation (25 km blocks, 5 folds, GroupKFold). See `output/metrics.json`.
Out-of-fold AUC 0.89. A single feature, distance to the nearest substation, already reaches 0.88
to 0.89, so the extra features add interpretation more than accuracy. A random forest on the
same features gives 0.88 (cross-check, not used).

## Outputs (`output/`)

- `heatmap.html`: interactive map (probability overlay, red exclusions, lines, battery projects,
  numbered top-20 candidate zones). `heatmap.png`: static version.
- `heatmap_prob_500m.tif`, `exclusion_mask_500m.tif`: GeoTIFFs, EPSG:25831.
- `heatmap_grid_500m.gpkg`: all 128,436 land pixels with every feature, probability, label,
  exclusion shares and nearest REE node (opens in QGIS).
- `coefficients.csv`: standardised coefficients with bootstrap 95% intervals and odds ratios.
- `candidate_zones_top20.csv`: best non-excluded pixels with no battery project within 10 km,
  thinned so zones are at least 10 km apart.

## Caveats to keep in the report

- 76 sites, 72 positive pixels: a small sample. Confidence intervals are wide; two features
  (access capacity, distance to substation) are not significant once the others are in.
- The label is "a developer applied here", which mixes real opportunity with developer habits
  (one company accounts for a third of the applications) and with the current permitting rules
  (5 MW units avoid full environmental assessment, so sites cluster in industrial zones).
- The 10 km disc sums create visible circles around isolated plants and substations.
- REE node coordinates are approximate (two decimals, some planned nodes); access capacity is
  therefore attached with about 1 to 4 km of positional error.
- Curtailment/ERNI is absent, so the map says nothing about congestion value.

## Variant 2: fitted only near substations (`build_heatmap_near_substation.py`)

Motivation: in the first map, distance to the nearest substation explains almost everything
(AUC 0.89 with that one feature). To see what the other features add, the second script fits
and applies the same model only to land within 10 km of a real 220/400 kV substation
(44,468 pixels, 67 positives; 5 positive pixels farther away are dropped). Land outside the
domain is shown grey as "not modelled". Outputs in `output_near_substation/`.

Result: spatial-CV AUC 0.85 versus 0.81 for distance alone inside the domain, so the other
features now carry real signal. Significant weights: demand within 10 km (odds x3.3 per SD),
operating renewables (x2.0), suitable land (x2.0), closeness to a 400 kV substation (x0.51
per SD of distance) and to any substation (x0.56). Not significant: roads, pipeline renewables,
access capacity, distance to distribution substations.

The first map (`output/`) is kept unchanged as a record.
