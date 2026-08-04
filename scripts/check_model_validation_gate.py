#!/usr/bin/env python3
"""Evaluate the independent vehicle-model gate for one resolved profile."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.solar_sim import evaluate_model_validation_gate  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    profile = args.profile.resolve()
    cfg = yaml.safe_load(profile.read_text(encoding="utf-8")) or {}
    result = evaluate_model_validation_gate(cfg, profile)
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload + "\n", encoding="utf-8", newline="\n")
    print(payload)
    return 0 if bool(result.get("gate_pass", False)) else 2


if __name__ == "__main__":
    raise SystemExit(main())
