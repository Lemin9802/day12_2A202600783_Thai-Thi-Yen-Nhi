from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    language: str = "vi"
    chat_id: str | None = None
    user_id: str = "demo-user"
    attachment_ids: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)


class Source(BaseModel):
    title: str
    source_type: str = ""
    canonical_url: str | None = None
    url: str | None = None
    publisher: str | None = None
    official_domain: str | None = None
    doc_id: str | None = None
    source_id: str | None = None
    snippet: str | None = None
    source_type_label: str | None = None
    score: float | None = None


class ChatResponse(BaseModel):
    answer: str
    chat_id: str
    sources: list[dict] = Field(default_factory=list)
    refused: bool = False
    reason: str | None = None
    evidence_level: str | None = None
    confidence: float | None = None
    safety: dict = Field(default_factory=dict)
    follow_up_suggestions: list[str] = Field(default_factory=list)

    def model_post_init(self, __context) -> None:
        self.answer = _clean_answer_text(_repair_text(self.answer) or "")
        self.reason = _repair_text(self.reason)
        self.evidence_level = _repair_text(self.evidence_level)
        self.sources = _normalize_product_sources(self.sources)

        if not self.evidence_level:
            self.evidence_level = _infer_evidence_level(
                sources=self.sources,
                refused=self.refused,
                reason=self.reason,
                answer=self.answer,
            )

        if self.confidence is None:
            self.confidence = _infer_confidence(self.evidence_level, self.sources)

        if not self.safety:
            self.safety = _infer_safety(self.refused, self.reason, self.evidence_level)
        else:
            self.safety = _repair_text_values(self.safety)

        if not self.follow_up_suggestions:
            self.follow_up_suggestions = _suggest_followups(
                self.answer,
                self.evidence_level,
                self.refused,
                self.reason,
            )
        else:
            self.follow_up_suggestions = [_repair_text(item) or "" for item in self.follow_up_suggestions]


def _looks_mojibake(value: str) -> bool:
    if not value:
        return False
    markers = ("Ã", "Â", "Ä", "Æ", "Ð", "áº", "á»", "â€", "ï¿½")
    return any(marker in value for marker in markers) or bool(re.search(r"[\u0080-\u009f]", value))


def _mojibake_score(value: str) -> int:
    if not value:
        return 0
    score = 0
    for marker in ("Ã", "Â", "Ä", "Æ", "Ð", "áº", "á»", "â€", "ï¿½", "�"):
        score += value.count(marker) * 4
    score += len(re.findall(r"[\u0080-\u009f]", value)) * 3
    return score


def _repair_text(value: Any) -> Any:
    if not isinstance(value, str) or not _looks_mojibake(value):
        return value

    candidates = [value]
    for encoding in ("cp1252", "latin1"):
        try:
            candidates.append(value.encode(encoding).decode("utf-8"))
        except Exception:
            try:
                candidates.append(value.encode(encoding, errors="ignore").decode("utf-8", errors="ignore"))
            except Exception:
                pass

    best = min(candidates, key=lambda s: (_mojibake_score(s), -len(s)))
    return best if _mojibake_score(best) < _mojibake_score(value) else value


def _repair_text_values(value: Any) -> Any:
    if isinstance(value, str):
        return _repair_text(value)
    if isinstance(value, list):
        return [_repair_text_values(item) for item in value]
    if isinstance(value, dict):
        return {key: _repair_text_values(item) for key, item in value.items()}
    return value


def _first_visible_char(value: str) -> str:
    text = value.strip().lstrip("-•*0123456789. )(").strip()
    return text[:1]


def _clean_answer_text(value: str) -> str:
    if not value:
        return ""

    text = value.replace("\r\n", "\n")
    text = re.sub(r"\s+\*\*Source:\*\*.*", "", text)
    text = re.sub(r"\s+\*\*Date:\*\*.*", "", text)
    text = re.sub(r"\s+\*\*URL:\*\*\s*https?://\S+", "", text)
    text = re.sub(r"\s+\*\*Group:\*\*.*", "", text)
    text = re.sub(r"https?://\S+", "", text)

    # Source cards already carry references, so keep the legal note but remove
    # duplicated raw reference lists from the prose answer.
    text = re.sub(r"\n##\s*Nguồn tham khảo\s*\n.*?(?=\n##\s*Lưu ý|\Z)", "\n", text, flags=re.S)
    text = re.sub(r"\n##\s*References\s*\n.*?(?=\n##\s*Note|\Z)", "\n", text, flags=re.S | re.I)

    kept: list[str] = []
    for raw_line in text.split("\n"):
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            kept.append("")
            continue

        if stripped.startswith(("- ", "* ", "• ")):
            body = stripped[2:].strip()
            first = _first_visible_char(body)
            if first and first.islower():
                continue
            if len(body) < 35:
                continue
            if body.endswith(("xác đ.", "xác định.", "Group:.")):
                continue

        kept.append(line)

    text = "\n".join(kept)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def _is_low_quality_snippet(value: str | None) -> bool:
    if not value:
        return True
    text = str(value).strip()
    if len(text) < 25:
        return True
    if "---" in text:
        return True
    if re.search(r"\b[a-z]+-[a-z]+-[a-z]+", text.lower()):
        return True

    letters = re.findall(r"[A-Za-zÀ-ỹ]", text)
    if len(letters) >= 80:
        accented = re.findall(r"[À-ỹ]", text)
        lower = text.lower()
        unaccented_legal_hits = sum(
            1
            for token in (
                "quyet", "dinh", "chinh", "phu", "cong", "hoa", "nghia",
                "doc", "lap", "tu", "hanh", "phuc", "luat", "ma", "tuy",
                "khong", "trong", "diem", "phuc", "tap",
            )
            if token in lower
        )
        if len(accented) / max(len(letters), 1) < 0.02 and unaccented_legal_hits >= 4:
            return True

    return False


@lru_cache(maxsize=1)
def _dataset_snippet_registry() -> dict[str, dict]:
    dataset_path = Path(__file__).resolve().parents[1] / "data" / "maithuylaw_dataset" / "data" / "index" / "rag_chunks.json"
    registry: dict[str, dict] = {}
    try:
        chunks = json.loads(dataset_path.read_text(encoding="utf-8"))
    except Exception:
        return registry

    if not isinstance(chunks, list):
        return registry

    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        meta = chunk.get("metadata") or {}
        if not isinstance(meta, dict):
            meta = {}
        content = _compact_snippet(chunk.get("content"))
        keys = [
            meta.get("doc_id"),
            meta.get("source_id"),
            meta.get("chunk_id"),
            chunk.get("doc_id"),
        ]
        item = {
            "snippet": content,
            "publisher": meta.get("publisher") or chunk.get("publisher"),
            "official_domain": meta.get("official_domain") or chunk.get("official_domain"),
            "source_type": meta.get("source_type") or meta.get("type") or chunk.get("source_type"),
            "url": meta.get("canonical_url") or meta.get("url") or meta.get("source_url") or chunk.get("url"),
        }
        for key in keys:
            key = str(key or "").strip()
            if key and key not in registry:
                registry[key] = item
    return registry


def _compact_snippet(value: Any, limit: int = 280) -> str | None:
    if not isinstance(value, str):
        return None
    text = _clean_answer_text(_repair_text(value) or "")
    text = " ".join(text.split())
    if not text or _is_low_quality_snippet(text):
        return None
    return text[:limit]


def _normalize_product_sources(sources: list[dict]) -> list[dict]:
    registry = _dataset_snippet_registry()
    normalized: list[dict] = []
    for idx, raw in enumerate(sources or [], start=1):
        if not isinstance(raw, dict):
            continue

        doc_id = raw.get("doc_id") or raw.get("source_id")
        reg = registry.get(str(doc_id or ""), {})
        source_type = str(raw.get("source_type") or raw.get("type") or reg.get("source_type") or "").strip()
        url = raw.get("canonical_url") or raw.get("url") or raw.get("source_url") or raw.get("link") or reg.get("url")
        title = _repair_text(raw.get("title") or raw.get("source_title") or raw.get("doc_id") or f"Nguồn {idx}")
        snippet = _compact_snippet(raw.get("snippet") or raw.get("preview") or raw.get("excerpt") or raw.get("content") or reg.get("snippet"))
        if _is_low_quality_snippet(snippet) and isinstance(title, str):
            snippet = title

        item = {
            "source_id": raw.get("source_id") or f"S{idx}",
            "title": title,
            "source_type": source_type or None,
            "source_type_label": _source_type_label(source_type),
            "publisher": _repair_text(raw.get("publisher") or reg.get("publisher")),
            "official_domain": raw.get("official_domain") or reg.get("official_domain"),
            "url": url,
            "canonical_url": url,
            "doc_id": doc_id,
            "snippet": snippet,
        }
        normalized.append({k: v for k, v in item.items() if v not in (None, "")})
    return normalized


def _source_type_label(source_type: str) -> str:
    value = (source_type or "").lower()
    if "legal" in value:
        return "Văn bản pháp luật"
    if "news" in value:
        return "Tin chính thống"
    if "policy" in value or "chinh" in value:
        return "Chính sách"
    if "attachment" in value:
        return "Nguồn đính kèm"
    return "Nguồn tham khảo"


def _infer_evidence_level(sources: list[dict], refused: bool, reason: str | None, answer: str) -> str:
    reason_text = (reason or "").lower()
    answer_text = (answer or "").lower()

    if refused:
        if "out_of_domain" in reason_text or "ngoài phạm vi" in answer_text or "chỉ hỗ trợ tra cứu" in answer_text:
            return "Ngoài phạm vi hỗ trợ"
        return "Câu hỏi nhạy cảm"

    if not sources:
        return "Chưa đủ căn cứ"

    has_legal = any("legal" in str(s.get("source_type") or "").lower() for s in sources)
    has_official = any(
        any(domain in str(s.get("url") or s.get("canonical_url") or s.get("official_domain") or "").lower()
            for domain in ("vbpl.vn", "chinhphu.vn", "bocongan.gov.vn", "moj.gov.vn", "congbao.chinhphu.vn"))
        for s in sources
    )

    if has_legal and has_official:
        return "Căn cứ rõ"
    return "Cần kiểm tra thêm"


def _infer_confidence(evidence_level: str | None, sources: list[dict]) -> float:
    if evidence_level == "Căn cứ rõ":
        return 0.82
    if evidence_level == "Cần kiểm tra thêm":
        return 0.58
    if evidence_level == "Chưa đủ căn cứ":
        return 0.25
    if evidence_level == "Ngoài phạm vi hỗ trợ":
        return 0.95
    if evidence_level == "Câu hỏi nhạy cảm":
        return 0.95
    return 0.4 if sources else 0.2


def _infer_safety(refused: bool, reason: str | None, evidence_level: str | None) -> dict:
    if evidence_level == "Câu hỏi nhạy cảm":
        category = "sensitive_or_unsafe"
    elif evidence_level == "Ngoài phạm vi hỗ trợ":
        category = "out_of_scope"
    else:
        category = "safe"
    return {"refused": refused, "category": category, "reason": reason}


def _suggest_followups(answer: str, evidence_level: str | None, refused: bool, reason: str | None) -> list[str]:
    text = (answer or "").lower()

    if refused and evidence_level == "Câu hỏi nhạy cảm":
        return [
            "Quy định pháp luật liên quan là gì?",
            "Hậu quả pháp lý có thể phát sinh như thế nào?",
        ]

    if evidence_level == "Ngoài phạm vi hỗ trợ":
        return [
            "Sử dụng trái phép chất ma túy bị xử lý thế nào?",
            "Cai nghiện bắt buộc được quy định ra sao?",
        ]

    if evidence_level == "Chưa đủ căn cứ":
        return [
            "Bạn có thể nói rõ hành vi, thời điểm hoặc đối tượng liên quan không?",
            "Bạn muốn tra cứu theo văn bản pháp luật hay tin chính thống?",
        ]

    if "cai nghiện" in text or "điều trị" in text:
        return [
            "Cai nghiện bắt buộc áp dụng khi nào?",
            "Gia đình cần chuẩn bị giấy tờ gì?",
        ]

    return [
        "Mức xử phạt cụ thể là gì?",
        "Trường hợp nào có thể bị xử lý hình sự?",
    ]


class CreateChatRequest(BaseModel):
    user_id: str = "demo-user"
    title: str | None = None


class RenameChatRequest(BaseModel):
    user_id: str = "demo-user"
    title: str = Field(..., min_length=1, max_length=80)


class ChatSummary(BaseModel):
    id: str
    user_id: str = "demo-user"
    title: str
    created_at: str | None = None
    updated_at: str | None = None
    message_count: int = 0


class ChatDetail(BaseModel):
    id: str
    user_id: str = "demo-user"
    title: str
    created_at: str | None = None
    updated_at: str | None = None
    messages: list[dict] = []


class LinkAttachmentRequest(BaseModel):
    url: str = Field(..., min_length=8)
    user_id: str = "demo-user"
    chat_id: str | None = None
    title: str | None = None


class GenerateTitleRequest(BaseModel):
    user_id: str
    message: str
    language: str = "vi"


class GenerateTitleResponse(BaseModel):
    chat_id: str
    title: str
