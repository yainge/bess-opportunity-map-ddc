"""End-to-end pipeline behaviour on throw-away project roots."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
import yaml
from tests_helpers import enable_real_grid

from bess_catalonia.pipeline import run_pipeline

pytestmark = pytest.mark.slow


def test_full_demo_outputs(demo_project):
    res = demo_project / "results" / "demo"
    layers = set(gpd.list_layers(res / "bess_master.gpkg")["name"])
    assert {"nodes_integrated", "scores_renewable_absorption", "scores_connection_readiness",
            "scores_load_grid_support", "suitable_land_net", "renewable_installations"} <= layers
    nodes = gpd.read_file(res / "bess_master.gpkg", layer="nodes_integrated")
    assert nodes.crs.to_epsg() == 25831 and nodes["node_id"].is_unique
    for m in ("grid_nodes_overview", "score_renewable_absorption"):
        assert (res / "maps" / f"{m}.png").stat().st_size > 10_000
    assert (res / "quality" / "quality_congestion_node_matching.md").exists()
    assert "SYNTHETIC" in (res / "summary.md").read_text()
    # synthetic results never leak into real-data locations
    assert not (demo_project / "data" / "processed").exists() or not any(
        (demo_project / "data" / "processed").iterdir())
    assert not (demo_project / "results" / "real").exists()


def test_full_demo_integration_content(demo_project):
    integ = demo_project / "results/demo/processed/integrate"
    df = pd.read_csv(integ / "nodes_integrated.csv")
    report = json.loads((demo_project / "results/demo/quality/quality_integrated_nodes.json")
                        .read_text())
    assert report["metrics"]["milestone"].startswith("M3")
    assert df["erni_12m_gwh"].notna().sum() == 11  # 11 of 14 source nodes matched
    assert df["erni_12m_gwh"].isna().any()  # unmatched nodes stay null, not zero
    for col in ("renewable_mw_10km", "nearby_demand_mwh_10km", "suitable_land_ha_5km",
                "distance_to_major_road_km", "protected_area_conflict"):
        assert df[col].notna().all(), col
    matching = pd.read_csv(demo_project / "results/demo/processed/congestion/node_matching.csv")
    assert set(matching["match_status"]) == {"matched", "ambiguous", "unmatched"}


def test_run_record_and_provenance(demo_project):
    records = sorted((demo_project / "logs" / "runs").glob("*.json"))
    rec = json.loads(records[0].read_text())
    assert rec["status"] == "success" and rec["mode"] == "demo"
    assert rec["input_checksums"]["grid_nodes"].startswith("sha256:")
    assert {"run_id", "start_time", "end_time", "configuration", "outputs", "record_counts",
            "warnings", "errors"} <= set(rec)
    manifest = json.loads((demo_project / "results/demo/processed/grid/_stage.json").read_text())
    assert manifest["fingerprint"] and manifest["run_id"] == rec["run_id"]


def test_rerun_is_up_to_date_and_force_is_deterministic(tmp_path, demo_project):
    root = tmp_path / "copy"
    shutil.copytree(demo_project, root)
    integ = root / "results/demo/processed/integrate/nodes_integrated.csv"
    scores = root / "results/demo/processed/score/scores_long.csv"
    before = (integ.read_bytes(), scores.read_bytes())
    mtime = integ.stat().st_mtime_ns
    assert run_pipeline("demo", run_all=True, root=root, log_level="WARNING") == 0
    assert integ.stat().st_mtime_ns == mtime  # up to date -> not rewritten
    assert run_pipeline("demo", run_all=True, force=True, root=root, log_level="WARNING") == 0
    assert integ.stat().st_mtime_ns != mtime
    assert (integ.read_bytes(), scores.read_bytes()) == before  # identical results


def test_config_change_triggers_rerun(tmp_path, demo_project):
    root = tmp_path / "copy"
    shutil.copytree(demo_project, root)
    path = root / "config" / "spatial.yaml"
    sp = yaml.safe_load(path.read_text())
    sp["buffers_km"] = [5, 10]
    path.write_text(yaml.safe_dump(sp))
    assert run_pipeline("demo", steps="gis", root=root, log_level="WARNING") == 0
    cols = pd.read_csv(root / "results/demo/processed/gis/gis_node_metrics.csv").columns
    assert "suitable_land_ha_10km" in cols and "suitable_land_ha_20km" not in cols


def test_partial_integration(project):
    assert run_pipeline("demo", steps="grid,integrate", root=project,
                        log_level="WARNING") == 0
    rep = json.loads((project / "results/demo/quality/quality_integrated_nodes.json").read_text())
    assert rep["metrics"]["milestone"].startswith("M0")
    assert run_pipeline("demo", steps="congestion,integrate", root=project,
                        log_level="WARNING") == 0  # grid output reused from the first run
    rep = json.loads((project / "results/demo/quality/quality_integrated_nodes.json").read_text())
    assert rep["metrics"]["milestone"].startswith("M1")


def test_stage_without_upstream_output_is_blocked(project):
    assert run_pipeline("demo", steps="congestion", root=project, log_level="ERROR") == 1


def test_real_mode_never_uses_synthetic_data(project):
    assert run_pipeline("real", run_all=True, root=project, log_level="ERROR") == 1
    assert not (project / "data" / "sample").exists()
    assert not (project / "data" / "processed" / "grid" / "grid_nodes.csv").exists()
    assert run_pipeline("real", steps="demand", root=project, log_level="ERROR") == 1


def test_real_mode_optional_stages_skipped(project):
    enable_real_grid(project)
    assert run_pipeline("real", run_all=True, root=project, log_level="ERROR") == 0
    rec = json.loads(sorted((project / "logs/runs").glob("*.json"))[-1].read_text())
    status = {s["stage"]: s["status"] for s in rec["stage_results"]}
    assert status == {"grid": "ran", "demand": "skipped", "congestion": "skipped",
                      "renewables": "skipped", "gis": "skipped", "integrate": "ran",
                      "score": "ran", "ml": "skipped", "export": "ran"}
    assert (project / "results" / "real" / "bess_master.gpkg").exists()
    assert not (project / "results" / "demo").exists()


def test_dry_run_writes_nothing(project):
    assert run_pipeline("demo", run_all=True, dry_run=True, root=project) == 0
    assert not (project / "results").exists() and not (project / "data").exists()


def _cli(project, *args):
    src = str(Path(__file__).resolve().parents[2] / "src")
    env = {**os.environ, "BESS_PROJECT_ROOT": str(project), "PYTHONPATH": src}
    return subprocess.run([sys.executable, "-m", "bess_catalonia", *args], env=env,
                          capture_output=True, text=True)


def test_cli_commands(project):
    r = _cli(project, "--help")
    assert r.returncode == 0 and "grid, demand, congestion" in r.stdout
    assert _cli(project, "--all").returncode == 2  # --mode required
    bad = _cli(project, "--mode", "demo", "--steps", "grid,banana")
    assert bad.returncode == 2 and "Unknown stage" in bad.stderr
    plan = _cli(project, "--mode", "demo", "--steps", "grid", "--dry-run")
    assert plan.returncode == 0 and "WOULD RUN" in plan.stdout
    assert _cli(project, "--mode", "demo", "--validate").returncode == 0
    assert _cli(project, "--mode", "demo", "--record-manifest").returncode == 0
    manifest = json.loads((project / "data/manifests/demo_datasets.json").read_text())
    assert manifest["datasets"]["grid_nodes"]["checksum"].startswith("sha256:")
    assert _cli(project, "--mode", "real", "--validate").returncode == 1  # grid missing
