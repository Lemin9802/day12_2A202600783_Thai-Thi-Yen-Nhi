from pathlib import Path

from backend.dataset import dataset_summary, retrieve
from scripts.evaluate_retrieval import evaluate


def test_policy_corpus_and_hybrid_metadata_exist():
    summary = dataset_summary()
    assert summary["policy_chunks"] >= 10
    results = retrieve("chính sách vay vốn cho người sau cai nghiện", top_k=3, source_types=("policy", "legal"))
    assert results
    assert results[0]["retrieval_mode"] == "hybrid_rrf"
    assert "dense_score" in results[0] and "sparse_score" in results[0]
    assert (results[0].get("metadata") or {}).get("source_type") == "policy"


def test_hybrid_retrieval_meets_small_grounded_benchmark():
    fixture = Path(__file__).parent / "fixtures" / "retrieval_queries.json"
    metrics = evaluate(fixture)
    assert metrics["hybrid"]["recall_at_3"] >= 0.8
    assert metrics["hybrid"]["recall_at_5"] == 1.0
    assert metrics["hybrid"]["mrr"] >= metrics["bm25"]["mrr"]
