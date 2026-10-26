"""Map outputs: static PNG (matplotlib) and interactive HTML (folium).

Every demo map carries a SYNTHETIC watermark.
"""

from __future__ import annotations

from pathlib import Path

import folium
import geopandas as gpd
import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

SYNTHETIC_NOTE = "SYNTHETIC DEMO DATA - fictional, not a real Catalan BESS opportunity"


def _base(ax, context: dict[str, gpd.GeoDataFrame]) -> list:
    handles = []
    if (m := context.get("municipalities")) is not None:
        m.boundary.plot(ax=ax, color="#bbbbbb", linewidth=0.4, zorder=1)
    if (s := context.get("suitable_land_net")) is not None:
        s.plot(ax=ax, color="#9bd17f", alpha=0.6, zorder=2)
        handles.append(Patch(color="#9bd17f", alpha=0.6, label="Suitable land (net)"))
    if (h := context.get("hard_constraints")) is not None:
        h.plot(ax=ax, facecolor="none", edgecolor="#c0392b", hatch="///", linewidth=0.3,
               zorder=3)
        handles.append(Patch(facecolor="none", edgecolor="#c0392b", hatch="///",
                             label="Hard constraints"))
    if (r := context.get("roads")) is not None:
        r.plot(ax=ax, color="#555555", linewidth=0.8, zorder=4)
        handles.append(Line2D([], [], color="#555555", label="Major roads"))
    return handles


def _finish(fig, ax, title: str, mode: str, path: Path, handles: list) -> Path:
    ax.set_title(title, fontsize=12)
    ax.set_xlabel("Easting (m, EPSG:25831)")
    ax.set_ylabel("Northing (m, EPSG:25831)")
    ax.ticklabel_format(style="plain")
    ax.tick_params(labelsize=7)
    if handles:
        ax.legend(handles=handles, loc="lower left", fontsize=7, framealpha=0.9)
    if mode == "demo":
        ax.text(0.5, 0.5, "SYNTHETIC", transform=ax.transAxes, fontsize=60, color="red",
                alpha=0.12, ha="center", va="center", rotation=30, zorder=10)
        note, color = SYNTHETIC_NOTE, "red"
    else:
        note, color = "Opportunity screening only - not an engineering feasibility study", "k"
    ax.annotate(note, xy=(0.5, -0.14), xycoords="axes fraction", ha="center", fontsize=8,
                color=color)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}")
    fig.savefig(tmp, dpi=150, bbox_inches="tight", format="png")
    plt.close(fig)
    tmp.replace(path)
    return path


def node_overview_map(nodes, context, mode: str, path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(8, 8))
    handles = _base(ax, context)
    styles = {"transmission": ("#1f3b73", "^", 70), "distribution": ("#e67e22", "o", 35)}
    level = nodes.get("network_level")
    for lvl, (color, marker, size) in styles.items():
        sub = nodes[level == lvl] if level is not None else nodes.iloc[0:0]
        if len(sub):
            sub.plot(ax=ax, color=color, marker=marker, markersize=size, edgecolor="black",
                     linewidth=0.4, zorder=5)
            handles.append(Line2D([], [], color=color, marker=marker, linestyle="",
                                  label=f"{lvl.capitalize()} node"))
    other = nodes[~level.isin(list(styles))] if level is not None else nodes
    if len(other):
        other.plot(ax=ax, color="grey", markersize=25, zorder=5)
        handles.append(Line2D([], [], color="grey", marker="o", linestyle="", label="Other node"))
    return _finish(fig, ax, "Grid nodes and land feasibility", mode, path, handles)


def score_map(nodes, scores, scenario: str, context, mode: str, path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(8, 8))
    handles = _base(ax, context)
    s = scores[scores["scenario"] == scenario][["node_id", "score", "rank"]]
    g = nodes.merge(s, on="node_id", how="left")
    ranked = g[g["rank"].notna()]
    unranked = g[g["rank"].isna()]
    if len(unranked):
        unranked.plot(ax=ax, facecolor="none", edgecolor="grey", markersize=40, zorder=5)
        handles.append(Line2D([], [], marker="o", color="grey", markerfacecolor="none",
                              linestyle="", label="Unranked (excluded / insufficient data)"))
    if len(ranked):
        ranked.plot(ax=ax, column="score", cmap="RdYlGn", vmin=0, vmax=1, markersize=70,
                    edgecolor="black", linewidth=0.4, zorder=6, legend=True,
                    legend_kwds={"label": "Score (0-1, illustrative weights)", "shrink": 0.6})
        for _, r in ranked.nsmallest(5, "rank").iterrows():
            ax.annotate(f"#{int(r['rank'])}", (r.geometry.x, r.geometry.y), xytext=(4, 4),
                        textcoords="offset points", fontsize=7, zorder=7)
    title = f"Opportunity score - {scenario.replace('_', ' ')} (illustrative)"
    return _finish(fig, ax, title, mode, path, handles)


# ---------------------------------------------------------------------------
# Interactive HTML maps (folium) — style inspired by hhw2002/data-driven-challenge-project
# ---------------------------------------------------------------------------

_SCORE_COLORS = ["#d73027", "#fc8d59", "#fee08b", "#1a9850"]  # red → green (low → high)
_GREY = "#8a8a86"


def _to_wgs84(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if gdf.crs is None or gdf.crs.to_epsg() == 4326:
        return gdf
    return gdf.to_crs(epsg=4326)


def _swatch(color: str) -> str:
    return (
        f'<span style="display:inline-block;width:12px;height:12px;border-radius:50%;'
        f'background:{color};border:1px solid #fff;box-shadow:0 0 0 1px #9a9a96;'
        f'margin-right:6px;vertical-align:-1px;"></span>'
    )


def _folium_legend(title: str, subtitle: str, classes: list[dict], watermark: str = "") -> str:
    rows = "".join(
        f'<div style="margin-top:4px;">{_swatch(c["color"])}{c["label"]}'
        + (f'<span style="color:#6b6b68;"> · {c["count"]}</span>' if "count" in c else "")
        + "</div>"
        for c in classes
    )
    wm = (
        f'<div style="color:#c0392b;font-size:10px;font-style:italic;margin-top:6px;">'
        f"{watermark}</div>"
    ) if watermark else ""
    return (
        '<div style="position:fixed;bottom:24px;left:12px;z-index:1000;'
        "background:#fff;color:#1f1f1e;padding:10px 12px;border-radius:6px;"
        "box-shadow:0 1px 4px rgba(0,0,0,0.3);font:13px/1.3 'Open Sans',Arial,sans-serif;"
        'max-width:280px;">'
        f"<b>{title}</b>"
        + (f'<div style="color:#6b6b68;">{subtitle}</div>' if subtitle else "")
        + f"{rows}{wm}</div>"
    )


_ML_COLORS = {
    "opportunity": "#e67e22",  # orange: high probability, no existing project
    "existing": "#2980b9",     # blue: has operating renewable nearby
    "other": _GREY,            # grey: low probability, no project
}


def _save_html(m: folium.Map, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}")
    m.save(str(tmp))
    tmp.replace(path)
    return path


def node_overview_map_html(nodes, context: dict, mode: str, path: Path) -> Path:
    n4 = _to_wgs84(nodes)
    center = [n4.geometry.y.mean(), n4.geometry.x.mean()]
    m = folium.Map(
        location=center, zoom_start=8,
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Canvas/MapServer/tile/{z}/{y}/{x}",
        attr="Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ",
    )

    if (mun := context.get("municipalities")) is not None:
        folium.GeoJson(
            _to_wgs84(mun).__geo_interface__,
            name="Municipalities",
            style_function=lambda _: {"fillOpacity": 0, "color": "#aaaaaa", "weight": 0.8},
        ).add_to(m)

    level_col = n4.get("network_level")
    level_styles = {
        "transmission": ("#1f3b73", 7, "Transmission node"),
        "distribution": ("#e67e22", 5, "Distribution node"),
    }
    classes = []
    for lvl, (color, radius, label) in level_styles.items():
        sub = n4[level_col == lvl] if level_col is not None else n4.iloc[0:0]
        if not len(sub):
            continue
        layer = folium.FeatureGroup(name=f"{_swatch(color)}{label}", show=True)
        for _, row in sub.iterrows():
            name = row.get("node_name") or row["node_id"]
            folium.CircleMarker(
                location=[row.geometry.y, row.geometry.x],
                radius=radius, color="#fff", weight=1.5,
                fill=True, fill_color=color, fill_opacity=1.0,
                tooltip=name,
                popup=folium.Popup(
                    f"<b>{name}</b><br>ID: {row['node_id']}<br>Level: {lvl}", max_width=240
                ),
            ).add_to(layer)
        layer.add_to(m)
        classes.append({"color": color, "label": label, "count": len(sub)})

    other = n4[~level_col.isin(list(level_styles))] if level_col is not None else n4
    if len(other):
        layer = folium.FeatureGroup(name=f"{_swatch(_GREY)}Other node", show=True)
        for _, row in other.iterrows():
            name = row.get("node_name") or row["node_id"]
            folium.CircleMarker(
                location=[row.geometry.y, row.geometry.x],
                radius=5, color="#fff", weight=1.5,
                fill=True, fill_color=_GREY, fill_opacity=0.75,
                tooltip=name,
                popup=folium.Popup(
                    f"<b>{name}</b><br>ID: {row['node_id']}<br>Level: other", max_width=240
                ),
            ).add_to(layer)
        layer.add_to(m)
        classes.append({"color": _GREY, "label": "Other node", "count": len(other)})

    folium.LayerControl(collapsed=False).add_to(m)
    wm = "SYNTHETIC DEMO DATA" if mode == "demo" else ""
    m.get_root().html.add_child(
        folium.Element(_folium_legend("Grid nodes", "by network level · count", classes, wm))
    )
    return _save_html(m, path)


def score_map_html(nodes, scores, scenario: str, context: dict, mode: str, path: Path) -> Path:
    s = scores[scores["scenario"] == scenario][["node_id", "score", "rank"]]
    g4 = _to_wgs84(nodes.merge(s, on="node_id", how="left"))
    center = [g4.geometry.y.mean(), g4.geometry.x.mean()]
    m = folium.Map(
        location=center, zoom_start=8,
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Canvas/MapServer/tile/{z}/{y}/{x}",
        attr="Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ",
    )

    if (mun := context.get("municipalities")) is not None:
        folium.GeoJson(
            _to_wgs84(mun).__geo_interface__,
            name="Municipalities",
            style_function=lambda _: {"fillOpacity": 0, "color": "#aaaaaa", "weight": 0.8},
        ).add_to(m)

    ranked = g4[g4["rank"].notna()].copy()
    unranked = g4[g4["rank"].isna()]

    # Unranked layer
    if len(unranked):
        layer = folium.FeatureGroup(
            name=f"{_swatch(_GREY)}Unranked (excluded / insufficient data)", show=True
        )
        for _, row in unranked.iterrows():
            name = row.get("node_name") or row["node_id"]
            folium.CircleMarker(
                location=[row.geometry.y, row.geometry.x],
                radius=5, color="#fff", weight=1.5,
                fill=True, fill_color=_GREY, fill_opacity=0.6,
                tooltip=name,
                popup=folium.Popup(
                    f"<b>{name}</b><br>ID: {row['node_id']}<br>Status: unranked", max_width=240
                ),
            ).add_to(layer)
        layer.add_to(m)

    legend_classes: list[dict] = [{"color": _GREY, "label": "Unranked", "count": len(unranked)}]

    if len(ranked):
        q1, q2, q3 = ranked["score"].quantile([0.25, 0.5, 0.75]).round(2)
        score_classes = [
            {"label": f"≤ {q1:.2f}", "color": _SCORE_COLORS[0]},
            {"label": f"{q1:.2f} – {q2:.2f}", "color": _SCORE_COLORS[1]},
            {"label": f"{q2:.2f} – {q3:.2f}", "color": _SCORE_COLORS[2]},
            {"label": f"> {q3:.2f}", "color": _SCORE_COLORS[3]},
        ]
        ranked["_cls"] = ranked["score"].apply(
            lambda v: 0 if v <= q1 else (1 if v <= q2 else (2 if v <= q3 else 3))
        )
        for cls_idx, cls in enumerate(score_classes):
            sub = ranked[ranked["_cls"] == cls_idx]
            if not len(sub):
                continue
            layer = folium.FeatureGroup(
                name=f"{_swatch(cls['color'])}{cls['label']}", show=True
            )
            for _, row in sub.iterrows():
                name = row.get("node_name") or row["node_id"]
                rank_str = f"#{int(row['rank'])}" if pd.notna(row["rank"]) else ""
                folium.CircleMarker(
                    location=[row.geometry.y, row.geometry.x],
                    radius=7, color="#fff", weight=1.5,
                    fill=True, fill_color=cls["color"], fill_opacity=1.0,
                    tooltip=f"{name} {rank_str}: {row['score']:.3f}",
                    popup=folium.Popup(
                        f"<b>{name}</b><br>ID: {row['node_id']}<br>"
                        f"Rank: {rank_str}<br>Score: {row['score']:.3f}",
                        max_width=240,
                    ),
                ).add_to(layer)
            layer.add_to(m)
            legend_classes.append({**cls, "count": len(sub)})

    folium.LayerControl(collapsed=False).add_to(m)
    wm = "SYNTHETIC DEMO DATA" if mode == "demo" else ""
    title = f"Opportunity score · {scenario.replace('_', ' ')}"
    m.get_root().html.add_child(
        folium.Element(_folium_legend(title, "score range · node count", legend_classes, wm))
    )
    return _save_html(m, path)


def ml_opportunity_map_html(
    nodes: gpd.GeoDataFrame,
    ml_preds: pd.DataFrame,
    context: dict,
    mode: str,
    path: Path,
) -> Path:
    """Interactive map of ML opportunity nodes coloured by classifier category."""
    merged = _to_wgs84(nodes.merge(ml_preds[["node_id", "ml_label",
                                              "ml_opportunity_prob", "ml_opportunity"]],
                                   on="node_id", how="left"))
    center = [merged.geometry.y.mean(), merged.geometry.x.mean()]
    m = folium.Map(
        location=center, zoom_start=8,
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Canvas/MapServer/tile/{z}/{y}/{x}",
        attr="Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ",
    )

    if (mun := context.get("municipalities")) is not None:
        folium.GeoJson(
            _to_wgs84(mun).__geo_interface__,
            name="Municipalities",
            style_function=lambda _: {"fillOpacity": 0, "color": "#aaaaaa", "weight": 0.8},
        ).add_to(m)

    categories = [
        ("opportunity", "ML opportunity (no project yet)", 9),
        ("existing", "Has existing renewable project", 7),
        ("other", "Low probability", 5),
    ]

    legend_classes = []
    for key, label, radius in categories:
        color = _ML_COLORS[key]
        if key == "opportunity":
            sub = merged[merged["ml_opportunity"].fillna(False)]
        elif key == "existing":
            sub = merged[merged["ml_label"].fillna(0) == 1]
        else:
            sub = merged[~merged["ml_opportunity"].fillna(False) & (merged["ml_label"].fillna(0) == 0)]
        if sub.empty:
            continue
        layer = folium.FeatureGroup(name=f"{_swatch(color)}{label}", show=True)
        for _, row in sub.iterrows():
            name = row.get("node_name") or row["node_id"]
            prob = row.get("ml_opportunity_prob")
            prob_str = f"{prob:.3f}" if pd.notna(prob) else "n/a"
            folium.CircleMarker(
                location=[row.geometry.y, row.geometry.x],
                radius=radius, color="#fff", weight=1.5,
                fill=True, fill_color=color, fill_opacity=1.0,
                tooltip=f"{name} · p={prob_str}",
                popup=folium.Popup(
                    f"<b>{name}</b><br>ID: {row['node_id']}<br>"
                    f"ML prob: {prob_str}<br>Label: {int(row['ml_label']) if pd.notna(row['ml_label']) else 'n/a'}",
                    max_width=240,
                ),
            ).add_to(layer)
        layer.add_to(m)
        legend_classes.append({"color": color, "label": label, "count": len(sub)})

    folium.LayerControl(collapsed=False).add_to(m)
    wm = "SYNTHETIC DEMO DATA" if mode == "demo" else ""
    m.get_root().html.add_child(
        folium.Element(_folium_legend("ML opportunity nodes",
                                     "classifier: learn from developer decisions",
                                     legend_classes, wm))
    )
    return _save_html(m, path)
