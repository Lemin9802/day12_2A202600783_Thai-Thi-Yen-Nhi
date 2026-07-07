#!/usr/bin/env python3
"""
validate_dataset_manifest.py

Validates that dataset_manifest.json matches the actual rag_chunks.json.
Run before committing any dataset changes.

Usage:
    python scripts/validate_dataset_manifest.py
    python scripts/validate_dataset_manifest.py --fix   # auto-rewrite manifest

Exit codes:
    0 - manifest matches index
    1 - mismatch found (or fix applied, re-run to confirm)
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT          = Path(__file__).resolve().parents[1]
CHUNKS_PATH   = ROOT / "data" / "maithuylaw_dataset" / "data" / "index" / "rag_chunks.json"
MANIFEST_PATH = ROOT / "data" / "maithuylaw_dataset" / "data" / "index" / "dataset_manifest.json"

SCOPE_NOTE = (
    "Strict 2025-2026 dataset for MaiThuyLaw AI. "
    "Includes Vietnam drug-related legal documents, policy, and verified news "
    "from 2025 onward only. "
    "Scope is intentionally limited to 2025-2026; earlier legislation "
    "(e.g. BLHS 2015) is excluded. "
    "Chatbot returns evidence_level=insufficient when sources are unavailable."
)

# Doc IDs that must NOT appear in rag_chunks.json (out of 2025+ scope)
OUT_OF_SCOPE_IDS = {
    "legal-bo-luat-hinh-su-2015",
}


def load_chunks() -> list[dict]:
    if not CHUNKS_PATH.exists():
        print(f"ERROR: chunks file not found: {CHUNKS_PATH}", file=sys.stderr)
        sys.exit(1)
    return json.loads(CHUNKS_PATH.read_text(encoding="utf-8"))


def build_index(chunks: list[dict]) -> dict[str, dict]:
    docs: dict = defaultdict(lambda: {"chunks": 0, "source_type": "", "title": ""})
    for c in chunks:
        meta = c.get("metadata", {})
        doc_id = meta.get("doc_id", "")
        if not doc_id:
            continue
        docs[doc_id]["chunks"] += 1
        if not docs[doc_id]["source_type"]:
            docs[doc_id]["source_type"] = meta.get("source_type", "")
        if not docs[doc_id]["title"]:
            docs[doc_id]["title"] = (
                meta.get("title") or meta.get("source_title")
                or meta.get("source") or doc_id
            )
    return dict(docs)


def build_manifest_dict(docs: dict[str, dict]) -> dict:
    def sort_key(item):
        return (0 if item[1]["source_type"] == "legal" else 1, item[0])

    sorted_docs = sorted(docs.items(), key=sort_key)
    total = sum(v["chunks"] for v in docs.values())
    st: dict[str, int] = defaultdict(int)
    for v in docs.values():
        st[v["source_type"]] += v["chunks"]

    return {
        "name": "maithuylaw_dataset",
        "scope": "vietnam_2025_plus_strict",
        "description": SCOPE_NOTE,
        "chunks": total,
        "documents": len(docs),
        "source_type_counts": dict(st),
        "docs": [
            {
                "doc_id": did,
                "title": info["title"],
                "source_type": info["source_type"],
                "chunks": info["chunks"],
            }
            for did, info in sorted_docs
        ],
    }


def validate(fix: bool = False) -> int:
    chunks = load_chunks()
    actual = build_index(chunks)
    expected = build_manifest_dict(actual)
    errors: list[str] = []

    # Check for out-of-scope docs already in the index
    for doc_id in actual:
        if doc_id in OUT_OF_SCOPE_IDS:
            errors.append(f"OUT_OF_SCOPE doc in index (remove it): {doc_id}")

    # Load current manifest
    if not MANIFEST_PATH.exists():
        errors.append("manifest file missing")
        if fix:
            MANIFEST_PATH.write_text(
                json.dumps(expected, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print("FIXED: manifest created from index")
        else:
            print("VALIDATION FAILED:")
            for e in errors:
                print(f"  ERROR: {e}")
        return 1

    current = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    # Top-level counts
    for field in ("chunks", "documents"):
        if current.get(field) != expected[field]:
            errors.append(
                f"{field}: manifest={current.get(field)} actual={expected[field]}"
            )

    if current.get("source_type_counts") != expected["source_type_counts"]:
        errors.append(
            f"source_type_counts: manifest={current.get('source_type_counts')} "
            f"actual={expected['source_type_counts']}"
        )

    # Doc presence
    current_ids = {d["doc_id"] for d in current.get("docs", [])}
    actual_ids  = set(actual.keys())
    for did in sorted(current_ids - actual_ids):
        errors.append(f"doc in manifest but NOT in index (stale): {did}")
    for did in sorted(actual_ids - current_ids):
        errors.append(f"doc in index but NOT in manifest (missing): {did}")

    # Per-doc chunk counts
    current_map = {d["doc_id"]: d for d in current.get("docs", [])}
    for did, info in actual.items():
        if did in current_map and current_map[did]["chunks"] != info["chunks"]:
            errors.append(
                f"chunk count for {did}: manifest={current_map[did]['chunks']} actual={info['chunks']}"
            )

    if not errors:
        print("manifest OK")
        print(f"  chunks={expected['chunks']}, documents={expected['documents']}, "
              f"source_type_counts={expected['source_type_counts']}")
        return 0

    print("VALIDATION FAILED:")
    for e in errors:
        print(f"  ERROR: {e}")

    if fix:
        MANIFEST_PATH.write_text(
            json.dumps(expected, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print("\nFIXED: manifest rewritten from index. Re-run to confirm.")
    else:
        print("\nRun with --fix to auto-rewrite manifest from index.")
    return 1


def main():
    p = argparse.ArgumentParser(description="Validate dataset_manifest.json vs rag_chunks.json")
    p.add_argument("--fix", action="store_true", help="Auto-rewrite manifest from index")
    args = p.parse_args()
    sys.exit(validate(fix=args.fix))


if __name__ == "__main__":
    main()
