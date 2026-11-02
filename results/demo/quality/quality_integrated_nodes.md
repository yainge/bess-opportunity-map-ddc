# Quality report: integrated_nodes

- Stage: `integrate`
- Mode: `demo`
- **SYNTHETIC DEMONSTRATION DATA - not a real measurement**
- Issues: 0 error(s), 2 warning(s), 2 info

## Metrics

| metric | value |
|---|---|
| grid_nodes | 24 |
| congestion_nodes_joined | 11 |
| erni_source_nodes_matched | 11 |
| erni_source_nodes_unmatched | 2 |
| erni_source_nodes_ambiguous | 1 |
| renewable_installations_used | 196 |
| gis_municipalities_source_crs | EPSG:25831 |
| demand_year | 2024 |
| gis_nodes_joined | 24 |
| domains_included | grid,congestion,renewables,demand,gis |
| milestone | M3: grid + ERNI + renewables + demand + land feasibility |
| upstream_runs | grid=20261026T011119Z-5dba2e, congestion=20261026T011119Z-5dba2e, renewables=20261026T011119Z-5dba2e, demand=20261026T011119Z-5dba2e, gis=20261026T011119Z-5dba2e |

## Checks

| level | check | message | count | examples |
|---|---|---|---|---|
| info | renewables | Capacity summed within 10.0 km; overlapping catchments count an installation for every node in range |  |  |
| warning | demand_match | Municipalities without demand data | 2 |  |
| warning | demand_match | Demand rows without a municipal boundary | 1 | 99099 |
| info | demand | Municipal annual demand allocated by buffer area share (proxy; lower bound where sectors are suppressed or data is missing) |  |  |

## Completeness (share non-null)

| column | share |
|---|---|
| bess_headroom_proxy_mw | 70.83% |
| generation_available_mw | 87.50% |
| demand_available_mw | 87.50% |
| erni_12m_gwh | 45.83% |
| renewable_mw_10km | 100.00% |
| renewable_pipeline_mw_10km | 100.00% |
| nearby_demand_mwh_10km | 100.00% |
| suitable_land_ha_5km | 100.00% |
| distance_to_major_road_km | 100.00% |
