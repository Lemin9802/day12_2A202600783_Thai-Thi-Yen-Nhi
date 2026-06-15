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
    canonical_url: str | None = None
    url: str | None = None
    source_url: str | None = None
    link: str | None = None
    publisher: str | None = None
    official_domain: str | None = None
    doc_id: str | None = None
    source_id: str | None = None
    title: str
    source_type: str
    url: str | None = None
    score: float | None = None
class ChatResponse(BaseModel):
    answer: str
    chat_id: str
    sources: list[dict] = Field(default_factory=list)
    refused: bool = False
    reason: str | None = None


class CreateChatRequest(BaseModel):
    user_id: str = "demo-user"
    title: str | None = None


class RenameChatRequest(BaseModel):
    user_id: str = "demo-user"
    title: str = Field(..., min_length=1, max_length=80)


class ChatSummary(BaseModel):
    id: str
    user_id: str
    title: str
    created_at: str | None = None
    updated_at: str | None = None
    message_count: int = 0


class ChatDetail(BaseModel):
    id: str
    user_id: str
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

