# Decision log

Record significant technical and methodological decisions here (newest first). Methodology
decisions also get a CHANGELOG entry.

Template:

```
## D<n> - <title> (YYYY-MM-DD)
Context: ...   Decision: ...   Alternatives considered: ...   Consequences: ...   Decided by: ...
```

## D9 - Out-of-fold probabilities for the ML opportunity classifier (2026-11-01)
Context: in-sample Random Forest probabilities reproduce the training labels, so no node
without a nearby operating plant could exceed the threshold. Decision: score every node with
stratified k-fold `cross_val_predict` (k = min(5, smallest class)); feature importances come
from a final fit on all nodes. Consequences: first real run gives CV ROC AUC 0.90 and 11
flagged nodes. The label is renewable siting, not BESS value, so flags are exploratory.
Decided by: Yuki (to confirm with team).

## D8 - Normalise municipality codes to 5-digit INE (2026-11-01)
Context: ICGC boundaries carry a 6-digit code (INE + check digit); ICAEN demand uses 5 digits.
Decision: drop the check digit and zero-pad both sides before joining. Alternatives: fix only
the download script (rejected: other boundary sources may use either format).
Consequences: all 947 municipalities match. Decided by: Yuki.

## D7 - Area-weighted allocation of municipal demand (2026-10-08)
Context: a first centroid-in-radius implementation gave 0 MWh for nodes with no municipal
centroid within 10 km, which reads as "no demand". Decision: allocate municipal demand by the
share of municipal area inside the buffer. Alternatives: centroid method (rejected: artificial
zeros), population-weighted allocation (better; deferred until population grids are
available). Consequences: assumption A6. Decided by: implementation (to confirm with Fernando).

## D6 - Ambiguous node matches are never merged (2026-10-08)
Context: names repeat between transmission and distribution nodes. Decision: several
candidates ⇒ `ambiguous`, resolved only by a reviewed crosswalk entry. Consequences: some ERNI
stays unassigned until reviewed; every decision is in `node_matching.csv`.

## D5 - Fingerprint-based up-to-date detection (2026-10-08)
Decision: stages re-run only when input checksums, relevant configuration, upstream outputs
or code change; `--force` overrides. Alternative: always re-run (slow with large GIS layers)
or timestamps (unreliable across machines / git checkouts).

## D4 - Separate demo and real workspaces (2026-10-08)
Decision: synthetic data lives in `data/sample/` → `results/demo/`; real data in `data/raw/` →
`data/processed/` → `results/real/`. Real mode never falls back to synthetic data.

## D3 - Files, not a database (2026-10-08)
Decision: CSV / GeoPackage / Parquet on disk; no PostGIS, Docker or cloud services in v0.1.
Reason: simplest setup for five students; QGIS reads GeoPackage directly.

## D2 - uv for environments (2026-10-08)
Decision: `uv` with `uv.lock` and a project-local `.venv`, Python 3.12. Reason: one tool for
Python installation, locking and syncing on macOS, Linux and Windows.

## D1 - Grid nodes as analytical unit (project definition)
Decision: start from the electrical network (grid opportunity → land feasibility → candidate
areas), not from land parcels. Reason: connection is the binding constraint for BESS.
