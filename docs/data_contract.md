# Data contract

The canonical columns every stage reads and writes. Source of truth in code: `src/bess_catalonia/schemas.py` (a test fails if this document and the code diverge). Changes to this contract need a reviewed pull request and a CHANGELOG entry.

## Conventions

| Standard | Value |
|---|---|
| Analytical CRS | EPSG:25831 (ETRS89 / UTM 31N) — all buffers, areas, distances |
| Geographic coordinates | EPSG:4326, as `lon` / `lat` columns |
| Power | MW (`*_mw`) |
| Energy | MWh (`*_mwh`) or GWh (`*_gwh`) — unit always in the name |
| Distance | metres internally; km in outputs (`*_km`) |
| Area | m² internally; hectares in outputs (`*_ha_*`) |
| Column names | `snake_case` |
| Missing values | null — never 0 |
| Canonical identifier | `node_id` = `<operator>-<source_node_id>`, upper-case, non-alphanumerics → `_` |
| Raw files | immutable (`data/raw/`), read only |
| Processed files | reproducible from raw + config + code |

## How a source becomes canonical

1. **Read** with the `format` / `read_options` in `config/datasets.yaml`.
2. **Map** source column names onto canonical names (`columns: {source: canonical}`). An empty mapping keeps names as they are.
3. **Check** required columns (missing → error, the stage stops).
4. **Coerce** types; unparseable values become null and are reported. `number_format` handles e.g. Catalan `2.555.460`.
5. **Convert units** declared in `units:` (e.g. `capacity_mw: kW`) to the canonical unit implied by the column suffix.
6. **Validate** domain rules and write the quality report.

`*_input` tables list what the mapped source must provide; the others are stage outputs.

## Grid (Polo)

Output `data/processed/grid/grid_nodes.{gpkg,csv}`. One row per canonical node; exact duplicate rows are dropped (warning), conflicting duplicates of a `node_id` are an error. Nodes without coordinates or outside the Catalonia bounding box are dropped and reported.

### `grid_input`

| column | type | required | unit | description |
|---|---|---|---|---|
| `source_node_id` | string | yes |  | Identifier used by the source publication |
| `node_name` | string | yes |  | Node / substation name as published |
| `x` | float | yes | source CRS | X / longitude in the dataset's source_crs |
| `y` | float | yes | source CRS | Y / latitude in the dataset's source_crs |
| `operator` | string |  |  | REE, EDIS (e-distribución), ... |
| `network_level` | string |  |  | transmission | distribution |
| `voltage_kv` | float |  | kV | Nominal voltage |
| `generation_available_mw` | float |  | MW | Available generation access capacity |
| `demand_available_mw` | float |  | MW | Available demand access capacity |
| `generation_capacity_date` | string |  |  | Publication date of gen. capacity |
| `demand_capacity_date` | string |  |  | Publication date of demand capacity |

### `grid_nodes`

| column | type | required | unit | description |
|---|---|---|---|---|
| `node_id` | string | yes |  | Canonical identifier: <operator>-<source_node_id> |
| `source_node_id` | string | yes |  | Original source identifier (preserved) |
| `node_name` | string | yes |  |  |
| `operator` | string |  |  |  |
| `network_level` | string |  |  |  |
| `voltage_kv` | float |  | kV |  |
| `generation_available_mw` | float |  | MW |  |
| `demand_available_mw` | float |  | MW |  |
| `bess_headroom_proxy_mw` | float |  | MW | min(generation, demand) available capacity - indicative screening proxy only |
| `headroom_note` | string |  |  | Why the proxy is null, if it is |
| `lon` | float | yes | deg | EPSG:4326 longitude |
| `lat` | float | yes | deg | EPSG:4326 latitude |
| `geometry` | geometry | yes |  | Point, EPSG:25831 |

## Demand (Fernando)

Outputs `demand_municipal_long.{parquet,csv}` (source resolution: municipality × year × sector, unchanged) and `demand_municipal_summary.csv` (latest year per municipality). Codes are zero-padded to 5 digits. Suppressed values stay null and set `total_is_lower_bound`.

### `demand_input`

| column | type | required | unit | description |
|---|---|---|---|---|
| `municipality_code` | string | yes |  | INE/Idescat 5-digit municipality code |
| `year` | int | yes |  |  |
| `consumption_mwh` | float | yes | MWh | Annual electricity consumption |
| `municipality_name` | string |  |  |  |
| `sector_code` | string |  |  |  |
| `sector_name` | string |  |  |  |
| `province` | string |  |  |  |
| `comarca` | string |  |  |  |
| `source_note` | string |  |  | Source remarks (e.g. statistical secrecy) |

### `demand_municipal_summary`

| column | type | required | unit | description |
|---|---|---|---|---|
| `municipality_code` | string | yes |  |  |
| `municipality_name` | string |  |  |  |
| `year` | int | yes |  | Latest year available for the municipality |
| `total_mwh` | float |  | MWh | Sum of published sector values |
| `industrial_mwh` | float |  | MWh |  |
| `n_suppressed_sectors` | int |  |  | Sectors withheld by the source |
| `total_is_lower_bound` | bool |  |  | True when any sector was suppressed |

## Congestion (Hsiang Wei)

Outputs `congestion_records.csv`, `node_matching.csv`, `congestion_node_summary.csv`. Optional crosswalk input columns: `congestion_source_node_id`, `grid_source_node_id` (+ free-text `note`). The 12-month window ends at `congestion.reference_period_end` (project.yaml) or the latest month in the data.

### `congestion_input`

| column | type | required | unit | description |
|---|---|---|---|---|
| `source_node_name` | string | yes |  | Node name as published by the source |
| `period_start` | date | yes |  | Start of the observation period (month) |
| `erni_mwh` | float | yes | MWh | Non-integrated renewable energy in the period |
| `source_node_id` | string |  |  | Source identifier, if published |
| `network_level` | string |  |  | transmission | distribution |

### `node_matching`

| column | type | required | unit | description |
|---|---|---|---|---|
| `congestion_source_key` | string | yes |  | source_node_id or name if no id |
| `source_node_id` | string |  |  |  |
| `source_node_name` | string | yes |  |  |
| `node_id` | string |  |  | Matched canonical node (null if not matched) |
| `match_method` | string | yes |  | crosswalk | source_id | name | none |
| `match_status` | string | yes |  | matched | ambiguous | unmatched |
| `match_reliability` | string | yes |  | high | medium | none |
| `candidates` | string |  |  | Candidate node_ids for ambiguous matches |

### `congestion_node_summary`

| column | type | required | unit | description |
|---|---|---|---|---|
| `node_id` | string | yes |  |  |
| `erni_12m_gwh` | float |  | GWh | ERNI in the 12-month reference window |
| `erni_total_gwh` | float |  | GWh | ERNI over the full observation period |
| `erni_months_observed` | int |  |  | Months with data in the 12m window |
| `erni_window_start` | string |  |  |  |
| `erni_window_end` | string |  |  |  |
| `erni_match_method` | string |  |  | How the record was linked to the node |
| `erni_source_keys` | string |  |  | Source keys aggregated into this node |

## Renewables (Isabella)

Outputs `renewable_installations.gpkg` (valid coordinates only) and `.csv` (all records), plus `renewables_summary.csv`. Statuses are mapped with `options.status_map`; unmapped → `unknown` (never counted as operating).

### `renewables_input`

| column | type | required | unit | description |
|---|---|---|---|---|
| `source_installation_id` | string | yes |  |  |
| `capacity_mw` | float | yes | MW | Installed / planned capacity |
| `status` | string | yes |  | Source status, mapped via options.status_map |
| `x` | float | yes | source CRS |  |
| `y` | float | yes | source CRS |  |
| `installation_name` | string |  |  |  |
| `technology` | string |  |  |  |

### `renewable_installations`

| column | type | required | unit | description |
|---|---|---|---|---|
| `source_installation_id` | string | yes |  |  |
| `installation_name` | string |  |  |  |
| `technology` | string |  |  |  |
| `capacity_mw` | float |  | MW |  |
| `status` | string | yes |  | Original status text |
| `status_category` | string | yes |  | operating | pipeline | unknown |
| `coord_valid` | bool | yes |  | False if outside region or unparseable |
| `duplicate_source_id` | bool | yes |  |  |
| `geometry` | geometry | yes |  | Point, EPSG:25831 |

## GIS (Yuki)

Output `gis_node_metrics.csv` and `gis_layers.gpkg` (node_buffers, suitable_land_net, hard_constraints). One `suitable_land_ha_<r>km` and one `<constraint>_share_<r>km` column per buffer radius in spatial.yaml (5, 10, 20 km) — only the 5 km columns are listed below. Metrics whose layer is unavailable are absent/null, never 0.

### `gis_node_metrics`

| column | type | required | unit | description |
|---|---|---|---|---|
| `node_id` | string | yes |  |  |
| `suitable_land_ha_5km` | float |  | ha | Suitable land-cover area minus hard constraints within 5 km (one column per buffer) |
| `protected_area_share_5km` | float |  | fraction | Share of 5 km buffer |
| `flood_zone_share_5km` | float |  | fraction | Share of 5 km buffer |
| `protected_area_conflict` | bool |  |  | Protected area within the configured conflict distance |
| `flood_risk_at_node` | bool |  |  | Node point inside a flood zone |
| `distance_to_major_road_km` | float |  | km |  |

## Integration

Output `data/processed/integrate/nodes_integrated.{gpkg,csv,parquet}`; one row per grid node. Additional pass-through columns (e.g. `source_node_id`, `headroom_note`, `erni_total_gwh`, buffer variants) follow the listed columns. The `_10km` suffix reflects `integration.aggregation_radius_km`.

### `integrated_nodes`

| column | type | required | unit | description |
|---|---|---|---|---|
| `node_id` | string | yes |  |  |
| `node_name` | string | yes |  |  |
| `operator` | string |  |  |  |
| `network_level` | string |  |  |  |
| `voltage_kv` | float |  | kV |  |
| `generation_available_mw` | float |  | MW |  |
| `demand_available_mw` | float |  | MW |  |
| `bess_headroom_proxy_mw` | float |  | MW |  |
| `erni_12m_gwh` | float |  | GWh |  |
| `erni_match_method` | string |  |  |  |
| `renewable_mw_10km` | float |  | MW | Operating capacity within radius |
| `renewable_pipeline_mw_10km` | float |  | MW | Pipeline capacity within radius |
| `nearby_demand_mwh_10km` | float |  | MWh | Area-weighted annual municipal demand within radius (proxy) |
| `nearby_industrial_demand_mwh_10km` | float |  | MWh |  |
| `suitable_land_ha_5km` | float |  | ha |  |
| `protected_area_conflict` | bool |  |  |  |
| `flood_risk_at_node` | bool |  |  |  |
| `distance_to_major_road_km` | float |  | km |  |
| `dq_indicator_completeness` | float |  | fraction | Share of scoring indicators that are non-null for this node |
| `lon` | float | yes | deg |  |
| `lat` | float | yes | deg |  |
| `geometry` | geometry | yes |  | Point, EPSG:25831 |

## Scoring

Output `scores_long.csv` (one row per node × scenario) and `scores_wide.csv`.

### `scores`

| column | type | required | unit | description |
|---|---|---|---|---|
| `node_id` | string | yes |  |  |
| `scenario` | string | yes |  |  |
| `score` | float |  | 0-1 | Weighted normalised score (illustrative) |
| `rank` | int |  |  | 1 = highest score; null if unranked |
| `weight_coverage` | float | yes | fraction | Share of scenario weight with data |
| `missing_indicators` | string |  |  |  |
| `excluded_reason` | string |  |  | Why the node is unranked |

## ML Opportunity Classifier

Output `ml_predictions.csv` (one row per node) and `ml_feature_importance.csv`.

### `ml_predictions`

| column | type | required | unit | description |
|---|---|---|---|---|
| `node_id` | string | yes |  |  |
| `ml_label` | int | yes |  | 1 if node has an operating renewable within label radius |
| `ml_opportunity_prob` | float | yes | 0-1 | Random Forest predicted probability |
| `ml_opportunity` | bool | yes |  | True if probability ≥ threshold and no existing project nearby |

### `ml_feature_importance`

| column | type | required | unit | description |
|---|---|---|---|---|
| `feature` | string | yes |  | Indicator name |
| `importance` | float | yes |  | Mean decrease in impurity (Gini importance) |
| `rank` | int | yes |  | 1 = most important feature |

## Data-quality indicators

Tracked separately from opportunity scores (no combined confidence score in v0.1):

| Aspect | Where |
|---|---|
| Completeness | `completeness` in every quality report; `dq_indicator_completeness` per node |
| Source age | `publication_date` / `retrieval_date` in datasets.yaml and the data manifest |
| Geographic precision | `spatial_resolution` metadata; coordinate validity flags |
| Match reliability | `match_method`, `match_reliability` in `node_matching.csv`; `erni_match_method` per node |
| Proxy vs direct observation | documented per indicator in docs/methodology.md (headroom and nearby demand are proxies) |
| Temporal coverage | `observation_period` metadata; `erni_months_observed` per node |
