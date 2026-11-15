# Raw data: stand-alone battery storage projects in Catalonia

Source: Generalitat de Catalunya environmental viewer, WFS service
`https://sig.gencat.cat/ows/ENERGIA/wfs`, layer `ENERGIA:ENERGIA_BATERIES_STANDALONE`.
Downloaded 2026-11-05 with GDAL (the server rejects plain `curl`/`urllib` user agents;
GDAL, QGIS and browsers work). 109 polygons, EPSG:25831.

Files
- `ENERGIA_BATERIES_STANDALONE_20261105.gpkg`: the layer as served, unmodified.
- `ENERGIA_BATERIES_STANDALONE_20261105.csv`: same attributes, `;`-separated like the
  renewables CSVs, plus polygon centroid (`X_UTM31N`, `Y_UTM31N`, `LON`, `LAT`),
  computed area (`AREA_POLIGON_HA`) and the polygon as WKT (`WKT_25831`).

Columns (from the WFS schema): ID, NOM (project name), EXPEDIENT (file number; `FUE-...`
Generalitat, `SGEA/...` Ministry), PROMOTOR (developer), OFICINA (territorial office:
OTAABA Barcelona, OTAATA Tarragona, OTAAGI Girona, OTAACC Catalunya Central, OTAAPE
Penedès, OTAALL Lleida, OTAATE Terres de l'Ebre, OAA / Ministerio), POTENCIA (MW),
SUPERFICIE (ha), TRAMIT_AMB (environmental-assessment case), URL (DOGC/BOE/portal
document), ESTAT (status), TIPUS_SOL (land class), ESTAT_AMB (environmental status).

Status as of download: En tramitació 82, Autoritzat 22, Autoritzat pel Ministerio 2,
En tramitació al Ministerio 2, No autoritzat 1. Total 1,389 MW (one row has no power).
None is in service yet.

Known gaps and quirks
- Stand-alone batteries only. Batteries hybridised with a solar or wind plant are not in
  this layer (the Govern cited 9 hybrid projects in 2025).
- Many sites are split into several 4.99–5 MW files with identical or adjacent polygons
  (e.g. Ripoll I–VI, Bellissens 2–8, Rubí I–VII), apparently to stay under permitting
  thresholds. 109 rows collapse to 77 distinct footprints; aggregate by footprint before
  counting sites or modelling.
- Three NOM/EXPEDIENT/PROMOTOR values contain trailing newlines in the source; the CSV
  has them stripped, the GeoPackage keeps them as served.
- `FUE-2024-04095643` appears twice (Ebro Energy Juià: original "No autoritzat" and its
  modification "En tramitació").
- Historical projects that were refused or withdrawn are mostly absent (only one
  "No autoritzat"), so this layer alone cannot support a permitting-outcome model.
