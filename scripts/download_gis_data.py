#!/usr/bin/env python3
"""
Download and prepare official GIS datasets for the BESS Opportunity Map (Catalonia).

Sources
-------
1. Municipal boundaries  – ICGC WFS (divisions-administratives)
2. Protected areas       – Generalitat WFS (ESPAIS_NATURALS): PEIN + Xarxa Natura 2000
3. Flood zones T100      – ACA WFS (AIGUA)
4. Urban zoning (MUC)    – Generalitat WFS (PLANEJAMENT)
5. Roads                 – Geofabrik OpenStreetMap Catalonia shapefile
6. Land cover 2024       – ICGC MCSC v1.0 2024 GeoPackage (810 MB zip)

Usage
-----
    uv run scripts/download_gis_data.py                  # all datasets
    uv run scripts/download_gis_data.py --datasets roads municipalities
    uv run scripts/download_gis_data.py --dry-run        # show what would run
    uv run scripts/download_gis_data.py --inspect-only   # download + inspect, skip processing

Output
------
  data/raw/gis/<source>/        raw downloads (preserved as-is)
  data/processed/gis/           standardised GeoPackages (EPSG:25831)
    municipalities.gpkg         layer: municipalities
    protected_areas.gpkg        layer: protected_areas
    flood_zones.gpkg            layer: flood_zones
    zoning.gpkg                 layer: zoning
    roads.gpkg                  layer: roads
    land_cover.gpkg             layer: land_cover
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import time
import zipfile
from datetime import date
from pathlib import Path
from typing import Optional

import geopandas as gpd
import pandas as pd
import pyogrio
import requests
from shapely import make_valid
from shapely.geometry import box

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
RAW_GIS = ROOT / "data" / "raw" / "gis"
# Pipeline reads inputs from data/raw/ (see config.py). The standardised GeoPackages
# produced here are the pipeline inputs, so they live in data/raw/gis/ directly.
PROC_GIS = RAW_GIS
ANALYSIS_CRS = "EPSG:25831"
GEO_CRS = "EPSG:4326"
# Generous Catalonia bbox [min_lon, min_lat, max_lon, max_lat] (WGS84)
BBOX_WGS84 = (0.10, 40.45, 3.40, 42.95)
TODAY = date.today().isoformat()
STREAM_CHUNK = 1024 * 256  # 256 KB


# ─────────────────────────────────────────────────────────────────────────────
# Provenance
# ─────────────────────────────────────────────────────────────────────────────
def save_provenance(dest_dir: Path, name: str, info: dict) -> None:
    prov_file = dest_dir / "_provenance.json"
    records: dict = {}
    if prov_file.exists():
        try:
            records = json.loads(prov_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    records[name] = {**info, "retrieval_date": TODAY}
    prov_file.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# HTTP Download
# ─────────────────────────────────────────────────────────────────────────────
def file_sha256(path: Path, n_bytes: int = 65536) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(n_bytes), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def download_file(url: str, dest: Path, desc: str = "", retries: int = 3) -> Path:
    """Stream-download *url* to *dest*. Skip (return early) if already present."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        size_mb = dest.stat().st_size / (1024 ** 2)
        print(f"  [skip] {desc or dest.name} already on disk ({size_mb:.1f} MB)")
        return dest

    headers = {"User-Agent": "Mozilla/5.0 bess-opportunity-map/0.1 research use"}
    for attempt in range(1, retries + 1):
        try:
            print(f"  → {desc or url[:80]} (attempt {attempt}/{retries})")
            tmp = dest.with_suffix(dest.suffix + ".tmp")
            with requests.get(url, stream=True, timeout=600, headers=headers) as r:
                r.raise_for_status()
                total = int(r.headers.get("content-length", 0))
                downloaded = 0
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(STREAM_CHUNK):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total:
                                pct = downloaded * 100.0 / total
                                mb = downloaded / (1024 ** 2)
                                print(
                                    f"\r    {mb:.1f} / {total/(1024**2):.1f} MB  "
                                    f"({pct:.0f}%)",
                                    end="",
                                    flush=True,
                                )
            print()
            tmp.rename(dest)
            print(f"  ✓ saved {dest.name} ({downloaded/(1024**2):.1f} MB)")
            return dest
        except Exception as exc:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
            print(f"  ✗ attempt {attempt} failed: {exc}")
            if attempt < retries:
                time.sleep(2 ** attempt)

    raise RuntimeError(f"Failed to download after {retries} attempts: {url}")


# ─────────────────────────────────────────────────────────────────────────────
# WFS helpers
# ─────────────────────────────────────────────────────────────────────────────
_WFS_HEADERS = {
    # Browser-like headers required by some Catalan government WFS services
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, */*",
    "Accept-Language": "ca,es;q=0.9,en;q=0.8",
}


def _wfs_count(base_url: str, typename: str) -> Optional[int]:
    """Return feature count from WFS hits request (None if unsupported)."""
    import re
    try:
        params = (
            f"SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature"
            f"&TYPENAMES={typename}&RESULTTYPE=hits"
        )
        r = requests.get(f"{base_url}?{params}", timeout=30, headers=_WFS_HEADERS)
        m = re.search(r'numberMatched="(\d+)"', r.text)
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return None


def _probe_json_format(base_url: str) -> str:
    """Return the correct JSON outputFormat string for this WFS server.

    ICGC uses 'GEOJSON'; OGC-standard servers use 'application/json'.
    """
    try:
        r = requests.get(
            f"{base_url}?SERVICE=WFS&REQUEST=GetCapabilities",
            timeout=20,
            headers=_WFS_HEADERS,
        )
        text = r.text
        if "GEOJSON" in text and "application/json" not in text:
            return "GEOJSON"
        if "application/json" in text:
            return "application/json"
    except Exception:
        pass
    return "application/json"


def read_wfs_layer(
    base_url: str,
    typename: str,
    label: str = "",
    max_features: int = 100_000,
    bbox_wgs84: Optional[tuple] = None,
    output_format: Optional[str] = None,
) -> gpd.GeoDataFrame:
    """Download a WFS 2.0 layer as GeoJSON via GetFeature, via requests.

    Uses browser-like headers to avoid 403 on Catalan government services.
    Downloads to a tempfile and reads with GeoPandas/pyogrio.
    """
    label = label or typename

    n = _wfs_count(base_url, typename)
    if n is not None:
        print(f"  WFS count: {n:,} features")
        if n > max_features:
            print(
                f"  WARNING: layer has {n:,} features (max_features={max_features:,}); "
                "truncated - use bbox filter or increase max_features."
            )

    fmt = output_format or _probe_json_format(base_url)

    params: dict[str, str] = {
        "SERVICE": "WFS",
        "VERSION": "2.0.0",
        "REQUEST": "GetFeature",
        "TYPENAMES": typename,
        "outputFormat": fmt,
        "srsName": GEO_CRS,
        "count": str(max_features),
    }
    if bbox_wgs84:
        params["BBOX"] = ",".join(str(x) for x in bbox_wgs84) + f",{GEO_CRS}"

    url = base_url + "?" + "&".join(f"{k}={v}" for k, v in params.items())
    print(f"  WFS → {label}  (format={fmt})")
    print(f"    {url[:120]}...")

    r = requests.get(url, timeout=300, headers=_WFS_HEADERS)
    if r.status_code != 200:
        raise RuntimeError(
            f"WFS returned HTTP {r.status_code} for {typename}: {r.text[:200]}"
        )
    if "<ExceptionReport" in r.text[:500]:
        raise RuntimeError(f"WFS server exception for {typename}:\n{r.text[:400]}")

    # Write to temp file and read with GeoPandas (pyogrio backend)
    suffix = ".json" if fmt in ("application/json", "GEOJSON") else ".gml"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = Path(tmp.name)
        tmp_path.write_bytes(r.content)

    try:
        gdf = gpd.read_file(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    print(f"  ✓ {len(gdf):,} features loaded, CRS={gdf.crs}")
    return gdf


# ─────────────────────────────────────────────────────────────────────────────
# Geometry helpers
# ─────────────────────────────────────────────────────────────────────────────
def clip_to_catalonia(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Keep only features that intersect the Catalonia bounding box (WGS84)."""
    if gdf.crs is None:
        raise ValueError("Cannot clip: GeoDataFrame has no CRS")
    working = gdf.to_crs(GEO_CRS) if gdf.crs.to_epsg() != 4326 else gdf
    mask = working.geometry.intersects(box(*BBOX_WGS84))
    result = gdf[mask].copy()
    print(f"  clip: {len(gdf):,} → {len(result):,} features in Catalonia bbox")
    return result


def reproject_and_fix(gdf: gpd.GeoDataFrame, crs: str = ANALYSIS_CRS) -> gpd.GeoDataFrame:
    """Reproject to *crs* and make_valid any invalid geometries."""
    if gdf.crs is None:
        raise ValueError("GeoDataFrame has no CRS")
    if gdf.crs.to_string() != gpd.GeoSeries(crs=crs).crs.to_string():
        gdf = gdf.to_crs(crs)
    invalid = ~gdf.geometry.is_valid
    if invalid.any():
        n = int(invalid.sum())
        print(f"  make_valid: fixing {n} invalid geometri{'y' if n==1 else 'es'}")
        gdf = gdf.copy()
        gdf.loc[invalid, "geometry"] = gdf.loc[invalid, "geometry"].apply(make_valid)
    return gdf


def save_gpkg(gdf: gpd.GeoDataFrame, path: Path, layer: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(path, driver="GPKG", layer=layer)
    n = len(gdf)
    mb = path.stat().st_size / (1024 ** 2)
    print(f"  saved {path.name} (layer={layer!r}, {n:,} features, {mb:.1f} MB)")


# ─────────────────────────────────────────────────────────────────────────────
# 1. Municipal boundaries
# ─────────────────────────────────────────────────────────────────────────────
def run_municipalities(dry_run: bool = False, inspect_only: bool = False) -> None:
    print("\n" + "=" * 60)
    print("[1] Municipal Boundaries  (ICGC WFS)")
    print("=" * 60)

    raw_dir = RAW_GIS / "icgc_municipis"
    raw_gpkg = raw_dir / "municipis_5000_raw.gpkg"
    proc_gpkg = PROC_GIS / "municipalities.gpkg"

    if dry_run:
        print("  DRY RUN: would download ICGC WFS → municipis_5000_raw.gpkg")
        return

    raw_dir.mkdir(parents=True, exist_ok=True)

    if not raw_gpkg.exists():
        gdf = read_wfs_layer(
            "https://geoserveis.icgc.cat/servei/catalunya/divisions-administratives/wfs",
            "divisions_administratives_wfs:divisions_administratives_municipis_5000",
            label="ICGC municipalities 1:5000",
        )
        gdf.to_file(raw_gpkg, driver="GPKG", layer="municipalities_raw")
    else:
        print(f"  [skip] raw data: {raw_gpkg.name}")
        gdf = gpd.read_file(raw_gpkg, layer="municipalities_raw")

    print(f"  columns: {list(gdf.columns)}")
    if "CODIMUNI" in gdf.columns:
        print(f"  CODIMUNI sample: {gdf['CODIMUNI'].head(5).tolist()}")

    if inspect_only:
        print("  [inspect-only] skipping processed output")
        return

    # Standardise: keep CODIMUNI (municipality code), NOMMUNI (name)
    keep_cols = [c for c in ["CODIMUNI", "NOMMUNI", "geometry"] if c in gdf.columns]
    out = gdf[keep_cols].copy()
    rename = {"CODIMUNI": "municipality_code", "NOMMUNI": "municipality_name"}
    out = out.rename(columns={k: v for k, v in rename.items() if k in out.columns})
    out = reproject_and_fix(out)

    save_gpkg(out, proc_gpkg, "municipalities")
    save_provenance(raw_dir, "municipalities", {
        "source": "ICGC - Divisions Administratives WFS",
        "source_url": "https://geoserveis.icgc.cat/servei/catalunya/divisions-administratives/wfs",
        "wfs_layer": "divisions_administratives_wfs:divisions_administratives_municipis_5000",
        "scale": "1:5000",
        "crs_processed": ANALYSIS_CRS,
        "features": len(out),
        "license": "Creative Commons Attribution 4.0 ICGC",
    })
    print(f"  ✓ municipalities done: {len(out):,} features")


# ─────────────────────────────────────────────────────────────────────────────
# 2. Protected areas (PEIN + Natura 2000)
# ─────────────────────────────────────────────────────────────────────────────
def run_protected_areas(dry_run: bool = False, inspect_only: bool = False) -> None:
    print("\n" + "=" * 60)
    print("[2] Protected Areas  (Generalitat WFS – PEIN + Natura 2000)")
    print("=" * 60)

    raw_dir = RAW_GIS / "gencat_espais_naturals"
    raw_dir.mkdir(parents=True, exist_ok=True)
    proc_gpkg = PROC_GIS / "protected_areas.gpkg"
    BASE_WFS = "https://sig.gencat.cat/ows/ESPAIS_NATURALS/wfs"

    if dry_run:
        print("  DRY RUN: would download ESPAIS_NATURALS WFS layers (PEIN + XARNAT_2000)")
        return

    layers_spec = {
        "pein": "ESPAIS_NATURALS:ESPAISNATURALS_PEIN",
        "natura2000": "ESPAIS_NATURALS:ESPAISNATURALS_XARNAT_2000",
    }
    gdfs = []
    for name, typename in layers_spec.items():
        raw_gpkg = raw_dir / f"{name}_raw.gpkg"
        if not raw_gpkg.exists():
            gdf = read_wfs_layer(BASE_WFS, typename, label=name)
            gdf.to_file(raw_gpkg, driver="GPKG", layer=name)
        else:
            print(f"  [skip] {raw_gpkg.name}")
            gdf = gpd.read_file(raw_gpkg, layer=name)
        print(f"  {name}: {len(gdf):,} features  cols: {list(gdf.columns)[:8]}")
        gdfs.append(gdf[["geometry"]].copy())

    if inspect_only:
        return

    # Merge + dissolve PEIN ∪ Natura 2000 to avoid double-counting overlaps
    all_geoms = pd.concat([g.geometry for g in gdfs], ignore_index=True)
    all_gdf = gpd.GeoDataFrame(geometry=all_geoms, crs=gdfs[0].crs)
    all_gdf = reproject_and_fix(all_gdf)
    # Dissolve into single-row frame (union_all)
    dissolved = all_gdf.geometry.union_all()
    # Keep as (possibly multi-)polygon; explode to single parts for cleaner GIS
    out = gpd.GeoDataFrame(
        {"source": ["PEIN+Natura2000"], "merged": [True]},
        geometry=[dissolved],
        crs=ANALYSIS_CRS,
    )
    # Explode multipart → singlepart for pipeline area calculations
    out = out.explode(index_parts=False).reset_index(drop=True)

    save_gpkg(out, proc_gpkg, "protected_areas")
    save_provenance(raw_dir, "protected_areas", {
        "source": "Generalitat de Catalunya WFS – ESPAIS_NATURALS",
        "source_url": BASE_WFS,
        "wfs_layers": list(layers_spec.values()),
        "processing": "PEIN ∪ Xarxa Natura 2000 dissolved (no double counting)",
        "crs_processed": ANALYSIS_CRS,
        "features_after_explode": len(out),
        "license": "Open Government Licence Generalitat de Catalunya",
    })
    print(f"  ✓ protected_areas done: {len(out):,} features after dissolve+explode")


# ─────────────────────────────────────────────────────────────────────────────
# 3. Flood zones T100 (ACA)
# ─────────────────────────────────────────────────────────────────────────────
def run_flood_zones(dry_run: bool = False, inspect_only: bool = False) -> None:
    print("\n" + "=" * 60)
    print("[3] Flood Zones T100  (ACA WFS – AIGUA_LI100)")
    print("=" * 60)

    raw_dir = RAW_GIS / "aca_flood_zones"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_gpkg = raw_dir / "flood_t100_raw.gpkg"
    proc_gpkg = PROC_GIS / "flood_zones.gpkg"
    BASE_WFS = "https://sig.gencat.cat/ows/AIGUA/wfs"

    if dry_run:
        print("  DRY RUN: would download AIGUA WFS layer AIGUA_LI100")
        return

    if not raw_gpkg.exists():
        gdf = read_wfs_layer(BASE_WFS, "AIGUA:AIGUA_LI100", label="flood T100", max_features=50_000)
        gdf.to_file(raw_gpkg, driver="GPKG", layer="flood_t100")
    else:
        print(f"  [skip] {raw_gpkg.name}")
        gdf = gpd.read_file(raw_gpkg, layer="flood_t100")

    print(f"  {len(gdf):,} features  cols: {list(gdf.columns)[:8]}")

    if inspect_only:
        return

    out = gdf[["geometry"]].copy()
    out = reproject_and_fix(out)

    save_gpkg(out, proc_gpkg, "flood_zones")
    save_provenance(raw_dir, "flood_zones", {
        "source": "Agència Catalana de l'Aigua (ACA) WFS",
        "source_url": BASE_WFS,
        "wfs_layer": "AIGUA:AIGUA_LI100",
        "return_period": "T100 (100-year flood)",
        "crs_processed": ANALYSIS_CRS,
        "features": len(out),
        "license": "Open Government Licence Generalitat de Catalunya",
    })
    print(f"  ✓ flood_zones done: {len(out):,} features")


# ─────────────────────────────────────────────────────────────────────────────
# 4. Urban zoning (MUC – Mapa Urbanístic de Catalunya)
# ─────────────────────────────────────────────────────────────────────────────
# MUC CODI_CLAS_MUC codes (confirmed from downloaded data, October 2026):
#
#   SUC  (5120) → Sòl urbà                         → urban_core
#   SNC  (2919) → Sòl urbà no consolidat           → urban_residential
#   SUD  (3465) → Sòl urbanitzable delimitat       → urban_residential
#   SND  ( 615) → Sòl urbanitzable no delimitat    → urban_residential (conservative)
#   SNU  (2883) → Sòl no urbanitzable              → None (this is our BESS target area)
_MUC_ZONE_MAP = {
    # ── urban_core: consolidated built urban land – hard exclusion for BESS
    "SUC": "urban_core",
    # ── urban_residential: non-consolidated urban + urbanizable land – hard exclusion
    "SNC": "urban_residential",
    "SUD": "urban_residential",
    "SND": "urban_residential",
    # SNU (Sòl no urbanitzable) is NOT excluded: it is the main BESS candidate area
}


def _map_muc_zone(code: object) -> Optional[str]:
    if code is None or (isinstance(code, float) and pd.isna(code)):
        return None
    key = str(code).strip()
    return _MUC_ZONE_MAP.get(key) or _MUC_ZONE_MAP.get(key.upper())


def run_zoning(dry_run: bool = False, inspect_only: bool = False) -> None:
    print("\n" + "=" * 60)
    print("[4] Urban Zoning  (MUC – Generalitat PLANEJAMENT WFS)")
    print("=" * 60)

    raw_dir = RAW_GIS / "gencat_muc"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_gpkg = raw_dir / "muc_classifications_raw.gpkg"
    proc_gpkg = PROC_GIS / "zoning.gpkg"
    BASE_WFS = "https://sig.gencat.cat/ows/PLANEJAMENT/wfs"

    if dry_run:
        print("  DRY RUN: would download PLANEJAMENT WFS layer MUC_CLASSIFICACIONS")
        return

    if not raw_gpkg.exists():
        gdf = read_wfs_layer(
            BASE_WFS,
            "PLANEJAMENT:MUC_CLASSIFICACIONS",
            label="MUC land classifications",
            max_features=300_000,
        )
        # GPKG is case-insensitive for field names; 'id' and 'ID' both present → collision.
        # Also 'ID' conflicts with OGR's reserved fid. Drop the WFS feature-id strings
        # and rename the integer ID column to avoid GPKG write errors.
        drop_cols = [c for c in gdf.columns if c.lower() == "id" and
                     gdf[c].dtype == object]  # drop string WFS feature-id
        gdf = gdf.drop(columns=drop_cols)
        gdf = gdf.rename(columns={"ID": "muc_id"})  # rename integer ID away from reserved name
        gdf.to_file(raw_gpkg, driver="GPKG", layer="muc_classifications")
    else:
        print(f"  [skip] {raw_gpkg.name}")
        gdf = gpd.read_file(raw_gpkg, layer="muc_classifications")

    print(f"  {len(gdf):,} features  cols: {list(gdf.columns)}")

    # Inspect classification codes
    clas_col = "CODI_CLAS_MUC"
    if clas_col in gdf.columns:
        vc = gdf[clas_col].value_counts(dropna=False).to_dict()
        print(f"  {clas_col} values: {vc}")
    else:
        print(f"  WARNING: expected column {clas_col!r} not found; "
              f"available: {list(gdf.columns)}")
        # Try fallback
        for candidate in ["CODI_CLAS_AJUNT", "DESC_CLAS_MUC", "CODI"]:
            if candidate in gdf.columns:
                clas_col = candidate
                print(f"  using fallback column: {clas_col!r}")
                break

    if inspect_only:
        print("  Inspect mode: update _MUC_ZONE_MAP in the script based on values above")
        return

    if clas_col not in gdf.columns:
        print(f"  ERROR: no usable classification column found; skipping zoning")
        return

    out = gdf[["geometry", clas_col]].copy()
    out["zone_class"] = out[clas_col].apply(_map_muc_zone)

    mapped = out["zone_class"].notna().sum()
    total = len(out)
    print(f"  mapping: {mapped:,}/{total:,} features have a zone_class "
          f"({mapped/total*100:.1f}%)")
    print(f"  zone_class distribution: {out['zone_class'].value_counts(dropna=False).to_dict()}")

    # Only keep excluded zones (urban) for the hard-constraint pipeline layer
    out = out[out["zone_class"].notna()].copy()
    out = reproject_and_fix(out)

    save_gpkg(out, proc_gpkg, "zoning")
    save_provenance(raw_dir, "zoning", {
        "source": "Generalitat WFS – Mapa Urbanístic de Catalunya (MUC)",
        "source_url": BASE_WFS,
        "wfs_layer": "PLANEJAMENT:MUC_CLASSIFICACIONS",
        "crs_processed": ANALYSIS_CRS,
        "source_column": clas_col,
        "pipeline_column": "zone_class",
        "pipeline_values": ["urban_core", "urban_residential"],
        "features_extracted": len(out),
        "license": "Open Government Licence Generalitat de Catalunya",
        "note": "Only urban/urbanizable zones retained (SU, SUD). Non-urbanizable land omitted.",
    })
    print(f"  ✓ zoning done: {len(out):,} urban zone features")


# ─────────────────────────────────────────────────────────────────────────────
# 5. Roads (Geofabrik – OpenStreetMap Catalonia)
# ─────────────────────────────────────────────────────────────────────────────
# OSM fclass values present in Geofabrik Catalonia roads shapefile:
#   motorway, motorway_link, trunk, trunk_link, primary, primary_link,
#   secondary, secondary_link, tertiary, tertiary_link, unclassified, residential, …
#
# Pipeline uses road_class ∈ {motorway, primary} to find major-road distance.
# trunk (autovia/national) is equivalent to motorway for BESS accessibility.
_ROAD_CLASS_MAP = {
    "motorway": "motorway",
    "motorway_link": "motorway",
    "trunk": "motorway",
    "trunk_link": "motorway",
    "primary": "primary",
    "primary_link": "primary",
}


def run_roads(dry_run: bool = False, inspect_only: bool = False) -> None:
    print("\n" + "=" * 60)
    print("[5] Roads  (Geofabrik – OpenStreetMap Catalonia)")
    print("=" * 60)

    raw_dir = RAW_GIS / "geofabrik_catalonia"
    raw_dir.mkdir(parents=True, exist_ok=True)
    zip_path = raw_dir / "cataluna-latest-free.shp.zip"
    proc_gpkg = PROC_GIS / "roads.gpkg"

    if dry_run:
        print("  DRY RUN: would download cataluna-latest-free.shp.zip from Geofabrik")
        return

    download_file(
        "https://download.geofabrik.de/europe/spain/cataluna-latest-free.shp.zip",
        zip_path,
        "Geofabrik Catalonia shapefiles",
    )

    # Locate roads shapefile inside the zip
    roads_shp: Optional[Path] = None
    already_extracted = list(raw_dir.glob("*roads*.shp"))
    if already_extracted:
        roads_shp = already_extracted[0]
        print(f"  [skip] already extracted: {roads_shp.name}")
    else:
        print("  extracting roads shapefile from zip...")
        with zipfile.ZipFile(zip_path, "r") as z:
            names = z.namelist()
            road_files = [n for n in names if "roads" in n.lower()]
            print(f"  road-related entries: {road_files}")
            for n in road_files:
                z.extract(n, raw_dir)
        extracted = list(raw_dir.glob("*roads*.shp"))
        if not extracted:
            raise FileNotFoundError(
                f"No *roads*.shp found after extracting {zip_path.name}. "
                f"Available: {[n for n in names][:20]}"
            )
        roads_shp = extracted[0]

    print(f"  reading {roads_shp.name}...")
    gdf = gpd.read_file(roads_shp)
    print(f"  {len(gdf):,} features  cols: {list(gdf.columns)}")

    if "fclass" in gdf.columns:
        print(f"  fclass values (top 20): {gdf['fclass'].value_counts().head(20).to_dict()}")

    if inspect_only:
        return

    # Filter to major roads only and normalise road_class
    if "fclass" in gdf.columns:
        keep = gdf["fclass"].isin(_ROAD_CLASS_MAP)
        out = gdf[keep][["fclass", "geometry"]].copy()
        out["road_class"] = out["fclass"].map(_ROAD_CLASS_MAP)
        out = out.drop(columns=["fclass"])
    else:
        print("  WARNING: 'fclass' column not found; keeping all roads without class mapping")
        out = gdf[["geometry"]].copy()

    out = reproject_and_fix(out)
    print(f"  road_class distribution: {out.get('road_class', pd.Series()).value_counts().to_dict()}")

    save_gpkg(out, proc_gpkg, "roads")
    save_provenance(raw_dir, "roads", {
        "source": "Geofabrik – OpenStreetMap Catalonia",
        "source_url": "https://download.geofabrik.de/europe/spain/cataluna-latest-free.shp.zip",
        "license": "ODbL – OpenStreetMap contributors (https://www.openstreetmap.org/copyright)",
        "crs_processed": ANALYSIS_CRS,
        "classes_kept": sorted(_ROAD_CLASS_MAP.keys()),
        "pipeline_column": "road_class",
        "pipeline_values": ["motorway", "primary"],
        "features": len(out),
    })
    print(f"  ✓ roads done: {len(out):,} major-road segments")


# ─────────────────────────────────────────────────────────────────────────────
# 6. Land cover 2024 (ICGC MCSC v1.0)
# ─────────────────────────────────────────────────────────────────────────────
# MCSC v1.0 2024 uses a 3-digit numeric code stored in column 'nivell_2'.
# Legend confirmed from the GPKG 'cobertes_sol_categories' table (October 2026).
#
# Code groups:
#   1xx – Agricultural / crop land
#   2xx – Forest and semi-natural vegetation
#   3xx – Urban and artificial surfaces
#   4xx – Water bodies
#
# Pipeline categories:
#   agricultural_dryland – dryland crops (vineyards, olives, arable) suitable for BESS
#   grassland_scrub      – scrubland, natural grassland, open land
#   bare_industrial      – industrial/commercial zones, quarries, brownfields
#
_MCSC_CLASS_MAP: dict[str, str] = {
    # ── Agricultural dryland (1xx group) ────────────────────────────────────
    # 111 Conreus herbacis (herbaceous crops – predominantly dryland in Catalonia)
    "111": "agricultural_dryland",
    # 113 Vinyes (vineyards)
    "113": "agricultural_dryland",
    # 114 Oliverars (olive groves)
    "114": "agricultural_dryland",
    # 115 Altres conreus llenyosos (other woody crops)
    "115": "agricultural_dryland",
    # 116 Conreus en transformació (crops in transition)
    "116": "agricultural_dryland",
    # 112 Horta, vivers i conreus forçats (market gardens, greenhouses) — omitted:
    #   intensive irrigated, unsuitable for large-scale BESS

    # ── Grassland / scrubland (2xx group) ───────────────────────────────────
    # 224 Matollar (scrubland / maquis / garrigue) – largest single class
    "224": "grassland_scrub",
    # 228 Prats i herbassars (natural grasslands and meadows)
    "228": "grassland_scrub",
    # 230 Sòl nu forestal (bare forest soil – clearcuts, logging roads)
    "230": "grassland_scrub",
    # 231 Zones cremades (recently burned areas – recovering, potentially available)
    "231": "grassland_scrub",

    # ── Bare / industrial (3xx group) ───────────────────────────────────────
    # 347 Zones industrials, comercials i/o de serveis (industrial/commercial zones)
    "347": "bare_industrial",
    # 349 Zones d'extracció minera i/o abocadors (quarries, mines, landfills)
    "349": "bare_industrial",
    # 350 Zones en transformació (construction sites / brownfields)
    "350": "bare_industrial",
    # 352 Sòl nu urbà (urban bare soil – cleared plots, vacant lots)
    "352": "bare_industrial",
}


def _find_mcsc_clas_col(gdf: gpd.GeoDataFrame) -> str:
    """Identify the classification code column in a MCSC GeoPackage."""
    # ICGC MCSC v1.0 2024: confirmed column name is 'nivell_2'
    candidates = [
        "nivell_2",                                   # MCSC v1.0 2024 (confirmed)
        "CODI_COBER", "codi_cober", "COBER", "cober", # older format candidates
        "CLASS_CODE", "class_code", "CLAS", "clas",
        "CODI", "codi", "CODE", "code",
        "TIPUS", "tipus", "CAT", "cat",
    ]
    for c in candidates:
        if c in gdf.columns:
            return c
    # Heuristic: first non-geometry, non-date column with 10-100 unique integer values
    for c in gdf.columns:
        if c.lower() in ("geometry", "geom", "fid", "id", "objectid", "shape", "data_font"):
            continue
        col = gdf[c].dropna()
        n_unique = col.nunique()
        if 10 <= n_unique <= 100 and pd.api.types.is_numeric_dtype(col):
            print(f"  heuristic: using {c!r} ({n_unique} unique numeric values)")
            return c
    # Fallback: first non-geometry column
    non_geom = [c for c in gdf.columns if c.lower() not in ("geometry", "geom")]
    return non_geom[0] if non_geom else gdf.columns[0]


def run_land_cover(dry_run: bool = False, inspect_only: bool = False) -> None:
    print("\n" + "=" * 60)
    print("[6] Land Cover 2024  (ICGC MCSC v1.0 2024 – 810 MB zip)")
    print("=" * 60)

    raw_dir = RAW_GIS / "icgc_cobertes_sol_2024"
    raw_dir.mkdir(parents=True, exist_ok=True)
    zip_path = raw_dir / "cobertes-sol-v1r0-2024.zip"
    proc_gpkg = PROC_GIS / "land_cover.gpkg"

    if dry_run:
        print("  DRY RUN: would download cobertes-sol-v1r0-2024.zip (810 MB) from ICGC datacloud")
        return

    download_file(
        "https://datacloud.icgc.cat/datacloud/cobertes-sol/gpkg/cobertes-sol-v1r0-2024.zip",
        zip_path,
        "ICGC MCSC 2024 GeoPackage zip (810 MB)",
    )

    # Extract GPKG from zip
    gpkg_files = list(raw_dir.glob("*.gpkg"))
    if not gpkg_files:
        print("  extracting GeoPackage from zip...")
        with zipfile.ZipFile(zip_path, "r") as z:
            all_names = z.namelist()
            gpkg_in_zip = [n for n in all_names if n.endswith(".gpkg")]
            print(f"  .gpkg files in zip: {gpkg_in_zip}")
            for n in gpkg_in_zip:
                z.extract(n, raw_dir)
        gpkg_files = list(raw_dir.glob("*.gpkg"))

    if not gpkg_files:
        raise FileNotFoundError(
            f"No .gpkg found after extracting {zip_path.name}. "
            "Check zip contents manually."
        )

    gpkg = gpkg_files[0]
    layers_in_gpkg = pyogrio.list_layers(str(gpkg))
    print(f"  GPKG: {gpkg.name}")
    print(f"  layers: {layers_in_gpkg}")

    layer_name = layers_in_gpkg[0][0] if len(layers_in_gpkg) > 0 else None

    # Inspect first 500 features to find classification column
    print(f"  inspecting columns (first 500 features of layer={layer_name!r})...")
    sample = gpd.read_file(gpkg, layer=layer_name, max_features=500)
    print(f"  columns: {list(sample.columns)}")
    print(f"  dtypes: {sample.dtypes.to_dict()}")

    # Find the code column and show its unique values
    clas_col = _find_mcsc_clas_col(sample)
    unique_codes = sorted(sample[clas_col].dropna().astype(str).unique())
    print(f"  classification column: {clas_col!r}")
    print(f"  unique codes in sample: {unique_codes}")

    if inspect_only:
        print("\n  ──────────────────────────────────────────────────────")
        print("  INSPECT MODE: update _MCSC_CLASS_MAP with the codes above.")
        print("  Re-run without --inspect-only to process the full dataset.")
        print("  ──────────────────────────────────────────────────────")
        return

    # Apply mapping
    # Build WHERE clause for GDAL to read only relevant classes (avoids loading 1.5M features)
    mapped_codes = sorted(_MCSC_CLASS_MAP.keys())
    # nivell_2 is stored as integer in the GPKG → use unquoted numeric literals
    # Try integer first, fall back to quoted string if the filter fails
    where_int = f"{clas_col} IN ({', '.join(mapped_codes)})"
    print(f"  reading with SQL filter: WHERE {where_int}")
    try:
        gdf = gpd.read_file(gpkg, layer=layer_name, where=where_int)
        print(f"  {len(gdf):,} features match pipeline classes")
    except Exception as exc:
        print(f"  integer WHERE failed ({exc}); trying quoted strings...")
        where_str = f"{clas_col} IN ({', '.join(repr(c) for c in mapped_codes)})"
        try:
            gdf = gpd.read_file(gpkg, layer=layer_name, where=where_str)
        except Exception as exc2:
            print(f"  quoted WHERE also failed ({exc2}); reading full layer (slow)...")
            gdf = gpd.read_file(gpkg, layer=layer_name)

    print(f"  total features in GPKG layer: ~{len(gdf):,}")

    out = gdf[["geometry", clas_col]].copy()
    out["land_class"] = out[clas_col].astype(str).map(_MCSC_CLASS_MAP)

    mapped = out["land_class"].notna().sum()
    total = len(out)
    if total:
        print(f"  mapping: {mapped:,}/{total:,} features mapped ({mapped/total*100:.0f}%)")

    dist = out["land_class"].value_counts(dropna=False).to_dict()
    print(f"  land_class distribution: {dist}")

    out = out[out["land_class"].notna()].copy()
    out = reproject_and_fix(out)

    save_gpkg(out, proc_gpkg, "land_cover")
    save_provenance(raw_dir, "land_cover", {
        "source": "ICGC – Mapa de Cobertes del Sòl de Catalunya (MCSC) v1.0",
        "year": 2024,
        "source_url": (
            "https://datacloud.icgc.cat/datacloud/cobertes-sol/gpkg/"
            "cobertes-sol-v1r0-2024.zip"
        ),
        "license": "Creative Commons Attribution 4.0 (CC BY 4.0) ICGC",
        "classes_total": 41,
        "classes_extracted": sorted(_MCSC_CLASS_MAP.keys()),
        "crs_processed": ANALYSIS_CRS,
        "features": len(out),
        "zip_size_mb": zip_path.stat().st_size // (1024 ** 2),
        "source_col": clas_col,
    })
    print(f"  ✓ land_cover done: {len(out):,} features with pipeline class mapping")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
ALL_DATASETS = {
    "municipalities": run_municipalities,
    "protected_areas": run_protected_areas,
    "flood_zones": run_flood_zones,
    "zoning": run_zoning,
    "roads": run_roads,
    "land_cover": run_land_cover,
}

# Download order: smallest / fastest first
DEFAULT_ORDER = [
    "municipalities",
    "protected_areas",
    "flood_zones",
    "zoning",
    "roads",
    "land_cover",
]


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Download and prepare GIS datasets for the BESS opportunity map."
    )
    ap.add_argument(
        "--datasets", nargs="*",
        choices=list(ALL_DATASETS), default=None,
        help="Which datasets to process (default: all in dependency order)",
    )
    ap.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be done without downloading anything",
    )
    ap.add_argument(
        "--inspect-only", action="store_true",
        help="Download raw data and print attribute info; skip processed output",
    )
    args = ap.parse_args()

    datasets = args.datasets or DEFAULT_ORDER
    # Preserve user order but only include known datasets
    datasets = [d for d in datasets if d in ALL_DATASETS]

    RAW_GIS.mkdir(parents=True, exist_ok=True)
    PROC_GIS.mkdir(parents=True, exist_ok=True)

    print(f"BESS Opportunity Map – GIS dataset download")
    print(f"  RAW_GIS  : {RAW_GIS}")
    print(f"  PROC_GIS : {PROC_GIS}")
    print(f"  datasets : {datasets}")
    print(f"  dry_run  : {args.dry_run}")
    print(f"  date     : {TODAY}")

    results: dict[str, str] = {}
    for name in datasets:
        fn = ALL_DATASETS[name]
        try:
            fn(dry_run=args.dry_run, inspect_only=args.inspect_only)
            results[name] = "OK"
        except Exception as exc:
            import traceback
            traceback.print_exc()
            results[name] = f"FAILED: {exc}"
            print(f"\n  ✗ {name} FAILED: {exc}")

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for name, status in results.items():
        icon = "✓" if status == "OK" else "✗"
        print(f"  {icon}  {name:<20} {status}")

    failed = [n for n, s in results.items() if s != "OK"]
    if failed:
        print(f"\n{len(failed)} dataset(s) failed: {failed}")
        sys.exit(1)
    else:
        print("\nAll datasets completed successfully.")
        print("\nNext steps:")
        print("  1. Review processed GeoPackages in data/processed/gis/")
        print("  2. Update config/datasets.yaml with real paths")
        print("  3. Run: ./start.sh --mode real --validate")


if __name__ == "__main__":
    main()
