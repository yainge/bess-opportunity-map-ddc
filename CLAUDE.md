# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

All commands go through the start scripts, which bootstrap `.venv` via `uv` and forward to the CLI. Use `./start.sh` on macOS/Linux and `.\start.ps1` on Windows.

```bash
# Environment
./start.sh --setup                               # verify install, create directories

# Pipeline
./start.sh --mode demo --all                     # synthetic end-to-end run (safest first test)
./start.sh --mode real --steps <stage>           # one stage on real data
./start.sh --mode real --all                     # all stages (optional ones skipped if no data)
./start.sh --mode real --all --dry-run           # show plan without running
./start.sh --mode real --validate                # load + validate inputs, write quality reports
./start.sh --mode real --steps <stage> --force   # re-run even if up to date

# Development
./start.sh --test                                # full test suite
./start.sh --test -m "not slow"                  # unit tests only (fast)
./start.sh --lab                                 # JupyterLab on notebooks/

# Linting (no auto-fix flag needed for checking)
uv run ruff check src tests
uv run ruff format src tests
```

Stages in dependency order: `grid → demand → congestion → renewables → gis → integrate → score → export`.

The `BESS_PROJECT_ROOT` environment variable overrides root detection (used in tests).

## Architecture

### Core idea

Grid nodes are the analytical unit. The pipeline attaches electrical and spatial indicators to each canonical `node_id`, then scores and ranks them across three scenarios (renewable absorption, connection readiness, load/grid support).

### Package layout (`src/bess_catalonia/`)

Each domain is a sub-package owned by one team member:

| Sub-package | Owner | Purpose |
|---|---|---|
| `grid/` | Polo | Reads node list + access capacity; creates `node_id`; is the canonical coordinate source |
| `demand/` | Fernando | ICAEN municipal electricity consumption; long table + municipal summary |
| `congestion/` | Hsiang Wei | ERNI records + rule-based node matching (`matching.py`) to link source keys → `node_id` |
| `renewables/` | Isabella | Installation coordinates, capacity, status classification |
| `gis/` | Yuki | Buffer metrics, land cover/constraint overlays, road distance (`spatial.py`) |
| `integration/` | Coordinator | Joins all processed outputs onto grid nodes by `node_id`; area-weighted spatial demand |
| `scoring/` | Team | Min-max normalisation, scenario weights (`model.py`), exclusion rules |
| `export/` | Yuki | Writes `bess_master.gpkg`, CSV tables, PNG maps, `summary.md` |

Core modules: `pipeline.py` (orchestration), `config.py` (YAML loading + path resolution), `schemas.py` (canonical column contracts + type coercion), `quality.py` (QualityReport), `io.py` (safe atomic writes, `Loaded` dataclass), `provenance.py` (fingerprints, run records), `demo.py` (synthetic data generation), `units.py` (unit conversion), `cli.py` (argparse → pipeline).

### Domain module interface

Every domain module exposes four functions:
```python
load(ctx)              # read + map columns + coerce types + convert units → Loaded
validate(loaded, ctx)  # domain rules → [QualityReport]
process(loaded, ctx)   # pure transformation into canonical schema → DataFrame/GeoDataFrame
run(ctx)               # load → validate → (stop on errors) → process → write → StageResult
```

`--validate` calls only `load` + `validate`. `ctx` is a `RunContext` (see `pipeline.py`) giving access to config, mode paths, dataset specs, and upstream outputs.

### Configuration (`config/`)

| File | Controls |
|---|---|
| `project.yaml` | Mode paths, CRS, bbox, optional stages, logs dir |
| `datasets.yaml` | Per-mode dataset entries: path, format, column mapping, units, provenance metadata |
| `scoring.yaml` | Indicators (direction, normalisation, missing policy), scenario weights |
| `spatial.yaml` | Buffer sizes, land-cover codes, constraint layers, road accessibility |

`datasets.yaml` has a `demo:` block (synthetic) and a `real:` block. A real entry with `path: null` means "not yet delivered" — the stage is skipped or blocked depending on whether it is optional.

### Data contracts and identifiers

- **`node_id`** = `<operator>-<source_node_id>` (e.g. `REE-SYN_T01`). Created by the `grid` stage. Source ids are always preserved alongside.
- **CRS:** analysis in EPSG:25831 (metres); lon/lat EPSG:4326 kept as columns. Each dataset declares `source_crs` in `datasets.yaml`; CRS stored in a file wins.
- **Units:** MW / MWh / GWh (explicit in column names). Conversions declared in `datasets.yaml → units:`.
- **Missing values are null, never zero.** Type coercion in `schemas.coerce_types` enforces this.
- The canonical column list for every schema lives in `schemas.SCHEMAS`; `docs/data_contract.md` mirrors it (a test asserts they stay in sync).

### Modes

| | `demo` | `real` |
|---|---|---|
| inputs | `data/sample/` (synthetic, auto-generated) | `data/raw/` (official sources, git-ignored) |
| processed | `results/demo/processed/` | `data/processed/` |
| results | `results/demo/` | `results/real/` |

Real mode never falls back to synthetic data. The two modes never share folders.

### Up-to-date detection

Each stage writes `<processed_root>/<stage>/_stage.json` with a fingerprint (SHA-256 of input checksums + config sections + upstream fingerprints + package source hash). Identical fingerprint + existing outputs → stage is skipped. `--force` bypasses this. Outputs are written atomically (temp file → rename), so a failed run never corrupts a prior good output.

### Tests

- `tests/unit/` — fast, run without real data; cover schemas, validation rules, domain logic, config validation.
- `tests/integration/` — marked `slow`; end-to-end demo pipeline and notebook/doc checks.
- `tests/fixtures/` — small CSV samples (e.g. `icaen_demand_format_sample.csv`).
- `tests/conftest.py` — shared fixtures including `cfg`, `demo_ctx`, `demo_project` (isolated temp project root).

### Contributing a dataset (real mode)

1. Place the file in `data/raw/<domain>/`.
2. Edit the `real:` entry in `config/datasets.yaml` (path, format, `source_crs`, `columns` mapping, `units`, `metadata`).
3. `./start.sh --mode real --validate` → fix errors.
4. `./start.sh --mode real --steps <domain>`.
5. `./start.sh --mode real --record-manifest` (commits `data/manifests/real_datasets.json`).

### PR checklist

Before every PR: `./start.sh --test`, `./start.sh --mode demo --all`, `uv run ruff check src tests`. PRs touching `schemas.py`, `data_contract.md`, `integration/`, `gis/spatial.py`, `spatial.yaml`, `scoring/`, or `pipeline.py` require review by at least one other member.
