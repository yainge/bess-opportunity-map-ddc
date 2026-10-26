"""Pipeline orchestration: stage registry, execution planning and run records.

Stages run in the fixed dependency order of ``STAGE_ORDER``. Each stage writes its outputs to
``<processed_root>/<stage>/`` together with a ``_stage.json`` manifest holding a fingerprint
of everything the output depends on (input file checksums, relevant configuration, upstream
outputs and package source). A stage whose fingerprint is unchanged is reported as
"up to date" and not re-run unless ``--force`` is given.
"""

from __future__ import annotations

import importlib
import json
import logging
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from bess_catalonia.config import Config, DatasetSpec, load_config
from bess_catalonia.io import MissingDataError, write_text
from bess_catalonia.provenance import (
    RunRecord,
    StageRecord,
    code_fingerprint,
    compare_manifest,
    new_run_id,
    now_iso,
    sha256_file,
)
from bess_catalonia.quality import DataValidationError, QualityReport

STAGE_ORDER = ("grid", "demand", "congestion", "renewables", "gis", "integrate", "score",
               "ml", "export")
MANIFEST = "_stage.json"
logger = logging.getLogger("bess_catalonia")


@dataclass(frozen=True)
class StageSpec:
    name: str
    owner: str
    description: str
    module: str
    required_datasets: tuple[str, ...] = ()
    optional_datasets: tuple[str, ...] = ()
    needs_any_dataset: bool = False  # at least one optional dataset must be available
    upstream: tuple[str, ...] = ()  # stages whose output is required
    optional_upstream: tuple[str, ...] = ()  # stages whose output is used when present
    config_keys: tuple[tuple[str, str], ...] = ()  # (config file, top-level key)


STAGES: dict[str, StageSpec] = {
    s.name: s
    for s in (
        StageSpec("grid", "Polo", "Grid nodes, access capacity, headroom proxy",
                  "bess_catalonia.grid.processing", required_datasets=("grid_nodes",),
                  config_keys=(("project", "grid"), ("project", "project"))),
        StageSpec("demand", "Fernando", "Municipal / sector electricity demand",
                  "bess_catalonia.demand.processing", required_datasets=("demand_municipal",)),
        StageSpec("congestion", "Hsiang Wei", "ERNI records, node matching, 12-month totals",
                  "bess_catalonia.congestion.processing",
                  required_datasets=("congestion_erni",),
                  optional_datasets=("congestion_crosswalk",), upstream=("grid",),
                  config_keys=(("project", "congestion"),)),
        StageSpec("renewables", "Isabella", "Renewable installations and pipeline",
                  "bess_catalonia.renewables.processing",
                  optional_datasets=("renewables_installations",
                                     "renewables_solar", "renewables_wind"),
                  needs_any_dataset=True,
                  config_keys=(("project", "project"),)),
        StageSpec("gis", "Yuki", "Node buffers, land feasibility, constraints, access",
                  "bess_catalonia.gis.processing",
                  optional_datasets=("gis_land_cover", "gis_protected_areas", "gis_flood_zones",
                                     "gis_zoning", "gis_roads"),
                  needs_any_dataset=True, upstream=("grid",),
                  config_keys=(("spatial", "buffers_km"), ("spatial", "land_cover"),
                               ("spatial", "constraints"), ("spatial", "accessibility"),
                               ("spatial", "protected_conflict_distance_m"))),
        StageSpec("integrate", "Integration coordinator", "Master node dataset",
                  "bess_catalonia.integration.processing",
                  optional_datasets=("gis_municipalities",), upstream=("grid",),
                  optional_upstream=("demand", "congestion", "renewables", "gis"),
                  config_keys=(("project", "integration"), ("spatial", "municipalities"),
                               ("scoring", "indicators"))),
        StageSpec("score", "Team (methodology)", "Illustrative multi-scenario scoring",
                  "bess_catalonia.scoring.processing", upstream=("integrate",),
                  config_keys=(("scoring", "indicators"), ("scoring", "scenarios"),
                               ("scoring", "exclude_if_true"),
                               ("scoring", "min_weight_coverage"))),
        StageSpec("ml", "Team", "Opportunity classifier: learn from renewable developer siting decisions",
                  "bess_catalonia.ml.processing",
                  upstream=("integrate", "renewables"),
                  config_keys=(("ml", "features"), ("ml", "label"), ("ml", "model"),
                               ("ml", "opportunity_threshold"))),
        StageSpec("export", "Yuki", "Master GeoPackage, CSV, maps, run summary",
                  "bess_catalonia.export.processing", optional_datasets=("gis_municipalities",),
                  upstream=("integrate",), optional_upstream=("score", "gis", "ml")),
    )
}


@dataclass
class StageResult:
    outputs: list[Path] = field(default_factory=list)
    record_counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass
class RunContext:
    config: Config
    mode: str
    run_id: str
    record: RunRecord
    force: bool = False
    assume_available: bool = False  # demo dry run: sample data would be generated first
    _checksums: dict[Path, str] = field(default_factory=dict)

    @property
    def paths(self):
        return self.config.mode_paths(self.mode)

    @property
    def logger(self) -> logging.Logger:
        return logger

    def dataset(self, key: str) -> DatasetSpec:
        spec = self.config.dataset(self.mode, key)
        self.record.add_input(spec, self.config.root)
        return spec

    def available(self, key: str) -> bool:
        if key not in self.config.dataset_keys(self.mode):
            return False
        spec = self.config.dataset(self.mode, key)
        return spec.available or (self.assume_available and spec.configured)

    def stage_dir(self, stage: str) -> Path:
        d = self.paths.processed_root / stage
        d.mkdir(parents=True, exist_ok=True)
        return d

    def manifest(self, stage: str) -> dict | None:
        p = self.paths.processed_root / stage / MANIFEST
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def has_output(self, stage: str) -> bool:
        m = self.manifest(stage)
        return bool(m) and all((self.config.root / o).exists() for o in m.get("outputs", []))

    def upstream_file(self, stage: str, filename: str) -> Path:
        path = self.paths.processed_root / stage / filename
        if not self.has_output(stage) or not path.exists():
            raise MissingDataError(
                f"Output of stage '{stage}' not found ({path}). "
                f"Run: ./start.sh --mode {self.mode} --steps {stage}"
            )
        return path

    def write_report(self, report: QualityReport) -> list[Path]:
        report.mode = self.mode
        for w in report.warnings:
            logger.warning(w)
        return report.write(self.paths.quality_dir)

    def checksum(self, path: Path) -> str:
        if path not in self._checksums:
            self._checksums[path] = sha256_file(path)
        return self._checksums[path]


# ---------------------------------------------------------------------------- fingerprints
def stage_fingerprint(ctx: RunContext, spec: StageSpec) -> str:
    cfg = ctx.config
    datasets = {}
    for key in spec.required_datasets + spec.optional_datasets:
        if key not in cfg.dataset_keys(ctx.mode):
            datasets[key] = {"checksum": None, "spec": None}
            continue
        d = cfg.dataset(ctx.mode, key)
        datasets[key] = {
            "checksum": ctx.checksum(d.path) if d.available else None,
            "spec": (cfg.datasets.get(ctx.mode) or {}).get(key),
        }
    upstream = {u: (ctx.manifest(u) or {}).get("fingerprint")
                for u in spec.upstream + spec.optional_upstream}
    conf = {f"{f}.{k}": getattr(cfg, f).get(k) for f, k in spec.config_keys}
    return cfg.section_hash(spec.name, ctx.mode, code_fingerprint(), datasets, upstream, conf)


def _write_stage_manifest(ctx: RunContext, spec: StageSpec, result: StageResult) -> None:
    root = ctx.config.root
    payload = {
        "stage": spec.name,
        "mode": ctx.mode,
        "run_id": ctx.run_id,
        "finished_at": now_iso(),
        "fingerprint": stage_fingerprint(ctx, spec),
        "upstream_runs": {u: (ctx.manifest(u) or {}).get("run_id")
                          for u in spec.upstream + spec.optional_upstream},
        "outputs": [p.resolve().relative_to(root).as_posix() for p in result.outputs],
        "record_counts": result.record_counts,
    }
    write_text(ctx.stage_dir(spec.name) / MANIFEST, json.dumps(payload, indent=2))


# ---------------------------------------------------------------------------- planning
@dataclass
class PlannedStage:
    name: str
    action: str  # run | up_to_date | skip | blocked
    reason: str = ""


def resolve_stages(steps: str | None, run_all: bool) -> list[str]:
    if run_all:
        return list(STAGE_ORDER)
    names = [s.strip() for s in (steps or "").split(",") if s.strip()]
    unknown = [n for n in names if n not in STAGES]
    if unknown:
        raise ValueError(f"Unknown stage(s) {unknown}. Valid stages: {', '.join(STAGE_ORDER)}")
    if not names:
        raise ValueError("No stages given: use --steps <names> or --all")
    return [s for s in STAGE_ORDER if s in names]


def plan(ctx: RunContext, stages: list[str], explicit: bool) -> list[PlannedStage]:
    optional_in_all = set(ctx.config.project.get("optional_stages_in_all") or [])
    planned: list[PlannedStage] = []
    will_run: set[str] = set()
    for name in stages:
        spec = STAGES[name]
        optional = (not explicit) and name in optional_in_all
        missing = [ctx.config.dataset(ctx.mode, k).describe() for k in spec.required_datasets
                   if not ctx.available(k)]
        if spec.needs_any_dataset and not any(ctx.available(k) for k in spec.optional_datasets):
            missing.append("none of " + ", ".join(spec.optional_datasets) + " is available")
        if missing:
            planned.append(PlannedStage(name, "skip" if optional else "blocked",
                                        "missing input data: " + "; ".join(missing)))
            continue
        lacking = [u for u in spec.upstream if u not in will_run and not ctx.has_output(u)]
        if lacking:
            planned.append(PlannedStage(
                name, "skip" if optional else "blocked",
                "requires output of stage(s) " + ", ".join(lacking) + " (run them first)"))
            continue
        if ctx.force:
            action, reason = "run", "--force"
        elif any(u in will_run for u in spec.upstream + spec.optional_upstream):
            action, reason = "run", "upstream stage re-runs"
        elif (m := ctx.manifest(name)) and ctx.has_output(name) and m.get(
                "fingerprint") == stage_fingerprint(ctx, spec):
            action, reason = "up_to_date", f"inputs unchanged since run {m.get('run_id')}"
        else:
            action, reason = "run", "inputs, configuration or code changed"
        if action == "run":
            will_run.add(name)
        planned.append(PlannedStage(name, action, reason))
    return planned


# ---------------------------------------------------------------------------- execution
def setup_logging(cfg: Config, run_id: str, level: str = "INFO") -> Path:
    log_path = cfg.logs_dir / f"{run_id}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    for h in list(logger.handlers):
        logger.removeHandler(h)
        h.close()
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    console = logging.StreamHandler()
    console.setLevel(getattr(logging, level.upper(), logging.INFO))
    console.setFormatter(logging.Formatter("%(levelname)-7s %(message)s"))
    file_h = logging.FileHandler(log_path, encoding="utf-8")
    file_h.setLevel(logging.DEBUG)
    file_h.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    logger.addHandler(console)
    logger.addHandler(file_h)
    return log_path


def _make_context(cfg: Config, mode: str, stages: list[str], force: bool, dry_run: bool):
    run_id = new_run_id()
    record = RunRecord(run_id=run_id, mode=mode, stages=stages, dry_run=dry_run,
                       configuration={"hash": cfg.section_hash(cfg.as_dict()),
                                      **cfg.as_dict()})
    return RunContext(config=cfg, mode=mode, run_id=run_id, record=record, force=force)


def execute(ctx: RunContext, planned: list[PlannedStage]) -> bool:
    failed: set[str] = set()
    ok = True
    for p in planned:
        spec = STAGES[p.name]
        status = {"skip": "skipped", "run": "planned"}.get(p.action, p.action)
        rec = StageRecord(stage=p.name, status=status, reason=p.reason)
        if p.action == "run" and (bad := [u for u in spec.upstream if u in failed]):
            p = PlannedStage(p.name, "blocked", f"upstream stage(s) failed: {bad}")
            rec.status, rec.reason = "blocked", p.reason
        if p.action == "run":
            logger.info("▶ %s - %s", p.name, spec.description)
            manifest = ctx.paths.processed_root / p.name / MANIFEST
            manifest.unlink(missing_ok=True)  # never leave a stale "up to date" marker
            try:
                result: StageResult = importlib.import_module(spec.module).run(ctx)
                _write_stage_manifest(ctx, spec, result)
                rec.status = "ran"
                rec.outputs = [str(o) for o in result.outputs]
                rec.record_counts = result.record_counts
                rec.warnings = result.warnings
                ctx.record.outputs += rec.outputs
                ctx.record.record_counts.update(
                    {f"{p.name}.{k}": v for k, v in result.record_counts.items()})
                ctx.record.warnings += result.warnings
                logger.info("✔ %s: %s", p.name, result.record_counts)
            except (MissingDataError, DataValidationError, ValueError, KeyError) as exc:
                rec.status, rec.errors = "failed", [str(exc)]
                logger.error("✖ %s failed: %s", p.name, exc)
                logger.debug(traceback.format_exc())
            except Exception as exc:  # unexpected bug: keep full traceback in the log file
                rec.status, rec.errors = "failed", [f"{type(exc).__name__}: {exc}"]
                logger.error("✖ %s failed unexpectedly: %s (traceback in log file)", p.name, exc)
                logger.debug(traceback.format_exc())
            if rec.status == "failed":
                failed.add(p.name)
                ok = False
                ctx.record.errors += [f"{p.name}: {e}" for e in rec.errors]
        elif p.action == "blocked":
            failed.add(p.name)
            ok = False
            ctx.record.errors.append(f"{p.name}: {p.reason}")
            logger.error("✖ %s cannot run: %s", p.name, p.reason)
        elif p.action == "skip":
            logger.warning("⏭  %s skipped (optional): %s", p.name, p.reason)
        else:
            logger.info("✔ %s up to date (%s)", p.name, p.reason)
        ctx.record.stage_results.append(rec)
    return ok


def print_plan(ctx: RunContext, planned: list[PlannedStage]) -> None:
    labels = {"run": "WOULD RUN", "up_to_date": "UP TO DATE", "skip": "SKIP (optional)",
              "blocked": "BLOCKED"}
    print(f"\nExecution plan - mode: {ctx.mode} (dry run: nothing is executed or written)")
    print(f"  inputs : {ctx.paths.raw_root}")
    print(f"  outputs: {ctx.paths.processed_root}  |  {ctx.paths.results_root}\n")
    for p in planned:
        spec = STAGES[p.name]
        print(f"  {p.name:<11} {labels[p.action]:<16} {p.reason}")
        for k in spec.required_datasets + spec.optional_datasets:
            if k in ctx.config.dataset_keys(ctx.mode):
                print(f"      - {ctx.config.dataset(ctx.mode, k).describe()}")
    print()


def run_pipeline(
    mode: str,
    steps: str | None = None,
    run_all: bool = False,
    dry_run: bool = False,
    force: bool = False,
    root: Path | None = None,
    log_level: str = "INFO",
) -> int:
    """Plan and execute stages. Returns a process exit code (0 = success)."""
    cfg = load_config(root)
    stages = resolve_stages(steps, run_all)
    ctx = _make_context(cfg, mode, stages, force, dry_run)

    if mode == "demo":
        from bess_catalonia.demo import ensure_sample_data, sample_data_present

        if dry_run:
            if not sample_data_present(ctx.paths.raw_root):
                print("Demo mode: synthetic sample data would first be generated in",
                      ctx.paths.raw_root)
                ctx.assume_available = True
        else:
            setup_logging(cfg, ctx.run_id, log_level)
            if ensure_sample_data(ctx.paths.raw_root):
                logger.info("Demo mode: generated SYNTHETIC sample data in %s", ctx.paths.raw_root)

    planned = plan(ctx, stages, explicit=not run_all)
    if dry_run:
        print_plan(ctx, planned)
        return 1 if any(p.action == "blocked" for p in planned) else 0

    log_path = setup_logging(cfg, ctx.run_id, log_level)
    logger.info("Run %s - mode %s - stages %s", ctx.run_id, mode, ",".join(stages))
    if mode == "demo":
        logger.warning("DEMO MODE: all data and results are SYNTHETIC (results/demo/)")
    ok = execute(ctx, planned)
    ctx.record.finish("success" if ok else "failed")
    rec_path = ctx.record.write(cfg.logs_dir)
    logger.info("Run record: %s | log: %s", rec_path.relative_to(cfg.root),
                log_path.relative_to(cfg.root))
    logger.info("Status: %s", ctx.record.status.upper())
    return 0 if ok else 1


VALIDATABLE = ("grid", "demand", "congestion", "renewables", "gis")


def validate_inputs(mode: str, root: Path | None = None, log_level: str = "INFO") -> int:
    """Load and validate every available input dataset without writing processed outputs.
    Quality reports go to <results_root>/quality/. Returns exit code 1 on any error."""
    cfg = load_config(root)
    ctx = _make_context(cfg, mode, list(VALIDATABLE), force=False, dry_run=False)
    setup_logging(cfg, ctx.run_id, log_level)
    if mode == "demo":
        from bess_catalonia.demo import ensure_sample_data

        ensure_sample_data(ctx.paths.raw_root)
    optional_in_all = set(cfg.project.get("optional_stages_in_all") or [])
    ok = True
    print(f"\nValidating {mode} inputs in {ctx.paths.raw_root}\n")
    for name in VALIDATABLE:
        spec = STAGES[name]
        keys = spec.required_datasets + spec.optional_datasets
        if not any(ctx.available(k) for k in spec.required_datasets or keys):
            level = "OPTIONAL - not yet available" if name in optional_in_all else "MISSING"
            if name not in optional_in_all:
                ok = False
            print(f"  {name:<11} {level}")
            for k in keys:
                print(f"      - {cfg.dataset(mode, k).describe()}")
            continue
        module = importlib.import_module(spec.module)
        try:
            reports = module.validate(module.load(ctx), ctx)
        except (MissingDataError, ValueError, KeyError) as exc:
            print(f"  {name:<11} ERROR  {exc}")
            ok = False
            continue
        for rep in reports:
            ctx.write_report(rep)
            n_err = sum(i.level == "error" for i in rep.issues)
            n_warn = sum(i.level == "warning" for i in rep.issues)
            state = "ERRORS" if n_err else ("OK (warnings)" if n_warn else "OK")
            print(f"  {name:<11} {state:<14} {rep.dataset}: {n_err} error(s), "
                  f"{n_warn} warning(s)")
            ok = ok and not n_err
    drift = compare_manifest(cfg, mode)
    if drift:
        print("\nData manifest:")
        for d in drift:
            print("  -", d)
    print(f"\nQuality reports: {ctx.paths.quality_dir}")
    return 0 if ok else 1
