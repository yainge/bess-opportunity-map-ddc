# Deferred features

Deliberately not implemented in v0.1, with the reason and the intended hook.

| Feature | Why deferred | How it fits |
|---|---|---|
| Sensitivity: alternative normalisation | Weight perturbation and leave-one-out are done (`scoring/sensitivity.py`) | Add a normalisation option to `rank_stability` |
| Slope / terrain constraints | DTM not yet available; avoid heavy raster work early | Add `rasterio` (`uv add rasterio`), zonal slope per buffer in `gis/`, new constraint in `spatial.yaml` |
| Explicit data refresh / download commands | Acquisition must stay separate from processing | A future `--refresh <dataset>` that downloads to a new dated file and updates the manifest; never run implicitly |
| Combined confidence score | Opportunity, data quality and stability must first be understood separately | Quality indicators already recorded per node and per dataset |
| Population-weighted demand allocation | Needs population grid | Replace area weights in `area_weighted_sum` with population weights |
| Social / socio-economic indicators | Scope for later phases | New GIS/demand indicators + scoring entries |
| Candidate-area polygons per top node (case studies) | Needs real land data | Export of `suitable_land_net ∩ buffer` per selected node |
| Interactive web map | Static maps and QGIS suffice for now | Could export GeoJSON for a simple web viewer |
| QGIS project / style files | Wait for real layers | `qgis/` |
| Techno-economic assessment for selected sites | Innovation track | Separate notebook / module using integrated indicators |
| CI (GitHub Actions running tests) | Repository hosting not set up yet | `uv sync --locked && uv run pytest` |
