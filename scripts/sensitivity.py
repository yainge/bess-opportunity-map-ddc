"""Run the weight-sensitivity checks on the integrated real (or demo) node table.

Usage:
    uv run python scripts/sensitivity.py --mode real [--draws 500] [--rel 0.2] [--top-k 10]

Reads <processed_root>/integrate/nodes_integrated.csv and config/scoring.yaml and writes
<results_root>/tables/sensitivity_rank_stability.csv and sensitivity_leave_one_out.csv.
Exploratory: weights are illustrative, so this shows dependence on them, not validity.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
import yaml

from bess_catalonia.scoring.sensitivity import run_all

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mode", choices=["demo", "real"], default="real")
    ap.add_argument("--draws", type=int, default=500)
    ap.add_argument("--rel", type=float, default=0.2)
    ap.add_argument("--top-k", type=int, default=10)
    args = ap.parse_args()

    project = yaml.safe_load((ROOT / "config" / "project.yaml").read_text())
    paths = project["modes"][args.mode]
    cfg = yaml.safe_load((ROOT / "config" / "scoring.yaml").read_text())
    nodes = pd.read_csv(ROOT / paths["processed_root"] / "integrate" / "nodes_integrated.csv")

    stab, loo = run_all(nodes, cfg, n_draws=args.draws, rel=args.rel, top_k=args.top_k)
    out = ROOT / paths["results_root"] / "tables"
    out.mkdir(parents=True, exist_ok=True)
    stab.to_csv(out / "sensitivity_rank_stability.csv", index=False)
    loo.to_csv(out / "sensitivity_leave_one_out.csv", index=False)
    print(f"Wrote {out / 'sensitivity_rank_stability.csv'} and sensitivity_leave_one_out.csv")


if __name__ == "__main__":
    main()
