from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

import numpy as np
from rank_bm25 import BM25Okapi

from backend.config import DATASET_PATH, MIN_SCORE

DENSE_DIMENSIONS = 384
RRF_K = 60
DENSE_INDEX_PATH = Path(DATASET_PATH).with_name("dense_index.npz")
POLICY_OVERRIDES_PATH = Path(DATASET_PATH).with_name("policy_overrides.json")


def _normalize(text: str) -> str:
    value = unicodedata.normalize("NFKC", str(text or "")).lower()
    value = "".join(ch for ch in unicodedata.normalize("NFD", value) if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", value).strip()


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-zA-ZÀ-ỹ0-9]+", str(text).lower())


def _dense_features(text: str) -> list[str]:
    normalized = _normalize(text)
    tokens = re.findall(r"[a-z0-9]+", normalized)
    features = [f"w:{token}" for token in tokens]
    features.extend(f"b:{left}_{right}" for left, right in zip(tokens, tokens[1:]))
    compact = re.sub(r"[^a-z0-9]", "", normalized)
    features.extend(f"c3:{compact[i:i + 3]}" for i in range(max(0, len(compact) - 2)))
    return features


def _dense_vector(text: str) -> np.ndarray:
    vector = np.zeros(DENSE_DIMENSIONS, dtype=np.float32)
    for feature in _dense_features(text):
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        number = int.from_bytes(digest, "big")
        index = number % DENSE_DIMENSIONS
        sign = 1.0 if number & 1 else -1.0
        vector[index] += sign
    norm = float(np.linalg.norm(vector))
    if norm:
        vector /= norm
    return vector


def _chunk_search_text(chunk: dict) -> str:
    meta = chunk.get("metadata", {}) or {}
    metadata_text = " ".join(
        str(meta.get(key, ""))
        for key in ("title", "source", "doc_id", "path", "news_group", "publisher", "exact_number_symbol")
    )
    return f"{chunk.get('content', '')} {metadata_text}".strip()


@lru_cache(maxsize=1)
def _policy_overrides() -> dict[str, dict]:
    if not POLICY_OVERRIDES_PATH.exists():
        return {}
    value = json.loads(POLICY_OVERRIDES_PATH.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


@lru_cache(maxsize=1)
def load_chunks() -> list[dict]:
    path = Path(DATASET_PATH)
    if not path.exists():
        raise FileNotFoundError(f"Dataset not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("rag_chunks.json must be a list")
    clean = []
    for i, item in enumerate(data):
        content = str(item.get("content", "")).strip()
        metadata = dict(item.get("metadata", {}) or {})
        original_doc_id = str(metadata.get("doc_id") or "")
        override = _policy_overrides().get(original_doc_id)
        if override:
            metadata.update(override)
            old_chunk_id = str(metadata.get("chunk_id") or f"chunk_{i:04d}")
            metadata["chunk_id"] = old_chunk_id.replace("news-", "policy-", 1)
            metadata["canonical_url"] = metadata.get("canonical_url") or metadata.get("url")
            metadata["source_url"] = metadata.get("source_url") or metadata.get("url")
            metadata["link"] = metadata.get("link") or metadata.get("url")
        content = re.sub(r"(?i)\b(?:key context for rag|build production|crawler/local browser|index production|do not use for|use for|summary)\s*:?\s*", " ", content)
        content = re.sub(r"\s+", " ", content).strip(" ,.;:-")
        if not content or len(content) < 40:
            continue
        clean.append({"content": content, "metadata": metadata, "chunk_id": metadata.get("chunk_id") or f"chunk_{i:04d}"})
    return clean


def _dataset_signature(chunks: list[dict]) -> str:
    payload = "|".join(f"{item.get('chunk_id')}:{len(item.get('content', ''))}" for item in chunks)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_dense_index(*, force: bool = False) -> Path:
    """Build and persist the deterministic local dense-vector index."""
    chunks = load_chunks()
    signature = _dataset_signature(chunks)
    if DENSE_INDEX_PATH.exists() and not force:
        try:
            with np.load(DENSE_INDEX_PATH, allow_pickle=False) as data:
                stored = str(data["signature"].item())
                if stored == signature and data["vectors"].shape == (len(chunks), DENSE_DIMENSIONS):
                    return DENSE_INDEX_PATH
        except Exception:
            pass
    vectors = np.vstack([_dense_vector(_chunk_search_text(item)) for item in chunks]).astype(np.float32)
    DENSE_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(DENSE_INDEX_PATH, vectors=vectors, signature=np.array(signature))
    _dense_matrix.cache_clear()
    return DENSE_INDEX_PATH


@lru_cache(maxsize=1)
def _dense_matrix() -> np.ndarray:
    build_dense_index()
    with np.load(DENSE_INDEX_PATH, allow_pickle=False) as data:
        return np.asarray(data["vectors"], dtype=np.float32)


@lru_cache(maxsize=1)
def _bm25() -> BM25Okapi:
    chunks = load_chunks()
    corpus = [_tokens(_chunk_search_text(chunk)) for chunk in chunks]
    return BM25Okapi(corpus)


def dataset_summary() -> dict:
    chunks = load_chunks()
    counts: dict[str, int] = {}
    for chunk in chunks:
        source_type = str(chunk["metadata"].get("source_type") or "unknown")
        counts[source_type] = counts.get(source_type, 0) + 1
    docs = sorted({c["metadata"].get("doc_id") or c["metadata"].get("source") for c in chunks})
    return {
        "dataset_path": str(DATASET_PATH),
        "chunks": len(chunks),
        "legal_chunks": counts.get("legal", 0),
        "policy_chunks": counts.get("policy", 0),
        "news_chunks": counts.get("news", 0),
        "source_type_counts": counts,
        "documents": len([doc for doc in docs if doc]),
        "dense_dimensions": DENSE_DIMENSIONS,
        "dense_index_path": str(DENSE_INDEX_PATH),
    }


LEGAL_INTENT_TERMS = ["quy định", "điều", "khoản", "luật", "nghị định", "thông tư", "pháp lệnh", "bị phạt", "xử phạt", "xử lý", "bị xử lý", "trách nhiệm hình sự", "tội", "khung hình phạt", "vi phạm hành chính", "biện pháp xử lý hành chính", "tàng trữ", "vận chuyển", "mua bán", "sản xuất", "tổ chức sử dụng", "sử dụng trái phép", "cai nghiện bắt buộc", "hồ sơ", "thủ tục"]
POLICY_INTENT_TERMS = ["chính sách", "kế hoạch", "chương trình", "quản lý", "hỗ trợ", "tái hòa nhập", "vay vốn", "giảm cầu", "giảm tác hại", "phòng ngừa"]
NEWS_INTENT_TERMS = ["tin", "tin tức", "mới nhất", "gần đây", "vụ", "chuyên án", "bắt", "khởi tố", "xét xử", "đường dây", "học đường", "thuốc lá điện tử", "xu hướng"]
SANCTION_INTENT_TERMS = ["xử lý", "bị xử lý", "xử phạt", "bị phạt", "mức phạt", "hình phạt", "trách nhiệm hình sự", "vi phạm hành chính", "sử dụng trái phép"]
LEGAL_SIGNAL_TERMS = ["điều", "khoản", "nghị định", "thông tư", "pháp lệnh", "luật", "xử phạt", "vi phạm hành chính", "biện pháp xử lý hành chính", "trách nhiệm hình sự", "cai nghiện bắt buộc", "sử dụng trái phép"]
NEWS_INCIDENT_TERMS = ["khởi tố", "tạm giam", "bắt giữ", "xét xử", "bị cáo", "đối tượng", "đường dây", "chuyên án", "thu giữ", "karaoke", "triệt phá"]


def _query_intent(query: str) -> str:
    q = str(query).lower()
    scores = {
        "legal": sum(1 for term in LEGAL_INTENT_TERMS if term in q),
        "policy": sum(1 for term in POLICY_INTENT_TERMS if term in q),
        "news": sum(1 for term in NEWS_INTENT_TERMS if term in q),
    }
    intent, score = max(scores.items(), key=lambda item: item[1])
    return intent if score > 0 else "general"


def _is_sanction_query(query: str) -> bool:
    q = str(query).lower()
    return any(term in q for term in SANCTION_INTENT_TERMS)


def _expanded_query(query: str) -> str:
    if not _is_sanction_query(query):
        return str(query)
    return str(query) + " xử phạt vi phạm hành chính biện pháp xử lý hành chính cai nghiện bắt buộc pháp lệnh nghị định luật phòng chống ma túy trách nhiệm hình sự điều khoản"


def _source_boost(intent: str, source_type: str, sanction_query: bool = False) -> float:
    source_type = (source_type or "unknown").lower()
    if sanction_query:
        return {"legal": 2.35, "policy": 0.75, "news": 0.35}.get(source_type, 0.5)
    matrix = {
        "legal": {"legal": 1.65, "policy": 0.95, "news": 0.62},
        "policy": {"policy": 1.7, "legal": 1.05, "news": 0.72},
        "news": {"news": 1.35, "policy": 1.05, "legal": 0.92},
    }
    return matrix.get(intent, {}).get(source_type, 1.0)


def _metadata_blob(meta: dict) -> str:
    return " ".join(str(meta.get(key, "")) for key in ["title", "source", "doc_id", "path", "news_group"]).lower()


def _rank_positions(scores: dict[int, float]) -> dict[int, int]:
    ranked = sorted(scores.items(), key=lambda item: float(item[1]), reverse=True)
    return {index: rank for rank, (index, score) in enumerate(ranked, 1) if float(score) > 0}


def retrieve_bm25(query: str, top_k: int = 6, source_types: tuple[str, ...] | None = None) -> list[dict]:
    """Sparse BM25 baseline retained for regression evaluation."""
    chunks = load_chunks()
    expanded = _expanded_query(query)
    raw_scores = _bm25().get_scores(_tokens(expanded))
    intent = _query_intent(query)
    sanction_query = _is_sanction_query(query)
    query_terms = [token for token in _tokens(expanded) if len(token) >= 4]
    allowed_sources = {value.lower() for value in source_types or ()}
    scored: list[tuple[int, float]] = []
    for index, item in enumerate(chunks):
        meta = item.get("metadata", {}) or {}
        source_type = str(meta.get("source_type") or meta.get("type") or "unknown").lower()
        if allowed_sources and source_type not in allowed_sources:
            continue
        title_blob = _metadata_blob(meta)
        blob = title_blob + " " + str(item.get("content", "")).lower()[:1200]
        score = max(float(raw_scores[index]), 0.0) * _source_boost(intent, source_type, sanction_query)
        score += sum(1 for token in query_terms if token in title_blob) * 0.18
        if intent == "legal" or sanction_query:
            score += sum(1 for term in LEGAL_SIGNAL_TERMS if term in blob) * (0.28 if sanction_query else 0.18)
        if sanction_query and source_type == "news":
            score -= sum(1 for term in NEWS_INCIDENT_TERMS if term in blob) * 0.35
        if score > 0:
            scored.append((index, score))
    scored.sort(key=lambda item: item[1], reverse=True)
    max_score = max((score for _, score in scored), default=0.0)
    results: list[dict] = []
    seen_docs: set[str] = set()
    for index, score in scored:
        relative = score / max_score if max_score else 0.0
        if relative < MIN_SCORE:
            continue
        item = dict(chunks[index])
        meta = item.get("metadata", {}) or {}
        doc_key = str(meta.get("doc_id") or meta.get("source_id") or item.get("chunk_id"))
        if doc_key in seen_docs:
            continue
        seen_docs.add(doc_key)
        item.update(score=round(relative, 4), sparse_score=round(score, 4), retrieval_mode="bm25")
        results.append(item)
        if len(results) >= max(top_k, 1):
            break
    return results


def retrieve(query: str, top_k: int = 6, source_types: tuple[str, ...] | None = None) -> list[dict]:
    """Hybrid BM25+dense retrieval with reciprocal-rank fusion and source controls."""
    chunks = load_chunks()
    expanded = _expanded_query(query)
    sparse_raw = _bm25().get_scores(_tokens(expanded))
    dense_raw = _dense_matrix() @ _dense_vector(expanded)
    intent = _query_intent(query)
    sanction_query = _is_sanction_query(query)
    query_terms = [token for token in _tokens(expanded) if len(token) >= 4]
    allowed_sources = {value.lower() for value in source_types or ()}

    sparse_scores: dict[int, float] = {}
    dense_scores: dict[int, float] = {}
    for index, item in enumerate(chunks):
        meta = item.get("metadata", {}) or {}
        source_type = str(meta.get("source_type") or meta.get("type") or "unknown").lower()
        if allowed_sources and source_type not in allowed_sources:
            continue
        boost = _source_boost(intent, source_type, sanction_query)
        title_blob = _metadata_blob(meta)
        blob = title_blob + " " + str(item.get("content", "")).lower()[:1200]
        sparse = max(float(sparse_raw[index]), 0.0) * boost
        sparse += sum(1 for token in query_terms if token in title_blob) * 0.18
        if intent == "legal" or sanction_query:
            sparse += sum(1 for term in LEGAL_SIGNAL_TERMS if term in blob) * (0.28 if sanction_query else 0.18)
        if sanction_query and source_type == "news":
            sparse -= sum(1 for term in NEWS_INCIDENT_TERMS if term in blob) * 0.35
        dense = max(float(dense_raw[index]), 0.0) * math.sqrt(max(boost, 0.1))
        sparse_scores[index] = max(sparse, 0.0)
        dense_scores[index] = dense

    sparse_ranks = _rank_positions(sparse_scores)
    dense_ranks = _rank_positions(dense_scores)
    candidates = set(sparse_ranks) | set(dense_ranks)
    fused: list[tuple[int, float]] = []
    for index in candidates:
        score = 0.0
        if index in sparse_ranks:
            score += 0.58 / (RRF_K + sparse_ranks[index])
        if index in dense_ranks:
            score += 0.42 / (RRF_K + dense_ranks[index])
        fused.append((index, score))
    fused.sort(key=lambda item: item[1], reverse=True)
    max_fused = max((score for _, score in fused), default=0.0)
    if max_fused <= 0:
        return []

    results: list[dict] = []
    seen_docs: set[str] = set()
    for index, fused_score in fused:
        relative = fused_score / max_fused
        if relative < MIN_SCORE:
            continue
        item = dict(chunks[index])
        meta = item.get("metadata", {}) or {}
        doc_key = str(meta.get("doc_id") or meta.get("source_id") or item.get("chunk_id"))
        if doc_key in seen_docs:
            continue
        seen_docs.add(doc_key)
        item.update(
            score=round(relative, 4),
            sparse_score=round(float(sparse_scores.get(index, 0.0)), 4),
            dense_score=round(float(dense_scores.get(index, 0.0)), 4),
            rrf_score=round(float(fused_score), 6),
            retrieval_mode="hybrid_rrf",
            retrieval_intent=intent,
            sanction_query=sanction_query,
        )
        results.append(item)
        if len(results) >= max(top_k, 1):
            break
    return results
