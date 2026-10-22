import pandas as pd
import pytest
import yaml

from bess_catalonia.config import ConfigError, load_config
from bess_catalonia.units import UnitError, convert_column, m2_to_ha, mwh_to_gwh, to_mw, to_mwh


def test_config_loads_and_separates_modes(cfg):
    demo, real = cfg.mode_paths("demo"), cfg.mode_paths("real")
    assert demo.results_root != real.results_root
    assert demo.processed_root != real.processed_root
    assert demo.raw_root.name == "sample" and real.raw_root.name == "raw"
    assert cfg.analysis_crs == "EPSG:25831"


def test_dataset_spec_resolution(cfg):
    spec = cfg.dataset("demo", "grid_nodes")
    assert spec.path == cfg.root / "data/sample/grid/grid_nodes_synthetic.csv"
    assert spec.columns["kv"] == "voltage_kv"
    real = cfg.dataset("real", "grid_nodes")
    assert real.path is not None
    assert real.columns["Node"] == "source_node_id"


def test_unknown_mode_rejected(cfg):
    with pytest.raises(ConfigError):
        cfg.mode_paths("production")


def _edit_scoring(project, fn):
    path = project / "config" / "scoring.yaml"
    data = yaml.safe_load(path.read_text())
    fn(data)
    path.write_text(yaml.safe_dump(data))


def test_weights_must_sum_to_one(project):
    _edit_scoring(project, lambda d: d["scenarios"]["renewable_absorption"]["weights"].update(
        erni_12m_gwh=0.9))
    with pytest.raises(ConfigError, match="sum to 1"):
        load_config(project)


def test_scenario_cannot_use_undefined_indicator(project):
    _edit_scoring(project, lambda d: d["scenarios"]["connection_readiness"]["weights"].update(
        {"made_up": 0.0}))
    with pytest.raises(ConfigError, match="undefined indicators"):
        load_config(project)


def test_unit_conversions():
    s = pd.Series([1000.0, None])
    assert to_mw(s, "kW").iloc[0] == 1.0
    assert to_mwh(s, "kWh").iloc[0] == 1.0
    assert pd.isna(to_mw(s, "kW").iloc[1])  # null stays null
    assert to_mwh(pd.Series([2.0]), "GWh").iloc[0] == 2000.0
    assert mwh_to_gwh(pd.Series([1500.0])).iloc[0] == 1.5
    assert m2_to_ha(pd.Series([10_000.0])).iloc[0] == 1.0
    with pytest.raises(UnitError):
        to_mw(s, "horsepower")


def test_convert_column_uses_suffix():
    df = pd.DataFrame({"capacity_mw": [500.0], "consumption_mwh": [3000.0]})
    convert_column(df, "capacity_mw", "kW")
    convert_column(df, "consumption_mwh", "kWh")
    assert df.loc[0, "capacity_mw"] == 0.5 and df.loc[0, "consumption_mwh"] == 3.0
    with pytest.raises(UnitError):
        convert_column(pd.DataFrame({"voltage_kv": [1.0]}), "voltage_kv", "V")
