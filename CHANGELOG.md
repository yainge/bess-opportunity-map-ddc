# Changelog

All notable changes to this project are documented here. Format:
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/). Dataset updates are recorded in
`data/manifests/`, pipeline executions in `logs/runs/` — not here.

## [Unreleased]

### Added
- `docs/data_pipeline_overview.md`: data pipeline overview table and Mermaid flowchart covering
  all five data categories (grid nodes, congestion, demand, renewables, GIS/land) — dataset,
  source, variables, cleaning, processing, usage, outputs and implementation status per domain.

### Changed
- Project (distribution) and virtual-environment prompt renamed from `bess-catalonia` to
  `bess-opportunity-map-ddc` to match the repository; the Python import package stays
  `bess_catalonia`.
- README clone instructions point to the GitHub repository.

## [0.1.0] - 2026-10-08

Initial software foundation. All functionality tested on synthetic data only; no real-data
results exist yet.

### Added
- uv-managed environment (Python 3.12, `pyproject.toml`, `uv.lock`, project-local `.venv`).
- `start.sh` (macOS/Linux) and `start.ps1` (Windows) entry points: detect repo root, check for
  uv (install instructions instead of a silent installer), sync `.venv` against the lockfile,
  forward arguments, return exit codes.
- CLI (`bess_catalonia.cli`): `--setup`, `--mode demo|real`, `--steps`, `--all`, `--validate`,
  `--dry-run`, `--force`, `--record-manifest`, `--lab`, `--test`.
- Pipeline orchestration with stages `grid`, `demand`, `congestion`, `renewables`, `gis`,
  `integrate`, `score`, `export`; dependency-ordered planning; optional-stage skipping in
  `--all`; explicit errors for missing required data; fingerprint-based up-to-date detection;
  atomic writes; per-stage lineage manifests; run records and log files.
- Configuration: `project.yaml`, `datasets.yaml` (demo and real entries, column mappings,
  units, provenance metadata), `spatial.yaml`, `scoring.yaml`, with cross-file validation.
- Canonical schemas (`schemas.py`) and data contract documentation; type coercion that turns
  unparseable values into reported nulls; explicit unit conversion (`units.py`); parsing of
  Catalan-formatted numbers.
- Data-quality reports (JSON + Markdown) for every dataset and stage.
- Provenance: dataset records with SHA-256 checksums, data-version manifests
  (`--record-manifest`) and drift detection in `--validate`.
- Grid stage: canonical `node_id`, duplicate detection, coordinate plausibility checks,
  CRS transformation to EPSG:25831, `bess_headroom_proxy_mw` with comparability rules.
- Demand stage: municipal × year × sector table kept at source resolution, latest-year
  summary, suppressed values kept null with `total_is_lower_bound`. Real-mode configuration
  for the ICAEN-format municipal consumption file.
- Congestion stage: auditable node matching (crosswalk → source id → unique normalised name),
  ambiguous/unmatched reporting, 12-month ERNI per node with coverage.
- Renewables stage: operating vs pipeline via status mapping, coordinate validation,
  duplicate-id flags.
- GIS stage: 5/10/20 km buffers, suitable land net of hard constraints, constraint shares,
  protected-area conflict, flood risk at node, distance to major roads.
- Integration: partial integration onto grid nodes, area-weighted municipal demand, renewable
  capacity within radius, milestone tracking (M0–M3), per-node indicator completeness.
- Scoring: min-max / percentile normalisation, indicator directions, missing-value policies
  (reweight / worst / exclude), minimum weight coverage, hard screening filters,
  deterministic ranking; three illustrative scenarios.
- Export: master GeoPackage, CSV tables, PNG maps (synthetic watermark in demo mode), run
  summary.
- Deterministic synthetic demonstration dataset generator with deliberate data problems.
- Three exploration notebooks (data, spatial, model) running on the demo data.
- Test suite (unit + integration: CLI, configuration, validation, matching, units, CRS,
  buffers, areas, integration, scoring, determinism, GeoPackage, notebooks, docs consistency).
- Documentation: README, architecture, data contract, dataset inventory, methodology,
  assumptions, decision log, team workflow, future features, QGIS notes, PR template.
