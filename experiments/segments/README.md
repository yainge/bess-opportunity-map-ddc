# Local trial: market segments of the existing battery projects (option 2)

Status: experiment, untracked by git. Built 2026-11-15.

Run:
```
experiments/heatmap/.venv/bin/python experiments/segments/build_project_segments.py
```

## Question

Instead of classifying land, classify the projects developers have actually filed. Which kinds
of stand-alone battery project exist in Catalonia, where does each kind go, and how far has
each kind got through permitting?

## Unit and data

One site = one connected footprint in the Generalitat layer `ENERGIA_BATERIES_STANDALONE`
(108 rows after dropping the refused one, 74 sites, 1,384 MW). Rows that share a footprint are
aggregated: 15 sites hold several filings of 5 MW or less, filed under different company names
(e.g. seven 4.5 MW filings on one plot at Bellissens). Per site: MW, number of filings and
promoters, status, land class, environmental procedure, filing year, municipality. Location
attributes come from the 500 m pixel grid (`experiments/heatmap/output/`) and the nearest node
in Fernando's table (`data/processed/grid_topology/ree_nodes_matched.csv`).

## Method

Ward hierarchical clustering on seven standardised features: log MW, log distance to the
nearest 220/400 kV substation, to the nearest 400 kV substation and to the nearest
distribution substation, log demand within 10 km, log renewables (operating + pipeline)
within 10 km, urban-land flag. Silhouette is flat (0.19 to 0.24 for k = 3 to 6, see
`output/k_selection.csv`), so k cannot be chosen from it with 74 sites; k = 4 is fixed as the
smallest k at which size, urban land and distance to the transmission grid separate. Names
in `segment_names.json` were written after reading `output/segment_profiles.csv`.

## Result

| Segment | Sites | MW | Median MW | Urban land | Authorised | Where |
|---|---|---|---|---|---|---|
| Industrial belt, 20 MW and above next to 400 kV nodes | 22 | 780 | 21 | 34% | 23% | Castellbisbal, Rubí, Palau-solità |
| Metropolitan 20 MW on urban land, distribution-connected, far from 400 kV | 15 | 316 | 20 | 80% | 20% | L'Hospitalet, Cervelló, Montgat, Girona |
| Small 5 MW units near 220 kV substations in mid-size towns | 34 | 274 | 5 | 44% | 18% | Vic, Tarragona, la Canonja, l'Arboç |
| Remote rural, next to renewable plants, far from the distribution grid | 3 | 14 | 4 | 0% | 0% | Ciutadilla, Vilalba dels Arcs |

What it says:
- Two business models dominate: many small 5 MW units (34 sites, 46% of sites, 20% of MW) and
  fewer 20 MW+ plants in the Vallès and Baix Llobregat industrial belt (22 sites, 56% of MW).
- The 5 MW segment has 34 different promoters and a top-promoter share of 3%: it is a crowd of
  small developers, often splitting one plot into several sub-5 MW filings (21% of sites in
  the segment). The large segment is more concentrated and is the only one with Ministry
  files (projects above 50 MW).
- Authorisation rates are the same across segments (18 to 23%, 14 of 74 sites overall, as of
  Nov 2026). Permitting outcome so far does not depend on the kind of project; it depends on
  filing year (most authorised files are from 2024).
- Only 3 sites sit next to renewable plants. The "battery next to the solar park" model is
  nearly absent from the stand-alone register (hybrid storage is filed with the plant and is
  not in this layer).

## Outputs (`output/`)

`segments.html` (interactive, one layer per segment, tooltips with filings, promoters, status,
nearest node and queue), `segments.png`, `project_sites_segments.gpkg` / `.csv` (all site
attributes and segment), `segment_profiles.csv`, `segment_centroids_zscore.csv`,
`k_selection.csv`, `metrics.json`.

## Caveats

- 74 sites is small; the segments are descriptive, not a statistical model.
- "Authorised" means the Generalitat or Ministry authorisation, not grid access granted.
- Distribution substation distance uses the e-distribución layer; most 5 MW units connect
  there, so the transmission-node attributes are context for them, not the connection point.
