"""Extract ERNI per node from REE's monthly PDF reports (ESIOS documentation page).

Source: https://www.esios.ree.es/es/documentacion, documents named
"ERNI Nudos RR.TT PDBF Fase I_YYYYMM" (peninsular day-ahead restrictions). The
"TNP" reports cover the Balearic and Canary Islands only, so they are skipped.
The site blocks scripted downloads, so save the PDFs by hand into
``data/raw/congestion/erni/`` and run:

    uv run --with pdfplumber python scripts/build_erni_records.py

Each report has a bar chart with every node that had notable ERNI and a Top 30 table.
The chart is vector graphics, so bar heights are read exactly and converted to GWh with
the chart's own axis. Top 30 values are then used to check the conversion.

Output: one CSV per report type in ``data/interim/congestion/`` with the columns the
congestion stage expects (erni_node_id, erni_node_name, month, erni_mwh, level), plus
``erni_parse_log.csv``. Node names are REE's 8-character codes (for example RIBARROJ),
so the script also writes ``erni_crosswalk_catalonia.csv`` mapping them to grid nodes.
"""

from __future__ import annotations

import argparse
import math
import re
import unicodedata
from pathlib import Path

import pandas as pd
import pdfplumber

ROOT = Path(__file__).resolve().parents[1]
BLUE, ORANGE = (0.27, 0.45, 0.77), (1.0, 0.6, 0.0)  # RTT, RTD bar fills
LEVELS = {"RTT": "transmission", "RTD": "distribution"}
ROW = re.compile(r"^(.+?) (\d{2,3}) ([\d.]*\d,\d+) ([\d.]*\d,\d+) [\d.,]+ ?% [\d.,]+ ?%$")


def _num(text: str) -> float:
    return float(text.replace(".", "").replace(",", "."))


def _is(colour, target) -> bool:
    return (colour is not None and len(colour) == 3
            and all(abs(a - b) < 0.02 for a, b in zip(colour, target, strict=True)))


def report_type(name: str) -> str:
    return "tnp" if "TNP" in name.upper() else "pdbf_fase1"


def report_month(path: Path, pdf) -> pd.Timestamp:
    m = re.search(r"_(20\d{2})(\d{2})\b", path.stem)
    if m:
        return pd.Timestamp(int(m.group(1)), int(m.group(2)), 1)
    text = " ".join((p.extract_text() or "") for p in pdf.pages[:3])
    m = re.search(r"\b01/(\d{2})/(20\d{2})\b", text.replace(" ", ""))
    if not m:
        raise ValueError("no month in file name or text")
    return pd.Timestamp(int(m.group(2)), int(m.group(1)), 1)


def chart_page(pdf):
    """The page with the most RTT-coloured bars."""
    return max(pdf.pages, key=lambda p: sum(_is(r.get("non_stroking_color"), BLUE)
                                            for r in p.rects))


def axis_scale(page, bars) -> tuple[float, float]:
    """(GWh per point, y of zero) from the integer labels on the left axis."""
    left = min(b["x0"] for b in bars)
    ticks = [(_num(w["text"]), (w["top"] + w["bottom"]) / 2) for w in page.extract_words()
             if w["x1"] < left and re.fullmatch(r"\d+", w["text"]) and w["upright"]]
    values = sorted({v for v, _ in ticks})
    if len(values) < 2:
        raise ValueError("left axis labels not found")
    lo, hi = values[0], values[-1]
    y_lo = next(y for v, y in ticks if v == lo)
    y_hi = next(y for v, y in ticks if v == hi)
    per_point = (hi - lo) / (y_lo - y_hi)
    return per_point, y_lo + lo / per_point


def _angle(c) -> float:
    return math.degrees(math.atan2(c["matrix"][1], c["matrix"][0]))


def diagonal_labels(page, n_columns: int, baseline: float) -> list[str] | None:
    """Labels of slanted (e.g. 35 degree) charts, in left-to-right column order.

    Characters are projected onto the normal of the text direction: characters of one label
    share that coordinate, and labels follow the column order. Returns None when the number of
    label groups found does not equal the number of bar columns.
    """
    below = [c for c in page.chars if baseline + 1 < c["top"] < baseline + 250]
    slanted = [c for c in below if 5 < abs(_angle(c)) < 85]
    if not slanted:
        return None
    a = math.radians(sorted(_angle(c) for c in slanted)[len(slanted) // 2])
    d, n = (math.cos(a), math.sin(a)), (-math.sin(a), math.cos(a))
    pts = [(c["matrix"][4] * n[0] + c["matrix"][5] * n[1],
            c["matrix"][4] * d[0] + c["matrix"][5] * d[1], c["text"]) for c in slanted]
    pts.sort()
    groups, gap = [[pts[0]]], 0.45 * min(c["size"] for c in slanted)
    for prev, cur in zip(pts, pts[1:], strict=False):
        (groups[-1] if cur[0] - prev[0] < gap else groups.append([]) or groups[-1]).append(cur)
    if len(groups) != n_columns:
        return None
    # larger normal coordinate = further left for text rising to the right
    groups.sort(key=lambda g: -sum(p[0] for p in g) / len(g))
    return ["".join(t for _, _, t in sorted(g, key=lambda p: p[1])).strip() for g in groups]


def chart_records(page) -> pd.DataFrame:
    """One row per node and level. A column can be RTT only, RTD only, or both stacked."""
    rects = [r for r in page.rects if r["x1"] - r["x0"] < 100
             and (_is(r.get("non_stroking_color"), BLUE)
                  or _is(r.get("non_stroking_color"), ORANGE))]
    if not rects:
        raise ValueError("no bars found")
    baseline = max(r["bottom"] for r in rects)
    columns: dict[float, list] = {}
    for r in rects:
        key = next((k for k in columns if abs(k - r["x0"]) < 2), r["x0"])
        columns.setdefault(key, []).append(r)
    # a column belongs to the chart if it reaches the baseline (drops legend swatches)
    columns = {k: v for k, v in sorted(columns.items())
               if any(abs(r["bottom"] - baseline) < 2 for r in v)}
    blue = [r for v in columns.values() for r in v if _is(r.get("non_stroking_color"), BLUE)]
    per_point, _ = axis_scale(page, blue or [r for v in columns.values() for r in v])
    labels = [c for c in page.chars if not c["upright"] and c["top"] > baseline]
    slanted = diagonal_labels(page, len(columns), baseline) if not labels else None
    rows = []
    for i, parts in enumerate(columns.values()):
        x0, x1 = min(r["x0"] for r in parts), max(r["x1"] for r in parts)
        if slanted is not None:
            label = slanted[i]
        else:
            chars = sorted((c for c in labels if x0 - 3 <= (c["x0"] + c["x1"]) / 2 <= x1 + 3),
                           key=lambda c: -c["top"])
            label = "".join(c["text"] for c in chars).strip()
        m = re.fullmatch(r"(.+?)\s*(\d{2,3})", label)
        if not m:
            raise ValueError(f"unreadable label {label!r} at x={x0:.0f}")
        name, kv = " ".join(m.group(1).split()), int(m.group(2))
        for code, colour in (("RTT", BLUE), ("RTD", ORANGE)):
            h = sum(r["bottom"] - r["top"] for r in parts
                    if _is(r.get("non_stroking_color"), colour))
            rows.append({"erni_node_id": f"{name} {kv}", "erni_node_name": name,
                         "voltage_kv": kv, "level": LEVELS[code],
                         "erni_gwh": round(h * per_point, 3)})
    return pd.DataFrame(rows)


def table_records(pdf) -> pd.DataFrame:
    rows = []
    for page in pdf.pages:
        for line in (page.extract_text() or "").splitlines():
            m = ROW.match(line.strip())
            if m:
                rows.append({"erni_node_id": f"{m.group(1)} {m.group(2)}",
                             "table_gwh": _num(m.group(4))})
    return pd.DataFrame(rows, columns=["erni_node_id", "table_gwh"])


def parse(path: Path) -> tuple[pd.DataFrame, dict]:
    with pdfplumber.open(path) as pdf:
        month = report_month(path, pdf)
        chart = chart_records(chart_page(pdf))
        table = table_records(pdf)
    total = chart.groupby("erni_node_id", as_index=False)["erni_gwh"].sum()
    check = total.merge(table, on="erni_node_id")
    diff = (check["erni_gwh"] - check["table_gwh"]).abs()
    chart = chart[chart["erni_gwh"] > 0].copy()
    chart["month"] = month.strftime("%Y-%m-%d")
    chart["erni_mwh"] = (chart["erni_gwh"] * 1000).round(0)
    chart["source_file"] = path.name
    log = {"file": path.name, "report": report_type(path.name), "month": chart["month"].iat[0],
           "status": "ok", "nodes": chart["erni_node_id"].nunique(),
           "total_gwh": round(chart["erni_gwh"].sum(), 1), "top30_rows": len(table),
           "top30_checked": len(check),
           "max_abs_diff_gwh": round(diff.max(), 3) if len(diff) else None}
    return chart, log


# REE codes whose 8-character abbreviation is not a prefix of the grid node name.
MANUAL_CROSSWALK = {"RIBARROJ 220": "RIBA-ROJA 220"}


def _norm(name) -> str:
    text = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def crosswalk(records: pd.DataFrame, grid: pd.DataFrame) -> pd.DataFrame:
    """Map REE ERNI codes (e.g. ALBATARR 220) to grid source ids (ALBATARREC 220).

    Rule: same voltage and the normalised ERNI name equals the first characters of the
    normalised grid name. Only unique matches are kept; manual overrides take precedence.
    """
    nodes = grid.assign(
        kv=pd.to_numeric(grid["source_node_id"].str.rsplit(" ", n=1).str[1], errors="coerce"),
        base=grid["source_node_id"].str.rsplit(" ", n=1).str[0].map(_norm))
    rows = []
    for node_id, name, kv in records[["erni_node_id", "erni_node_name", "voltage_kv"]] \
            .drop_duplicates().itertuples(index=False):
        if node_id in MANUAL_CROSSWALK:
            rows.append((node_id, MANUAL_CROSSWALK[node_id], "manual override"))
            continue
        key = _norm(name)
        hits = nodes[(nodes["kv"] == kv) & nodes["base"].str.startswith(key)]
        if len(hits) == 1:
            rows.append((node_id, hits["source_node_id"].iat[0], "name prefix + voltage"))
    out = pd.DataFrame(rows, columns=["congestion_source_node_id", "grid_source_node_id",
                                      "note"])
    known = set(grid["source_node_id"])
    return out[out["grid_source_node_id"].isin(known)].sort_values("congestion_source_node_id")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--src", type=Path, default=ROOT / "data/raw/congestion/erni")
    ap.add_argument("--out", type=Path, default=ROOT / "data/interim/congestion")
    ap.add_argument("--grid", type=Path,
                    default=ROOT / "data/processed/grid_topology/ree_nodes_matched.csv",
                    help="grid node table; its first column 'ree_node' holds source ids")
    args = ap.parse_args()
    frames, logs = [], []
    for path in sorted(args.src.glob("*.pdf")):
        if report_type(path.name) == "tnp":
            logs.append({"file": path.name, "report": "tnp",
                         "status": "skipped: islands only (non-peninsular)"})
            continue
        try:
            frame, log = parse(path)
            frames.append(frame.assign(report=log["report"]))
        except Exception as exc:  # one odd report must not stop the rest
            log = {"file": path.name, "report": report_type(path.name), "status": f"failed: {exc}"}
        logs.append(log)
    if not logs:
        raise SystemExit(f"No PDFs in {args.src}")
    args.out.mkdir(parents=True, exist_ok=True)
    log_df = pd.DataFrame(logs)
    log_df.to_csv(args.out / "erni_parse_log.csv", index=False)
    print(log_df.to_string(index=False))
    if not frames:
        raise SystemExit("No report could be parsed")
    records = pd.concat(frames, ignore_index=True)
    cols = ["erni_node_id", "erni_node_name", "voltage_kv", "month", "level", "erni_mwh",
            "source_file"]
    for report, part in records.groupby("report"):
        target = args.out / f"erni_monthly_{report}.csv"
        part.sort_values(["month", "erni_mwh"], ascending=[True, False])[cols].to_csv(
            target, index=False)
        print(f"wrote {target.relative_to(ROOT)}: {len(part)} rows")
    if args.grid.exists():
        grid = pd.read_csv(args.grid).rename(columns={"ree_node": "source_node_id"})
        xw = crosswalk(records, grid)
        target = args.out / "erni_crosswalk_catalonia.csv"
        xw.to_csv(target, index=False)
        print(f"wrote {target.relative_to(ROOT)}: {len(xw)} Catalan nodes")
        print(xw.to_string(index=False))


if __name__ == "__main__":
    main()
