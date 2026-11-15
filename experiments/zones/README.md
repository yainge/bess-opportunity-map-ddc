# Local trial: storage access status by REE capacity zone (option 3)

Status: experiment, untracked by git. Built 2026-11-15.

Run:
```
experiments/heatmap/.venv/bin/python experiments/zones/build_zone_map.py
```

## Idea

REE's per-node access-capacity files already define the electrical regions that matter for a
connection request: each node either belongs to a shared-capacity zone (`Zona con capacidad
compartida`, codes like E364_SEPE) or has node-level capacity, and the file names the criterion
that binds (`Din1_Zona`, `Est_Alm_Zona`, ...). Instead of clustering geography, this map uses
those zones as the unit and shows the current storage access status inside each one.

## Data

- Zones, static zone margins, dynamic margins, limiting criterion, demand-side reason: sheet
  "Nudos" of Polo's workbook, which is REE's national demand access-capacity file (version of
  about 1 Oct 2026). Zones are structural; they do not change month to month.
- Coordinates, under-construction flags, Nov 2026 available capacity in injection and charging
  mode, granted and pending MW, generation-side reason, tender flag: Fernando's
  `ree_nodes_matched.csv` (REE files of 3 Nov 2026).
- Line connections between substations: Fernando's `catalonia_grid.geojson` (OpenStreetMap).
- Battery filings: Generalitat layer.

## Method

Thiessen polygons of the 97 substation sites, clipped to Catalonia, dissolved by zone (sites
with no shared zone stay as one region per site): 68 regions, 27 of them shared zones. Each
node gets a status in injection mode from the Nov 2026 file: room for storage (available MW > 0),
reserved for tender ("Concurso por resolución SEE"), zonal margin reserved for tender,
no connection possible, or no capacity with no reason stated. A region takes the best status of
its nodes. The charging-mode status is kept separately (REE grants it separately).

## Result (Nov 2026)

| Status in injection mode | Regions | Nodes | Battery filings inside |
|---|---|---|---|
| Room for storage | 4 | 12 | 16 |
| Reserved for tender | 28 | 43 | 40 |
| Zonal margin reserved for tender | 4 | 8 | 21 |
| No connection possible | 9 | 21 | 10 |
| No capacity, reason not stated | 23 | 33 | 21 |

Room exists in four regions only: zone E208 (Penedès, Puigpelat: 307 MW, but 1,072 MW of
storage already pending), zone E364 (Tarragona: Bellicens, Constantí, La Secuita, La Selva,
Perafort: 40 MW), zone E150 (Begues: 7 MW) and the single node Rubió 220 (39 MW, 179 MW
pending). Tender nodes: Puigpelat 220, Vandellòs 400, Zona Franca 220. In charging mode, 55
nodes are blocked because the reference value with the distribution company is not agreed,
an administrative block rather than a physical one.

Reading for a developer: in Catalonia today, access for a new stand-alone battery goes through
a tender at 51 of 117 nodes, is physically impossible at 21, and is open at 12, most of which
already have a queue larger than the room. The 108 battery filings in the Generalitat
register sit mostly in tender-reserved regions, which is consistent with developers filing
the land permit first and waiting for a tender.

## Outputs (`output/`)

`zone_map.html` (regions with full figures on hover, line connections, nodes, filings),
`zone_map.png`, `zones.gpkg` (layers `regions`, `nodes`), `zone_table.csv` (one row per region:
nodes, kV, room, zone margins, limiting criterion, granted, pending, tenders, filings inside),
`node_table.csv`, `metrics.json`.

## Caveats and next steps

- The zone codes come from the demand file. The generation file (injection mode) has its own
  zone column; Fernando has the raw file and should confirm the zones match. Until then the
  zone outlines are from the charging-mode file and the colours from the injection-mode file.
- 44 nodes have zero capacity and no reason in the generation file; they are all inside shared
  zones, so the zone limit applies, but REE does not say which. Shown grey.
- Thiessen polygons are a drawing convention; the real zone is electrical, not territorial.
- This map updates when the next monthly REE file is dropped in; the history of these files is
  the forecast product (option 1).
