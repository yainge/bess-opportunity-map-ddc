"""Configuration loading and path resolution.

All configuration lives in ``config/*.yaml``. Paths in the configuration are relative to the
project root, which is the directory containing ``pyproject.toml`` (override with the
``BESS_PROJECT_ROOT`` environment variable, used by the tests).
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

MODES = ("demo", "real")
CONFIG_FILES = ("project", "datasets", "spatial", "scoring", "ml")


class ConfigError(ValueError):
    """Raised when configuration files are missing or inconsistent."""


def find_project_root(start: Path | None = None) -> Path:
    env = os.environ.get("BESS_PROJECT_ROOT")
    if env:
        return Path(env).resolve()
    here = (start or Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "pyproject.toml").exists() and (candidate / "config").is_dir():
            return candidate
    # Fall back to the source checkout this package was imported from.
    pkg_root = Path(__file__).resolve().parents[2]
    if (pkg_root / "config").is_dir():
        return pkg_root
    raise ConfigError("Could not locate the project root (directory with pyproject.toml + config/)")


@dataclass(frozen=True)
class ModePaths:
    mode: str
    raw_root: Path
    processed_root: Path
    results_root: Path

    @property
    def quality_dir(self) -> Path:
        return self.results_root / "quality"

    @property
    def maps_dir(self) -> Path:
        return self.results_root / "maps"


@dataclass(frozen=True)
class DatasetSpec:
    """One configured input dataset for one mode."""

    key: str
    mode: str
    domain: str
    owner: str
    path: Path | None
    format: str
    layer: str | None = None
    source_crs: str | None = None
    columns: dict[str, str] = field(default_factory=dict)
    read_options: dict[str, Any] = field(default_factory=dict)
    number_format: dict[str, str] = field(default_factory=dict)
    units: dict[str, str] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def configured(self) -> bool:
        return self.path is not None

    @property
    def available(self) -> bool:
        return self.path is not None and self.path.exists()

    def describe(self) -> str:
        if self.path is None:
            return f"{self.key}: not configured (path: null in config/datasets.yaml [{self.mode}])"
        state = "found" if self.path.exists() else "MISSING"
        return f"{self.key}: {self.path} ({state})"


@dataclass
class Config:
    root: Path
    project: dict[str, Any]
    datasets: dict[str, Any]
    spatial: dict[str, Any]
    scoring: dict[str, Any]
    ml: dict[str, Any]

    # -- paths --------------------------------------------------------------------------
    def mode_paths(self, mode: str) -> ModePaths:
        if mode not in MODES:
            raise ConfigError(f"Unknown mode {mode!r}; expected one of {MODES}")
        m = self.project["modes"][mode]
        return ModePaths(
            mode=mode,
            raw_root=self.root / m["raw_root"],
            processed_root=self.root / m["processed_root"],
            results_root=self.root / m["results_root"],
        )

    @property
    def logs_dir(self) -> Path:
        return self.root / self.project.get("logs_dir", "logs")

    @property
    def manifests_dir(self) -> Path:
        return self.root / self.project.get("manifests_dir", "data/manifests")

    @property
    def analysis_crs(self) -> str:
        return self.project["project"]["analysis_crs"]

    @property
    def geographic_crs(self) -> str:
        return self.project["project"]["geographic_crs"]

    # -- datasets -----------------------------------------------------------------------
    def dataset_keys(self, mode: str) -> list[str]:
        return list((self.datasets.get(mode) or {}).keys())

    def dataset(self, mode: str, key: str) -> DatasetSpec:
        entries = self.datasets.get(mode) or {}
        if key not in entries:
            raise ConfigError(f"Dataset {key!r} is not defined for mode {mode!r}")
        raw = entries[key] or {}
        rel = raw.get("path")
        path = self.mode_paths(mode).raw_root / rel if rel else None
        return DatasetSpec(
            key=key,
            mode=mode,
            domain=raw.get("domain", ""),
            owner=raw.get("owner", ""),
            path=path,
            format=str(raw.get("format", "csv")).lower(),
            layer=raw.get("layer"),
            source_crs=raw.get("source_crs"),
            columns=dict(raw.get("columns") or {}),
            read_options=dict(raw.get("read_options") or {}),
            number_format=dict(raw.get("number_format") or {}),
            units=dict(raw.get("units") or {}),
            options=dict(raw.get("options") or {}),
            metadata=dict(raw.get("metadata") or {}),
        )

    # -- hashing ------------------------------------------------------------------------
    def section_hash(self, *parts: Any) -> str:
        payload = json.dumps(parts, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def as_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in CONFIG_FILES}


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Missing configuration file: {path}")
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a YAML mapping")
    return data


def load_config(root: Path | None = None) -> Config:
    root = (root or find_project_root()).resolve()
    parts = {name: _read_yaml(root / "config" / f"{name}.yaml") for name in CONFIG_FILES}
    cfg = Config(root=root, **parts)
    validate_config(cfg)
    return cfg


def validate_config(cfg: Config) -> None:
    """Cross-file consistency checks. Raises ConfigError with all problems found."""
    problems: list[str] = []
    for mode in MODES:
        if mode not in (cfg.project.get("modes") or {}):
            problems.append(f"project.yaml: modes.{mode} missing")
    for key in ("analysis_crs", "geographic_crs", "region_bbox_wgs84"):
        if key not in (cfg.project.get("project") or {}):
            problems.append(f"project.yaml: project.{key} missing")
    if any(float(b) <= 0 for b in cfg.spatial.get("buffers_km", [])):
        problems.append("spatial.yaml: buffers_km must be positive")

    indicators = cfg.scoring.get("indicators") or {}
    for name, spec in indicators.items():
        if spec.get("direction") not in ("higher_better", "lower_better"):
            problems.append(f"scoring.yaml: indicator {name}: invalid direction")
        if spec.get("normalization") not in ("minmax", "percentile"):
            problems.append(f"scoring.yaml: indicator {name}: invalid normalization")
        if spec.get("missing") not in ("reweight", "worst", "exclude"):
            problems.append(f"scoring.yaml: indicator {name}: invalid missing policy")
    for scen, sspec in (cfg.scoring.get("scenarios") or {}).items():
        weights = sspec.get("weights") or {}
        unknown = set(weights) - set(indicators)
        if unknown:
            problems.append(f"scoring.yaml: scenario {scen} uses undefined indicators {unknown}")
        if any(w < 0 for w in weights.values()):
            problems.append(f"scoring.yaml: scenario {scen} has negative weights")
        if weights and abs(sum(weights.values()) - 1.0) > 1e-6:
            problems.append(f"scoring.yaml: scenario {scen} weights must sum to 1")

    for mode in MODES:
        for key, raw in (cfg.datasets.get(mode) or {}).items():
            if not isinstance(raw, dict) or "domain" not in raw:
                problems.append(f"datasets.yaml: {mode}.{key} needs at least 'domain'")
    if problems:
        raise ConfigError("Invalid configuration:\n  - " + "\n  - ".join(problems))
