#!/usr/bin/env python3
"""Merge parallel per-seed exact-replay rankings and select the fastest feasible policy."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import pandas as pd


def parse_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--stage", required=True)
    args = parser.parse_args()

    ranking_paths = sorted(
        args.input_root.resolve().glob("seed_*/exact_1hz_candidate_ranking.csv")
    )
    if not ranking_paths:
        raise FileNotFoundError(f"No per-seed exact rankings under {args.input_root}")

    frames = [pd.read_csv(path) for path in ranking_paths]
    ranking = pd.concat(frames, ignore_index=True)
    ranking["feasible"] = ranking["feasible"].map(parse_bool)
    ranking = ranking.sort_values(
        ["feasible", "elapsed_hours"],
        ascending=[False, True],
        na_position="last",
        kind="stable",
    )

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    ranking.to_csv(output / "exact_1hz_candidate_ranking.csv", index=False)
    feasible = ranking.loc[ranking["feasible"]]
    selection = {
        "scope": "parallel per-seed fixed-policy exact 1 Hz simulation ranking",
        "source_stage": args.stage,
        "candidate_count": int(len(ranking)),
        "feasible_candidate_count": int(len(feasible)),
        "selected": False,
        "ranking_sources": [str(path) for path in ranking_paths],
    }
    if not feasible.empty:
        winner = feasible.iloc[0]
        selected_policy = output / "selected_exact_policy.csv"
        shutil.copy2(Path(str(winner["policy_csv"])), selected_policy)
        selection.update(
            {
                "selected": True,
                "selected_seed": str(winner["seed_label"]),
                "selected_policy_csv": str(selected_policy),
                "selected_manifest_json": str(winner["manifest_json"]),
                "elapsed_hours": float(winner["elapsed_hours"]),
                "final_soc": float(winner["final_soc"]),
            }
        )

    (output / "exact_selection.json").write_text(
        json.dumps(selection, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(selection, indent=2, ensure_ascii=False))
    return 0 if selection["selected"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
