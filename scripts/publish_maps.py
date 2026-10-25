"""Copy the generated HTML maps from results/real/maps/ into docs/maps/ for GitHub Pages.

Usage:
    uv run python scripts/publish_maps.py

After running this, commit the changes in docs/maps/ and push.  GitHub Pages will
serve the maps from the docs/ folder on the main branch.
"""

from pathlib import Path
import shutil

PROJECT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "results" / "real" / "maps"
DEST_DIR = PROJECT_DIR / "docs" / "maps"

MAP_TITLES = {
    "grid_nodes_overview": "Grid nodes overview",
    "score_renewable_absorption": "Score: renewable absorption",
    "score_connection_readiness": "Score: connection readiness",
    "score_load_grid_support": "Score: load & grid support",
}


def _index_html(map_files: list[Path]) -> str:
    links = []
    for p in sorted(map_files):
        title = MAP_TITLES.get(p.stem, p.stem.replace("_", " ").title())
        links.append(f'    <li><a href="{p.name}">{title}</a></li>')
    return (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "  <title>BESS Opportunity Map – Catalonia</title>\n"
        '  <style>body{font-family:sans-serif;max-width:600px;margin:2rem auto;padding:0 1rem}'
        "a{color:#1c5cab}</style>\n"
        "</head>\n"
        "<body>\n"
        "  <h1>BESS Opportunity Map – Catalonia</h1>\n"
        "  <p>Interactive opportunity-screening maps for grid-scale battery storage. "
        "Scores use illustrative weights and are not validated engineering findings.</p>\n"
        f"  <ul>\n" + "\n".join(links) + "\n  </ul>\n"
        "</body>\n"
        "</html>\n"
    )


def main() -> None:
    if not SRC_DIR.exists():
        raise SystemExit(
            f"No maps found at {SRC_DIR}\n"
            "Run the pipeline first:  ./start.sh --mode real --steps export"
        )

    html_files = sorted(SRC_DIR.glob("*.html"))
    if not html_files:
        raise SystemExit(f"No .html files in {SRC_DIR}")

    DEST_DIR.mkdir(parents=True, exist_ok=True)
    for src in html_files:
        dst = DEST_DIR / src.name
        shutil.copy2(src, dst)
        print(f"  copied  {src.name}")

    index = DEST_DIR / "index.html"
    index.write_text(_index_html(html_files), encoding="utf-8")
    print(f"  wrote   docs/maps/index.html")
    print(f"\nDone. Commit docs/maps/ and push, then enable GitHub Pages:")
    print(f"  Settings → Pages → Source: Deploy from branch → main / docs")
    print(f"  Your maps will be at:  https://<org>.github.io/<repo>/maps/")


if __name__ == "__main__":
    main()
