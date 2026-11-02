"""Headroom proxy, node matching, demand summaries."""

from pathlib import Path

import numpy as np
import pandas as pd

from bess_catalonia.config import DatasetSpec
from bess_catalonia.congestion.matching import match_nodes, normalise_name
from bess_catalonia.demand.processing import summarise
from bess_catalonia.grid.processing import headroom_proxy, slug
from bess_catalonia.integration.processing import normalise_municipality_code
from bess_catalonia.io import load_standardized

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_headroom_proxy_rules():
    df = pd.DataFrame({
        "generation_available_mw": [10.0, 50.0, np.nan, 30.0],
        "demand_available_mw": [20.0, 40.0, 5.0, 30.0],
        "generation_capacity_date": ["2026-08", "2026-08", "2026-08", "2026-08"],
        "demand_capacity_date": ["2026-08", "2026-08", "2026-08", "2026-05"],
    })
    proxy, note = headroom_proxy(df, require_same_date=True)
    assert proxy.iloc[0] == 10.0 and proxy.iloc[1] == 40.0
    assert pd.isna(proxy.iloc[2]) and "missing" in note.iloc[2]
    assert pd.isna(proxy.iloc[3]) and "dates differ" in note.iloc[3]
    proxy2, _ = headroom_proxy(df, require_same_date=False)
    assert proxy2.iloc[3] == 30.0


def test_slug():
    assert slug("se Sant Just-2") == "SE_SANT_JUST_2"


def test_normalise_name():
    assert normalise_name("SE Màple  (EDIS)", ["SE"]) == "MAPLE EDIS"
    assert normalise_name(None) == ""


NODES = pd.DataFrame({
    "node_id": ["REE-T1", "EDIS-D1", "EDIS-D2", "EDIS-D3"],
    "source_node_id": ["T1", "D1", "D2", "D3"],
    "node_name": ["Alpha", "Cedar", "Cedar", "Bétula"],
})


def test_matching_rules_and_order():
    sources = pd.DataFrame({
        "source_node_id": ["X1", "D3", "X3", "X4", "X5", "X6"],
        "source_node_name": ["SET ALPHA 400", "whatever", "CEDAR", "NOWHERE", "BETULA",
                             "ALPHA"],
    })
    xwalk = pd.DataFrame({"congestion_source_node_id": ["X1", "X6"],
                          "grid_source_node_id": ["T1", "MISSING"]})
    m = match_nodes(sources, NODES, xwalk, strip_tokens=["SET"]).set_index("source_node_id")
    assert m.loc["X1", ["node_id", "match_method"]].tolist() == ["REE-T1", "crosswalk"]
    assert m.loc["D3", ["node_id", "match_method"]].tolist() == ["EDIS-D3", "source_id"]
    assert m.loc["X5", ["node_id", "match_reliability"]].tolist() == ["EDIS-D3", "medium"]
    assert m.loc["X3", "match_status"] == "ambiguous"  # never silently merged
    assert pd.isna(m.loc["X3", "node_id"]) and m.loc["X3", "candidates"] == "EDIS-D1;EDIS-D2"
    assert m.loc["X4", "match_status"] == "unmatched"
    # broken crosswalk entry is reported and falls through to the name rule
    assert bool(m.loc["X6", "crosswalk_target_missing"])
    assert m.loc["X6", "match_method"] == "name"


def test_name_matching_can_be_disabled():
    sources = pd.DataFrame({"source_node_name": ["Alpha"]})
    m = match_nodes(sources, NODES, allow_name_match=False)
    assert m.loc[0, "match_status"] == "unmatched"
    assert m.loc[0, "congestion_source_key"] == "name:Alpha"


def test_real_demand_format_parsing_and_summary():
    spec = DatasetSpec(
        key="demand_municipal", mode="real", domain="demand", owner="Fernando",
        path=FIXTURES / "icaen_demand_format_sample.csv", format="csv",
        read_options={"dtype": str}, number_format={"thousands": ".", "decimal": ","},
        columns={"Any": "year", "CDMUN": "municipality_code", "Municipi": "municipality_name",
                 "Codi_Sector": "sector_code", "Consum [kWh]": "consumption_mwh",
                 "Observacions": "source_note"},
        units={"consumption_mwh": "kWh"},
    )
    loaded = load_standardized(spec, "demand", "demand_input")
    df = loaded.data
    assert not loaded.report.has_errors
    assert df["consumption_mwh"].iloc[1] == 66_604.371  # kWh -> MWh, Catalan thousands
    assert pd.isna(df["consumption_mwh"].iloc[2])  # suppressed -> null, not zero
    df["municipality_code"] = df["municipality_code"].str.zfill(5)
    s = summarise(df, ["3"], "secret estad").set_index("municipality_code")
    a = s.loc["08001"]
    assert a["year"] == 2024 and a["n_suppressed_sectors"] == 1 and a["total_is_lower_bound"]
    assert a["industrial_mwh"] == 66_604.371  # 2023 value not mixed in
    assert not s.loc["25002", "total_is_lower_bound"]


def test_normalise_municipality_code_handles_icgc_and_ine_formats():
    codes = pd.Series(["080018", "08001", "8001", "250019", "8001.0"])
    assert normalise_municipality_code(codes).tolist() == [
        "08001", "08001", "08001", "25001", "08001"]
