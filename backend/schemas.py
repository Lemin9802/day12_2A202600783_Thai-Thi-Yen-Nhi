from __future__ import annotations

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

        if not self.follow_up_suggestions:
            self.follow_up_suggestions = _suggest_followups(
                self.answer,
                self.evidence_level,
                self.refused,
                self.reason,
            )


def _normalize_product_sources(sources: list[dict]) -> list[dict]:
    normalized: list[dict] = []
    for idx, raw in enumerate(sources or [], start=1):
        if not isinstance(raw, dict):
            continue

        source_type = str(raw.get("source_type") or raw.get("type") or "").strip()
        url = raw.get("canonical_url") or raw.get("url") or raw.get("source_url") or raw.get("link")
        title = raw.get("title") or raw.get("source_title") or raw.get("doc_id") or f"Nguồn {idx}"
        snippet = raw.get("snippet") or raw.get("preview") or raw.get("excerpt") or raw.get("content")
        if isinstance(snippet, str):
            snippet = " ".join(snippet.split())[:280]
        else:
            snippet = None

        item = {
            "source_id": raw.get("source_id") or f"S{idx}",
            "title": title,
            "source_type": source_type or None,
            "source_type_label": _source_type_label(source_type),
            "publisher": raw.get("publisher"),
            "official_domain": raw.get("official_domain"),
            "url": url,
            "canonical_url": url,
            "doc_id": raw.get("doc_id"),
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
