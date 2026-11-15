# Transmission grid geometry for Catalonia (OpenStreetMap via PyPSA-Eur)

Source: "Prebuilt Electricity Network for PyPSA-Eur based on OpenStreetMap Data", v0.7,
Zenodo record 18619025 (DOI 10.5281/zenodo.18619025), licence ODbL (attribute
OpenStreetMap contributors). Europe-wide, 220 kV and above, built from OSM power=line /
power=substation data. Downloaded 2026-11-05 and clipped to Catalonia (NUTS2 ES51 from
Eurostat GISCO, 3 km buffer).

Files
- `osm_pypsa_transmission_catalonia_20261105.gpkg`, layers:
  `lines` (130 AC lines: 96 x 220 kV, 1,490 km; 34 x 400 kV, 1,280 km inside Catalonia;
  columns voltage, circuits, i_nom, s_nom, r, x, b, length, underground, type, OSM ids),
  `substations` (107 buses: 82 x 220 kV, 24 x 400 kV, 1 x 320 kV DC converter),
  `dc_links` (the two 320 kV INELFE France–Spain cables, 1,000 MW each),
  `catalonia_nuts2` (the clip polygon). CRS EPSG:25831.
- `osm_pypsa_transmission_lines_catalonia_20261105.csv` and
  `osm_pypsa_substations_catalonia_20261105.csv`: same attributes, WGS84, lines as WKT.

Notes
- Lines crossing the border are kept whole; `length_in_cat_km` is the part inside Catalonia.
- Substations carry OSM ids but no names in this dataset; names can be joined from OSM later.
- Check against the REE node sheet (`Dataset_SusbtationNodes.xlsx`): 63 of 98 matched REE
  nodes lie more than 2 km from any OSM substation, two more than 30 km (ELS AUBALS,
  MASDENVERGE). The REE sheet coordinates look approximate; verify before using them for
  buffers.
- Distribution-level lines (110/132 kV, e-distribución) are not included. Sources for those:
  OpenStreetMap directly (Overpass, power=line with voltage 110000/132000) or the ICGC
  topographic base, dataset "Xarxa de línies elèctriques" (Pla Cartogràfic ID 30605).
