from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator

EVIDENCE_LEVELS = {"Căn cứ rõ", "Cần kiểm tra thêm", "Chưa đủ căn cứ", "Ngoài phạm vi hỗ trợ", "Câu hỏi nhạy cảm"}
INTERNAL_TERMS = ("dataset", "rag", "backend", "metadata", "provider", "fallback", "key context", "build production", "crawler/local", "index production")


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    language: str = Field("vi", max_length=8)
    chat_id: str | None = Field(default=None, max_length=128)
    user_id: str = Field("demo-user", max_length=128)
    attachment_ids: list[str] = Field(default_factory=list, max_length=10)
    links: list[str] = Field(default_factory=list, max_length=3)
    controlled_search: bool = False

    @field_validator("attachment_ids")
    @classmethod
    def validate_attachment_ids(cls, values: list[str]) -> list[str]:
        cleaned = [str(value).strip() for value in values]
        if any(not value or len(value) > 128 for value in cleaned):
            raise ValueError("Attachment ID không hợp lệ.")
        return list(dict.fromkeys(cleaned))

    @field_validator("links")
    @classmethod
    def validate_links(cls, values: list[str]) -> list[str]:
        cleaned = [str(value).strip() for value in values]
        if any(len(value) > 2048 for value in cleaned):
            raise ValueError("URL quá dài.")
        return list(dict.fromkeys(cleaned))


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


def clean_user_text(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.replace("\r\n", "\n").replace("\x00", " ")
    for pattern in (
        r"(?im)^.*(?:key context for rag|build production|crawler/local browser|index production).*$",
        r"\b(?:source_type|score|metadata)\s*=\s*[\w.:-]+",
        r"\b(?:dataset|backend|provider|fallback)\b\s*[:=-]*",
    ):
        text = re.sub(pattern, "", text, flags=re.I)
    text = re.sub(r"https?://\S+", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def normalize_sources(sources: list[dict]) -> list[dict]:
    result = []
    seen = set()
    for index, raw in enumerate(sources or [], 1):
        if not isinstance(raw, dict):
            continue
        url = raw.get("canonical_url") or raw.get("url")
        title = clean_user_text(raw.get("title") or raw.get("doc_id") or f"Nguồn {index}")
        key = str(raw.get("doc_id") or url or title)
        if key in seen:
            continue
        seen.add(key)
        source_type = str(raw.get("source_type") or "").lower()
        label = raw.get("source_type_label") or ("Văn bản pháp luật" if source_type == "legal" else "Tin chính thống" if source_type == "news" else "Chính sách" if source_type == "policy" else "Nguồn đính kèm" if source_type == "attachment" else "Nguồn tham khảo")
        host = (urlsplit(str(url)).hostname or "").lower() if url else ""
        item = {
            "source_id": str(raw.get("source_id") or index),
            "title": title,
            "source_type": source_type or None,
            "source_type_label": label,
            "publisher": clean_user_text(raw.get("publisher")),
            "official_domain": raw.get("official_domain") or host or None,
            "url": url,
            "canonical_url": url,
            "doc_id": raw.get("doc_id"),
            "snippet": clean_user_text(raw.get("snippet"))[:320] if raw.get("snippet") else None,
        }
        result.append({k: v for k, v in item.items() if v not in (None, "")})
    return result


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
        self.answer = clean_user_text(self.answer) or ""
        self.reason = clean_user_text(self.reason)
        self.sources = normalize_sources(self.sources)
        answer_lower = self.answer.lower()
        if self.answer.startswith("MaiThuyLaw là tên dự án") or self.answer.startswith("MaiThuyLaw combines"):
            self.evidence_level = "Căn cứ rõ"
            self.confidence = 1.0
        elif "chưa thấy căn cứ" in answer_lower or "chưa đủ căn cứ" in answer_lower or "not yet see direct legal" in answer_lower:
            self.evidence_level = "Chưa đủ căn cứ"
            self.confidence = 0.25
        if self.evidence_level not in EVIDENCE_LEVELS:
            if self.refused:
                self.evidence_level = "Ngoài phạm vi hỗ trợ" if self.reason == "out_of_domain" else "Câu hỏi nhạy cảm"
            elif self.sources:
                self.evidence_level = "Cần kiểm tra thêm"
            else:
                self.evidence_level = "Chưa đủ căn cứ"
        if self.confidence is None:
            self.confidence = {"Căn cứ rõ": .82, "Cần kiểm tra thêm": .58, "Chưa đủ căn cứ": .25, "Ngoài phạm vi hỗ trợ": .95, "Câu hỏi nhạy cảm": .95}[self.evidence_level]
        self.confidence = max(0.0, min(1.0, float(self.confidence)))
        if not self.safety:
            self.safety = {"allowed": not self.refused, "risk_level": "disallowed" if self.refused else "safe", "reason": self.reason}
        if not self.follow_up_suggestions:
            if self.evidence_level == "Chưa đủ căn cứ":
                self.follow_up_suggestions = ["Tìm thêm nguồn chính thống", "Hỏi lại cụ thể hơn", "Gửi văn bản hoặc link để đối chiếu"]
            elif self.evidence_level == "Câu hỏi nhạy cảm":
                self.follow_up_suggestions = ["Tìm hiểu quy định pháp luật liên quan", "Xem các bước hỗ trợ an toàn"]


class CreateChatRequest(BaseModel):
    user_id: str = Field("demo-user", max_length=128)
    title: str | None = Field(default=None, max_length=80)


class RenameChatRequest(BaseModel):
    user_id: str = Field("demo-user", max_length=128)
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
    messages: list[dict] = Field(default_factory=list)


class LinkAttachmentRequest(BaseModel):
    url: str = Field(..., min_length=8, max_length=2048)
    user_id: str = Field("demo-user", max_length=128)
    chat_id: str | None = Field(default=None, max_length=128)
    title: str | None = Field(default=None, max_length=200)


class GenerateTitleRequest(BaseModel):
    user_id: str = Field(..., max_length=128)
    message: str = Field(..., min_length=1, max_length=4000)
    language: str = Field("vi", max_length=8)


class GenerateTitleResponse(BaseModel):
    chat_id: str
    title: str
