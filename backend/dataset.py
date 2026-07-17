from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from rank_bm25 import BM25Okapi

from backend.config import DATASET_PATH, MIN_SCORE


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-zA-ZÀ-ỹ0-9]+", str(text).lower())


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
        metadata = item.get("metadata", {}) or {}
        content = re.sub(r"(?im)^.*(?:use for|do not use|build production|crawler/local browser|index production|key context for rag|summary:).*$", "", content)
        content = re.sub(r"\s+", " ", content).strip(" ,.;:-")
        if not content or len(content) < 40:
            continue
        clean.append({"content": content, "metadata": metadata, "chunk_id": metadata.get("chunk_id") or f"chunk_{i:04d}"})
    return clean


@lru_cache(maxsize=1)
def _bm25() -> BM25Okapi:
    chunks = load_chunks()
    corpus = [_tokens(c["content"] + " " + " ".join(str(v) for v in c["metadata"].values())) for c in chunks]
    return BM25Okapi(corpus)


def dataset_summary() -> dict:
    chunks = load_chunks()
    legal = sum(1 for c in chunks if c["metadata"].get("source_type") == "legal")
    news = sum(1 for c in chunks if c["metadata"].get("source_type") == "news")
    docs = sorted({c["metadata"].get("doc_id") or c["metadata"].get("source") for c in chunks})
    return {"dataset_path": str(DATASET_PATH), "chunks": len(chunks), "legal_chunks": legal, "news_chunks": news, "documents": len([d for d in docs if d])}


LEGAL_INTENT_TERMS = ["quy định", "điều", "khoản", "luật", "nghị định", "thông tư", "pháp lệnh", "bị phạt", "xử phạt", "xử lý", "bị xử lý", "trách nhiệm hình sự", "tội", "khung hình phạt", "vi phạm hành chính", "biện pháp xử lý hành chính", "tàng trữ", "vận chuyển", "mua bán", "sản xuất", "tổ chức sử dụng", "sử dụng trái phép", "cai nghiện bắt buộc", "hồ sơ", "thủ tục"]
NEWS_INTENT_TERMS = ["tin", "tin tức", "mới nhất", "gần đây", "vụ", "chuyên án", "bắt", "khởi tố", "xét xử", "đường dây", "học đường", "thuốc lá điện tử", "xu hướng"]
SANCTION_INTENT_TERMS = ["xử lý", "bị xử lý", "xử phạt", "bị phạt", "mức phạt", "hình phạt", "trách nhiệm hình sự", "vi phạm hành chính", "sử dụng trái phép"]
LEGAL_SIGNAL_TERMS = ["điều", "khoản", "nghị định", "thông tư", "pháp lệnh", "luật", "xử phạt", "vi phạm hành chính", "biện pháp xử lý hành chính", "trách nhiệm hình sự", "cai nghiện bắt buộc", "sử dụng trái phép"]
NEWS_INCIDENT_TERMS = ["khởi tố", "tạm giam", "bắt giữ", "xét xử", "bị cáo", "đối tượng", "đường dây", "chuyên án", "thu giữ", "karaoke", "triệt phá"]


def _query_intent(query: str) -> str:
    q = str(query).lower()
    legal_hits = sum(1 for term in LEGAL_INTENT_TERMS if term in q)
    news_hits = sum(1 for term in NEWS_INTENT_TERMS if term in q)
    if news_hits > legal_hits and news_hits > 0:
        return "news"
    if legal_hits > 0:
        return "legal"
    return "general"


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
        if source_type == "legal": return 2.35
        if source_type == "news": return 0.35
    if intent == "legal":
        if source_type == "legal": return 1.65
        if source_type == "news": return 0.62
    if intent == "news":
        if source_type == "news": return 1.35
        if source_type == "legal": return 0.92
    return 1.0


def _metadata_blob(meta: dict) -> str:
    return " ".join(str(meta.get(k, "")) for k in ["title", "source", "doc_id", "path", "news_group"]).lower()


def retrieve(query: str, top_k: int = 6, source_types: tuple[str, ...] | None = None) -> list[dict]:
    chunks = load_chunks()
    raw_scores = _bm25().get_scores(_tokens(_expanded_query(query)))
    intent = _query_intent(query)
    sanction_query = _is_sanction_query(query)
    search_query = _expanded_query(query)
    query_terms = [t for t in _tokens(search_query) if len(t) >= 4]
    scored = []
    allowed_sources = {value.lower() for value in source_types or ()}
    for idx, raw_score in enumerate(raw_scores):
        item = chunks[idx]
        meta = item.get("metadata", {}) or {}
        source_type = meta.get("source_type") or meta.get("type") or "unknown"
        if allowed_sources and str(source_type).lower() not in allowed_sources:
            continue
        title_blob = _metadata_blob(meta)
        blob = title_blob + " " + str(item.get("content", "")).lower()[:1200]
        adjusted_score = float(raw_score) * _source_boost(intent, source_type, sanction_query)
        adjusted_score += sum(1 for t in query_terms if t in title_blob) * 0.18
        if intent == "legal" or sanction_query:
            adjusted_score += sum(1 for term in LEGAL_SIGNAL_TERMS if term in blob) * (0.28 if sanction_query else 0.18)
        if sanction_query and source_type.lower() == "news":
            adjusted_score -= sum(1 for term in NEWS_INCIDENT_TERMS if term in blob) * 0.35
        scored.append((idx, adjusted_score))
    positive = [(idx, score) for idx, score in sorted(scored, key=lambda x: float(x[1]), reverse=True) if float(score) > 0]
    max_score = max([float(score) for _, score in positive], default=0.0)
    if max_score <= 0:
        return []
    results = []
    seen_docs: set[str] = set()
    for idx, raw_score in positive:
        relative = max(float(raw_score), 0.0) / max_score
        if relative < MIN_SCORE:
            continue
        item = dict(chunks[idx])
        meta = item.get("metadata", {}) or {}
        doc_key = str(meta.get("doc_id") or meta.get("source_id") or item.get("chunk_id"))
        if doc_key in seen_docs:
            continue
        seen_docs.add(doc_key)
        item.update(score=round(relative, 4), raw_score=round(float(raw_score), 4), retrieval_intent=intent, sanction_query=sanction_query)
        results.append(item)
        if len(results) >= max(top_k, 1):
            break
    return results
