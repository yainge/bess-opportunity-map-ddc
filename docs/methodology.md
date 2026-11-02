# Methodology

Status: v0.1 — methods implemented and tested on synthetic data. Parameters marked
*illustrative* must be revisited after exploratory analysis of the real data.

## 1. Analytical unit

The canonical grid node (`node_id`). Transmission (REE) and distribution (e-distribución)
nodes are kept in one table, distinguished by `operator` and `network_level`.

## 2. Grid indicators

* `generation_available_mw`, `demand_available_mw` — published available access capacity.
* `bess_headroom_proxy_mw = min(generation_available_mw, demand_available_mw)`. A battery
  both charges (demand) and discharges (generation), so the smaller of the two is a crude
  bidirectional bound. Computed only when both values exist, are ≥ 0 and — if capacity dates
  are provided — published on the same date (`grid.require_same_capacity_date`). Otherwise
  null with a `headroom_note`. **Proxy**, not a connection offer.

## 3. Congestion (ERNI)

* Records are standardised to MWh with a period (month).
* **Matching** to grid nodes (in order): reviewed crosswalk (reliability *high*) → identical
  source id (*high*) → unique normalised name (*medium*; upper-case, accents removed,
  punctuation removed, tokens such as `SE`, `SET`, `SUBESTACIO` stripped). Several candidates
  → *ambiguous*, not merged. No candidate → *unmatched*.
* `erni_12m_gwh` = sum of matched ERNI in the 12 months ending at the reference month
  (`congestion.reference_period_end`, default: latest month). Null if no values (not 0).
  `erni_months_observed` records coverage; < 12 months is reported.
* Several source nodes matched to one grid node are summed (reported as *many_to_one*).

## 4. Renewables

* `status_category` ∈ {operating, pipeline, unknown} via `options.status_map`.
* `renewable_mw_<R>km` / `renewable_pipeline_mw_<R>km`: sum of `capacity_mw` of installations
  within *R* km (default 10) of the node (planar distance, EPSG:25831). Records with invalid
  coordinates or duplicate source ids are excluded. Catchments overlap: one installation can
  count for several nodes. **Context indicator**, not electrical connectivity.

## 5. Demand

* Source resolution kept (municipality × year × sector). Summary: latest year per
  municipality, `total_mwh`, `industrial_mwh` (sector codes in `options.industrial_sector_codes`).
* `nearby_demand_mwh_<R>km = Σ_m total_mwh_m · area(buffer_R ∩ m) / area(m)` —
  **area-weighted** allocation assuming demand is spread uniformly over each municipality.
  Lower bound where sectors are suppressed or data is missing. **Proxy** for local demand,
  not nodal load.

## 6. Land feasibility and constraints (GIS)

For each node and buffer radius *r* ∈ {5, 10, 20} km (`spatial.buffers_km`):

* Buffers: Euclidean, EPSG:25831, 64 segments per quarter circle (area error < 0.01 %).
* Layers are dissolved before measuring, so overlapping polygons are not double counted.
* `suitable_land_ha_<r>km = area(buffer ∩ (suitable land cover − ∪ hard constraints)) / 10⁴`.
  Suitable classes: `land_cover.suitable_classes`. Hard constraints (v0.1): protected areas,
  flood zones, excluded zoning classes. If a hard layer is missing, a warning states that
  suitable land is overestimated.
* `<constraint>_share_<r>km` = constraint area in buffer / buffer area (hard and soft).
* `protected_area_conflict` = a protected area within `protected_conflict_distance_m`
  (1000 m) of the node. `flood_risk_at_node` = node point inside a flood zone.
* `distance_to_major_road_km` = planar distance to the nearest road of a major class.
* Slope / terrain: deferred until the DTM is available (requires Rasterio).

## 7. Integration milestones

| Milestone | Content |
|---|---|
| M0 | grid only (partial) |
| M1 | grid coordinates + access capacity + ERNI |
| M2 | M1 + renewables + demand |
| M3 | M2 + land feasibility |

Recorded in `quality_integrated_nodes.*` (`metrics.milestone`).

## 8. Scoring (illustrative)

For scenario *s* with weights *w_i* over indicators *i*:

* Normalisation per indicator to [0, 1], 1 = favourable: min-max (constant column → 0.5)
  or percentile rank; `lower_better` indicators are inverted.
* Missing-value policy per indicator: `reweight` (drop, renormalise remaining weights),
  `worst` (score 0), `exclude` (node unranked).
* `score = Σ w_i n_i / Σ_{i available} w_i`; `weight_coverage = Σ_{i available} w_i / Σ w_i`.
* Nodes are unranked if `weight_coverage < min_weight_coverage` (0.5) or a hard screening
  flag is true (`exclude_if_true`, e.g. `protected_area_conflict`).
* Ranks are deterministic: ties broken by `node_id`.
* Scenarios: *renewable absorption*, *connection readiness*, *load & grid support*
  (weights in `config/scoring.yaml` — **illustrative, not validated**).

Opportunity (score), data quality (completeness, match reliability, …) and ranking stability
(sensitivity) are kept conceptually separate; no combined confidence score is computed.

## 9. Sensitivity

`bess_catalonia.scoring.sensitivity` (run with `uv run python scripts/sensitivity.py --mode real`)
uses the pure `score_scenario` function for two checks per scenario:

* **Weight perturbation:** each weight multiplied by an independent factor in [0.8, 1.2],
  500 draws; per node the median rank, 5th to 95th percentile rank and share of draws in the
  top 10 (`results/real/tables/sensitivity_rank_stability.csv`).
* **Leave one indicator out:** top-10 overlap and Jaccard index with the base ranking when each
  indicator is dropped (`sensitivity_leave_one_out.csv`).

First real results (2026-11-02): top-10 lists are stable under ±20% weight changes, but removing
a single indicator can change them a lot (connection readiness keeps 5 of 10 without the headroom
proxy; load & grid support keeps 3 of 10 without nearby demand). Alternative normalisation is not
yet tested.
