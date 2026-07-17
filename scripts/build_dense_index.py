#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.dataset import DENSE_DIMENSIONS, build_dense_index, dataset_summary

if __name__ == "__main__":
    path = build_dense_index(force=True)
    summary = dataset_summary()
    print(f"dense index OK: path={path} dimensions={DENSE_DIMENSIONS} chunks={summary['chunks']}")
