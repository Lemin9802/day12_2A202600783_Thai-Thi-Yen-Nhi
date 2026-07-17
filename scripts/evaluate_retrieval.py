#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.dataset import retrieve, retrieve_bm25

DEFAULT_QUERIES = ROOT / "tests" / "fixtures" / "retrieval_queries.json"


def evaluate(path: Path, top_k: int = 5) -> dict:
    cases = json.loads(path.read_text(encoding="utf-8"))
    metrics = {}
    for name, fn in (("bm25", retrieve_bm25), ("hybrid", retrieve)):
        hits_at_3 = 0
        hits_at_5 = 0
        reciprocal_rank = 0.0
        rows = []
        for case in cases:
            results = fn(case["query"], top_k=top_k, source_types=tuple(case.get("source_types") or ()))
            ids = [(item.get("metadata") or {}).get("doc_id") for item in results]
            expected = case["expected_doc_id"]
            rank = ids.index(expected) + 1 if expected in ids else None
            hits_at_3 += int(rank is not None and rank <= 3)
            hits_at_5 += int(rank is not None and rank <= 5)
            reciprocal_rank += 1.0 / rank if rank else 0.0
            rows.append({"query": case["query"], "expected": expected, "rank": rank, "top_ids": ids})
        total = max(len(cases), 1)
        metrics[name] = {
            "queries": len(cases),
            "recall_at_3": round(hits_at_3 / total, 4),
            "recall_at_5": round(hits_at_5 / total, 4),
            "mrr": round(reciprocal_rank / total, 4),
            "rows": rows,
        }
    return metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--queries", type=Path, default=DEFAULT_QUERIES)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = evaluate(args.queries)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for name, values in result.items():
            print(f"{name}: R@3={values['recall_at_3']:.3f} R@5={values['recall_at_5']:.3f} MRR={values['mrr']:.3f}")
