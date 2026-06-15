from __future__ import annotations
from pathlib import Path
import re
import json
import uuid
from datetime import datetime
import os
from fastapi import FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile, Body
from fastapi.middleware.cors import CORSMiddleware

from backend.agent import generate_answer
from backend.attachments import (
    get_attachment,
    list_attachments_for_chat,
    resolve_attachments,
    save_attachment,
)
from backend.config import APP_NAME, MIN_SCORE, TOP_K
from backend.dataset import dataset_summary, retrieve
from backend.file_checker import evaluate_uploaded_text, extract_upload_text, fetch_link_text
from backend.guards import detect_safety_issue, is_in_domain
from backend.security import auth_and_quota
from backend.realtime import extract_urls, is_official_or_allowed_url, realtime_enabled, realtime_unavailable_answer, wants_realtime
from backend.schemas import (
    ChatDetail,
    ChatRequest,
    ChatResponse,
    ChatSummary,
    CreateChatRequest,
    LinkAttachmentRequest,
    RenameChatRequest,
    GenerateTitleRequest,
    GenerateTitleResponse,
    Source,
)
from backend.title import generate_chat_title
from backend.store import (
    add_message,
    create_chat,
    delete_chat,
    ensure_chat,
    get_chat,
    list_chats,
    rename_chat,
    rewrite_with_memory,
)

_DATASET_SOURCE_REGISTRY = None

def _load_dataset_source_registry():
    global _DATASET_SOURCE_REGISTRY
    if _DATASET_SOURCE_REGISTRY is not None:
        return _DATASET_SOURCE_REGISTRY

    registry = {}
    dataset_path = Path(__file__).resolve().parents[1] / "data" / "maithuylaw_dataset" / "data" / "index" / "rag_chunks.json"

    try:
        chunks = json.loads(dataset_path.read_text(encoding="utf-8"))
    except Exception:
        _DATASET_SOURCE_REGISTRY = registry
        return registry

    def add_key(key, info):
        key = str(key or "").strip()
        if key and key not in registry:
            registry[key] = info

    for chunk in chunks:
        meta = chunk.get("metadata") or {}
        doc_id = (
            meta.get("doc_id")
            or meta.get("source_id")
            or meta.get("id")
            or chunk.get("doc_id")
            or ""
        )
        title = (
            meta.get("title")
            or meta.get("source_title")
            or chunk.get("title")
            or meta.get("source")
            or doc_id
        )
        url = (
            meta.get("canonical_url")
            or meta.get("url")
            or meta.get("source_url")
            or meta.get("link")
            or chunk.get("canonical_url")
            or chunk.get("url")
            or ""
        )
        publisher = meta.get("publisher") or chunk.get("publisher") or ""
        official_domain = meta.get("official_domain") or chunk.get("official_domain") or ""
        source_type = meta.get("source_type") or meta.get("type") or chunk.get("source_type") or ""

        info = {
            "doc_id": doc_id,
            "title": title,
            "canonical_url": url,
            "url": url,
            "source_url": url,
            "link": url,
            "publisher": publisher,
            "official_domain": official_domain,
            "source_type": source_type,
        }

        add_key(doc_id, info)
        add_key(title, info)
        add_key(meta.get("source"), info)
        add_key(meta.get("source_title"), info)

    _DATASET_SOURCE_REGISTRY = registry
    return registry

def _source_to_dict(source):
    if source is None:
        return {}
    if isinstance(source, dict):
        return dict(source)
    if hasattr(source, "model_dump"):
        return source.model_dump()
    if hasattr(source, "dict"):
        return source.dict()
    return {
        key: getattr(source, key)
        for key in dir(source)
        if not key.startswith("_") and key in {"title", "doc_id", "source_type", "url", "canonical_url", "source_url", "link", "publisher", "official_domain", "score"}
    }

def _normalize_response_sources(sources):
    registry = _load_dataset_source_registry()
    normalized = []
    seen = set()

    for index, source in enumerate(sources or []):
        item = _source_to_dict(source)
        meta = item.get("metadata") or {}

        doc_id = (
            item.get("doc_id")
            or item.get("source_id")
            or meta.get("doc_id")
            or meta.get("source_id")
            or ""
        )

        title = (
            item.get("title")
            or item.get("source_title")
            or meta.get("title")
            or meta.get("source_title")
            or meta.get("source")
            or item.get("source")
            or doc_id
            or f"S{index + 1}"
        )

        lookup = (
            registry.get(str(doc_id).strip())
            or registry.get(str(title).strip())
            or registry.get(str(item.get("source") or "").strip())
            or registry.get(str(meta.get("source") or "").strip())
            or {}
        )

        url = (
            item.get("canonical_url")
            or item.get("url")
            or item.get("source_url")
            or item.get("link")
            or meta.get("canonical_url")
            or meta.get("url")
            or meta.get("source_url")
            or meta.get("link")
            or lookup.get("canonical_url")
            or lookup.get("url")
            or lookup.get("source_url")
            or lookup.get("link")
            or ""
        )

        final_doc_id = lookup.get("doc_id") or doc_id
        final_title = lookup.get("title") or title
        final_type = lookup.get("source_type") or item.get("source_type") or meta.get("source_type") or meta.get("type") or ""
        final_publisher = lookup.get("publisher") or item.get("publisher") or meta.get("publisher") or ""
        final_domain = lookup.get("official_domain") or item.get("official_domain") or meta.get("official_domain") or ""

        dedupe_key = (
            str(url).strip().lower()
            or str(final_doc_id).strip().lower()
            or str(final_title).strip().lower()
        )

        if dedupe_key and dedupe_key in seen:
            continue
        if dedupe_key:
            seen.add(dedupe_key)

        normalized.append({
            "source_id": final_doc_id or final_title or f"S{index + 1}",
            "doc_id": final_doc_id,
            "title": final_title,
            "source_type": final_type,
            "publisher": final_publisher,
            "official_domain": final_domain,
            "canonical_url": url,
            "url": url,
            "source_url": url,
            "link": url,
        })

    return normalized[:6]

def _reduce_single_source_citation_spam(answer: str, sources: list[dict]) -> str:
    text = str(answer or "")

    try:
        if len(sources or []) != 1:
            return text

        if text.count("[S1]") <= 4:
            return text

        lines = text.splitlines()
        output = []
        kept_in_current_section = False
        in_references = False

        for line in lines:
            stripped = line.strip()
            lower = stripped.lower()

            is_heading = stripped.startswith("#") or lower in {
                "nguồn tham khảo",
                "### nguồn tham khảo",
                "## nguồn tham khảo",
                "references",
                "### references",
                "## references",
            }

            if is_heading:
                kept_in_current_section = False

            if "nguồn tham khảo" in lower or lower == "references":
                in_references = True
            elif is_heading and in_references and "nguồn tham khảo" not in lower and lower != "references":
                in_references = False

            if "[S1]" in line and not in_references:
                if kept_in_current_section:
                    line = line.replace(" [S1]", "")
                    line = line.replace("[S1]", "")
                    line = re.sub(r"\s+([,.])", r"\1", line)
                else:
                    kept_in_current_section = True

            output.append(line)

        text = "\n".join(output)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    except Exception:
        return text

def _normalize_answer_citations(answer: str, sources: list[dict]) -> str:
    text = str(answer or "")
    try:
        count = len(sources or [])
        group_pattern = re.compile(r"\[(?:S\d+\s*(?:,\s*S\d+\s*)*)\]")

        if count <= 0:
            return group_pattern.sub("", text)

        def fix_group(match):
            raw = match.group(0)
            nums = [int(n) for n in re.findall(r"S(\d+)", raw)]

            if count == 1:
                return "[S1]"

            valid = []
            for n in nums:
                if 1 <= n <= count and n not in valid:
                    valid.append(n)

            if not valid:
                return ""

            return "[" + ", ".join(f"S{n}" for n in valid) + "]"

        text = group_pattern.sub(fix_group, text)

        if count == 1:
            text = re.sub(r"\[S1\](?:\s*,\s*\[S1\])+", "[S1]", text)
            text = re.sub(r"(\[S1\]\s*){2,}", "[S1] ", text)

        text = re.sub(r"\s+([,.])", r"\1", text)
        text = re.sub(r",\s*,", ",", text)
        return text
    except Exception:
        return text


def _source_label(item: dict, index: int) -> Source:
    meta = item.get("metadata", {}) or {}
    return Source(
        source_id=f"S{index}",
        title=meta.get("title") or meta.get("source") or meta.get("doc_id") or "unknown",
        source_type=meta.get("source_type") or meta.get("type") or "unknown",
        url=meta.get("url") or None,
        score=float(item.get("score", 0.0)),
    )

def _attachment_source(att: dict, index: int) -> Source:
    return Source(
        source_id=f"A{index}",
        title=att.get("name") or att.get("url") or "attachment",
        source_type=f"attachment:{att.get('verdict', 'unknown')}",
        url=att.get("url"),
        score=float(att.get("domain_score") or 0.0),
    )

def _compact(text: str, max_chars: int = 700) -> str:
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 3].rstrip() + "..."

def _summarize_attachment(att: dict) -> list[str]:
    text = att.get("text", "")
    sentences = [s.strip() for s in text.replace("?", ".").replace("!", ".").split(".") if len(s.strip()) > 35]
    selected = sentences[:4]
    if not selected and text:
        selected = [_compact(text, 500)]
    return [f"- {s}." for s in selected]

def _wants_summary(message: str) -> bool:
    q = message.lower()
    return any(x in q for x in ["tóm tắt", "tom tat", "ý chính", "y chinh", "nội dung chính", "noi dung chinh"])

def _wants_source_check(message: str) -> bool:
    q = message.lower()
    return any(x in q for x in ["chính thống", "chinh thong", "đáng tin", "dang tin", "kiểm tra nguồn", "kiem tra nguon", "nguồn này"])

def _wants_compare_law(message: str) -> bool:
    q = message.lower()
    return any(x in q for x in ["so sánh", "so sanh", "đối chiếu", "doi chieu", "theo luật", "theo luat", "quy định"])

def _format_dataset_answer(results: list[dict]) -> str:
    if not results or float(results[0].get("score", 0.0)) < MIN_SCORE:
        return (
            "Mình chưa tìm thấy nguồn đủ mạnh trong dataset hiện có để trả lời chắc chắn. "
            "Bạn có thể hỏi cụ thể hơn về văn bản pháp luật, hành vi, chính sách hoặc tin tức liên quan đến ma túy."
        )

    lines = [
        "## Trả lời từ nguồn hiện có",
        "",
        "Mình tìm được các nguồn liên quan trong dataset MaiThuyLaw:",
        "",
    ]

    for i, item in enumerate(results[:3], start=1):
        lines.append(f"**[S{i}]** {_compact(item.get('content', ''), 520)}")
        lines.append("")

    lines += [
        "## Lưu ý",
        "Thông tin này chỉ phục vụ tra cứu từ nguồn đã thu thập, không thay thế tư vấn pháp lý chính thức.",
    ]
    return "\n".join(lines).strip()

def _format_attachment_answer(message: str, attachments: list[dict], dataset_results: list[dict]) -> str:
    usable = [a for a in attachments if a.get("verdict") in {"accepted", "needs_review"}]
    rejected = [a for a in attachments if a.get("verdict") == "rejected"]

    lines = ["## Trả lời dựa trên nội dung đính kèm", ""]

    if rejected:
        lines.append("Một số file/link bị từ chối và không được dùng làm nguồn trả lời:")
        for att in rejected:
            lines.append(f"- **{att.get('name')}**: {att.get('reason')}")
        lines.append("")

    if not usable:
        lines.append("Không có file/link đủ an toàn và phù hợp để dùng làm ngữ cảnh trả lời.")
        return "\n".join(lines).strip()

    if _wants_source_check(message):
        lines.append("### Đánh giá nguồn")
        for i, att in enumerate(usable, start=1):
            lines.append(
                f"- **[A{i}] {att.get('name')}**: `{att.get('verdict')}`. "
                f"{att.get('reason')} "
                f"(domain={att.get('domain_score')}, official={att.get('official_score')}, dataset_match={att.get('dataset_match_score')})"
            )
        lines.append("")

    if _wants_summary(message) or not (_wants_source_check(message) or _wants_compare_law(message)):
        lines.append("### Tóm tắt nội dung đính kèm")
        for i, att in enumerate(usable, start=1):
            lines.append(f"**[A{i}] {att.get('name')}**")
            lines.extend(_summarize_attachment(att))
            lines.append("")

    if _wants_compare_law(message) or dataset_results:
        lines.append("### Đối chiếu với dataset MaiThuyLaw")
        for i, item in enumerate(dataset_results[:3], start=1):
            lines.append(f"- **[S{i}]** {_compact(item.get('content', ''), 380)}")
        lines.append("")

    lines.append("## Lưu ý")
    lines.append(
        "Mình chỉ dùng nội dung đính kèm nếu nó an toàn và nằm trong phạm vi pháp luật/chính sách/tin tức chính thống về ma túy. "
        "Nếu nguồn chỉ ở mức `needs_review`, bạn nên kiểm tra lại nguồn gốc trước khi trích dẫn."
    )

    return "\n".join(lines).strip()

# --- MaiThuyLaw language-aware user messages ---
def _request_language(req) -> str:
    value = getattr(req, "language", "vi")
    return "en" if str(value).lower().startswith("en") else "vi"

def _scope_refusal(language: str = "vi") -> str:
    if str(language).lower().startswith("en"):
        return (
            "I can help with Vietnamese law, policy, and verified official news related to drug-related matters. "
            "Please ask within that scope, for example about Vietnamese legal rules, prevention policy, rehabilitation, "
            "or official source checking."
        )

    return (
        "Mình chỉ hỗ trợ tra cứu thông tin pháp luật, chính sách và tin tức chính thống liên quan đến ma túy. "
        "Bạn hãy đặt câu hỏi trong phạm vi này nhé."
    )


app = FastAPI(title="MaiThuyLaw AI", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)




# FAST_CHAT_HISTORY_ROUTES
CHAT_HISTORY_PATH = Path("data/runtime/web_chats.json")


def _chat_now():
    return datetime.utcnow().isoformat() + "Z"


def _load_web_chats():
    try:
        if CHAT_HISTORY_PATH.exists():
            return json.loads(CHAT_HISTORY_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_web_chats(store):
    CHAT_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    CHAT_HISTORY_PATH.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")


def _chat_summary(chat):
    messages = chat.get("messages") or []
    return {
        "id": chat.get("id"),
        "chat_id": chat.get("id"),
        "title": chat.get("title") or "Cuộc trò chuyện mới",
        "created_at": chat.get("created_at"),
        "updated_at": chat.get("updated_at"),
        "message_count": len(messages),
    }


def _save_chat_message(user_id, chat_id, role, content, sources=None, title=None):
    store = _load_web_chats()
    user_store = store.setdefault(user_id or "demo-user", {})
    now = _chat_now()

    chat = user_store.setdefault(chat_id, {
        "id": chat_id,
        "chat_id": chat_id,
        "title": title or "Cuộc trò chuyện mới",
        "messages": [],
        "created_at": now,
        "updated_at": now,
    })

    if title and (not chat.get("title") or chat.get("title") == "Cuộc trò chuyện mới"):
        chat["title"] = title

    chat["messages"].append({
        "id": f"{role}-{uuid.uuid4()}",
        "role": role,
        "content": content or "",
        "sources": sources or [],
        "created_at": now,
    })
    chat["updated_at"] = now
    _save_web_chats(store)


@app.get("/api/chats")
async def fast_list_chats(user_id: str = "demo-user"):
    store = _load_web_chats()
    user_store = store.get(user_id or "demo-user", {})
    chats = sorted(
        (_chat_summary(chat) for chat in user_store.values()),
        key=lambda item: item.get("updated_at") or "",
        reverse=True,
    )
    return {"chats": chats}


@app.post("/api/chats")
async def fast_create_chat(payload: dict = Body(default_factory=dict)):
    store = _load_web_chats()
    user_id = str(payload.get("user_id") or "demo-user")
    user_store = store.setdefault(user_id, {})

    now = _chat_now()
    chat_id = str(payload.get("chat_id") or payload.get("id") or uuid.uuid4())
    title = str(payload.get("title") or "Cuộc trò chuyện mới")

    chat = user_store.setdefault(chat_id, {
        "id": chat_id,
        "chat_id": chat_id,
        "title": title,
        "messages": [],
        "created_at": now,
        "updated_at": now,
    })

    chat["title"] = chat.get("title") or title
    chat["updated_at"] = now
    _save_web_chats(store)

    return chat


@app.get("/api/chats/{chat_id}")
async def fast_get_chat(chat_id: str, user_id: str = "demo-user"):
    store = _load_web_chats()
    chat = store.get(user_id or "demo-user", {}).get(chat_id)

    if not chat:
        now = _chat_now()
        chat = {
            "id": chat_id,
            "chat_id": chat_id,
            "title": "Cuộc trò chuyện mới",
            "messages": [],
            "created_at": now,
            "updated_at": now,
        }

    return chat




@app.post("/api/chats", response_model=ChatDetail)
def api_create_chat(req: CreateChatRequest, request: Request, x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> dict:
    auth_and_quota(request, user_id=req.user_id, x_api_key=x_api_key)
    return create_chat(user_id=req.user_id, title=req.title)

@app.get("/api/chats", response_model=list[ChatSummary])
def api_list_chats(request: Request, user_id: str = Query("demo-user"), x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> list[dict]:
    auth_and_quota(request, user_id=user_id, x_api_key=x_api_key)
    return list_chats(user_id=user_id)

@app.get("/api/chats/{chat_id}", response_model=ChatDetail)
def api_get_chat(chat_id: str, request: Request, user_id: str = Query("demo-user"), x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> dict:
    auth_and_quota(request, user_id=user_id, x_api_key=x_api_key)
    chat = get_chat(chat_id, user_id=user_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat

@app.patch("/api/chats/{chat_id}", response_model=ChatDetail)
def api_rename_chat(chat_id: str, req: RenameChatRequest, request: Request, x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> dict:
    auth_and_quota(request, user_id=req.user_id, x_api_key=x_api_key)
    chat = rename_chat(chat_id, title=req.title, user_id=req.user_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat

@app.delete("/api/chats/{chat_id}")
def api_delete_chat(chat_id: str, request: Request, user_id: str = Query("demo-user"), x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> dict:
    auth_and_quota(request, user_id=user_id, x_api_key=x_api_key)
    ok = delete_chat(chat_id, user_id=user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Chat not found")
    return {"deleted": True, "chat_id": chat_id}

@app.post("/api/upload-check")
async def api_upload_check(request: Request, file: UploadFile = File(...), x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> dict:
    auth_and_quota(request, user_id=request.headers.get("X-User-ID"), x_api_key=x_api_key)
    extracted = await extract_upload_text(file)
    if not extracted.get("ok"):
        return {
            "filename": extracted.get("filename"),
            "size_bytes": extracted.get("size_bytes"),
            "verdict": "rejected",
            "reason": extracted.get("error"),
            "source_matches": [],
        }

    evaluation = evaluate_uploaded_text(extracted["text"])
    return {
        "filename": extracted["filename"],
        "size_bytes": extracted["size_bytes"],
        **evaluation,
    }

@app.post("/api/attachments/upload")
async def api_attachment_upload(
    request: Request,
    file: UploadFile = File(...),
    user_id: str = Form("demo-user"),
    chat_id: str | None = Form(None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict:
    auth_and_quota(request, user_id=user_id, x_api_key=x_api_key)
    extracted = await extract_upload_text(file)
    if not extracted.get("ok"):
        return {
            "id": None,
            "name": extracted.get("filename"),
            "kind": "file",
            "verdict": "rejected",
            "reason": extracted.get("error"),
            "source_matches": [],
        }

    return save_attachment(
        user_id=user_id,
        chat_id=chat_id,
        name=extracted["filename"],
        kind="file",
        text=extracted["text"],
        size_bytes=extracted["size_bytes"],
    )

@app.post("/api/attachments/link")
async def api_attachment_link(req: LinkAttachmentRequest, request: Request, x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> dict:
    auth_and_quota(request, user_id=req.user_id, x_api_key=x_api_key)
    fetched = await fetch_link_text(req.url)
    if not fetched.get("ok"):
        return {
            "id": None,
            "name": req.title or req.url,
            "kind": "link",
            "url": req.url,
            "verdict": "rejected",
            "reason": fetched.get("error"),
            "source_matches": [],
        }

    return save_attachment(
        user_id=req.user_id,
        chat_id=req.chat_id,
        name=req.title or req.url,
        kind="link",
        url=req.url,
        text=f"URL: {req.url}\n\n{fetched['text']}",
        size_bytes=len(fetched["text"].encode("utf-8")),
    )

@app.get("/api/attachments/{attachment_id}")
def api_get_attachment(attachment_id: str, request: Request, user_id: str = Query("demo-user"), x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> dict:
    auth_and_quota(request, user_id=user_id, x_api_key=x_api_key)
    item = get_attachment(attachment_id, user_id=user_id, include_text=False)
    if not item:
        raise HTTPException(status_code=404, detail="Attachment not found")
    return item

@app.get("/api/chats/{chat_id}/attachments")
def api_list_chat_attachments(chat_id: str, request: Request, user_id: str = Query("demo-user"), x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> list[dict]:
    auth_and_quota(request, user_id=user_id, x_api_key=x_api_key)
    return list_attachments_for_chat(chat_id, user_id=user_id)

@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, request: Request, x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> ChatResponse:
    auth_and_quota(request, user_id=req.user_id, x_api_key=x_api_key)
    message = req.message.strip()
    active_chat = ensure_chat(req.chat_id, req.user_id, first_message=message)
    chat_id = active_chat["id"]

    message_urls = extract_urls(message)
    merged_links = []
    for url in list(req.links or []) + message_urls:
        if url not in merged_links:
            merged_links.append(url)

    saved_link_attachments = []
    failed_link_attachments = []

    for url in merged_links:
        fetched = await fetch_link_text(url)
        if fetched.get("ok"):
            saved = save_attachment(
                user_id=req.user_id,
                chat_id=chat_id,
                name=url,
                kind="link",
                url=url,
                text=f"URL: {url}\n\n{fetched['text']}",
                size_bytes=len(fetched["text"].encode("utf-8")),
            )
            saved_link_attachments.append(saved)
        else:
            failed_link_attachments.append(
                {
                    "id": None,
                    "user_id": req.user_id,
                    "chat_id": chat_id,
                    "name": url,
                    "kind": "link",
                    "url": url,
                    "verdict": "rejected",
                    "reason": fetched.get("error") or "Không đọc được link.",
                    "safety_reason": None,
                    "domain_score": 0.0,
                    "official_score": 0.0,
                    "dataset_match_score": 0.0,
                    "source_matches": [],
                    "preview": "",
                    "text": "",
                }
            )

    all_attachment_ids = list(req.attachment_ids or []) + [
        a["id"] for a in saved_link_attachments if a.get("id")
    ]
    attachments = resolve_attachments(all_attachment_ids, user_id=req.user_id)
    attachments.extend(failed_link_attachments)

    attachment_text = "\n\n".join(a.get("text", "")[:2500] for a in attachments)
    safety_reason = detect_safety_issue(message + "\n" + attachment_text[:3000])

    if safety_reason:
        answer = (
            "Mình không thể hỗ trợ theo hướng đó vì nội dung có thể bị lạm dụng hoặc không phù hợp với quy định pháp luật. Mình có thể hỗ trợ bạn theo hướng an toàn hơn, như tra cứu quy định liên quan, hậu quả pháp lý, chính sách phòng chống ma túy, cai nghiện hoặc kiểm tra nguồn tin chính thống."
        )
        add_message(chat_id, "user", message, req.user_id)
        add_message(chat_id, "assistant", answer, req.user_id)
        return ChatResponse(chat_id=chat_id, refused=True, reason=safety_reason, answer=answer, sources=[])

    attachment_allows_domain = any(
        a.get("verdict") in {"accepted", "needs_review"} and float(a.get("domain_score") or 0) >= 0.3
        for a in attachments
    )

    if not attachments and not is_in_domain(message):
        answer = (
            "Mình chỉ hỗ trợ tra cứu thông tin pháp luật, chính sách và tin tức chính thống liên quan đến ma túy. "
            "Bạn hãy đặt câu hỏi trong phạm vi này nhé."
        )
        add_message(chat_id, "user", message, req.user_id)
        add_message(chat_id, "assistant", answer, req.user_id)
        return ChatResponse(chat_id=chat_id, refused=True, reason="out_of_domain", answer=answer, sources=[])

    if not attachments and wants_realtime(message) and not realtime_enabled():
        # Still allow dataset retrieval below if the query has enough in-domain/legal context.
        # But the final answer must clearly avoid pretending to have live web access.
        pass

    if attachments and not attachment_allows_domain and not is_in_domain(message):
        answer = (
            "Nội dung đính kèm chưa đủ phù hợp với phạm vi pháp luật, chính sách hoặc tin tức chính thống về ma túy, "
            "nên mình không dùng nó để trả lời. Bạn có thể gửi nguồn chính thống hơn hoặc hỏi lại trong đúng phạm vi."
        )
        add_message(chat_id, "user", message, req.user_id)
        add_message(chat_id, "assistant", answer, req.user_id)
        return ChatResponse(chat_id=chat_id, refused=True, reason="attachment_out_of_domain", answer=answer, sources=[])

    retrieval_query = rewrite_with_memory(message, chat_id, req.user_id)
    if attachment_text:
        retrieval_query = retrieval_query + "\n\nNội dung đính kèm:\n" + attachment_text[:2500]

    dataset_results = retrieve(retrieval_query, top_k=TOP_K)
    dataset_sources = [_source_label(item, i) for i, item in enumerate(dataset_results, start=1)]
    attachment_sources = [_attachment_source(att, i) for i, att in enumerate(attachments, start=1)]

    answer = generate_answer(
        message=message,
        dataset_results=dataset_results,
        attachments=attachments,
        language=getattr(req, "language", "vi")
    )

    if not attachments and wants_realtime(message) and not realtime_enabled():
        answer = realtime_unavailable_answer(locals().get("language") or "vi")

    add_message(chat_id, "user", message, req.user_id)
    add_message(chat_id, "assistant", answer, req.user_id)

    normalized_sources = _normalize_response_sources(attachment_sources + dataset_sources)
    safe_answer = _normalize_answer_citations(answer, normalized_sources)
    safe_answer = _reduce_single_source_citation_spam(safe_answer, normalized_sources)

    normalized_sources = _normalize_response_sources(attachment_sources + dataset_sources)
    safe_answer = _normalize_answer_citations(answer, normalized_sources)
    safe_answer = _reduce_single_source_citation_spam(safe_answer, normalized_sources)

    try:
        _save_chat_message(req.user_id, chat_id, "user", req.message, [])
        _save_chat_message(req.user_id, chat_id, "assistant", safe_answer, normalized_sources)
    except Exception:
        pass

    return ChatResponse(
        chat_id=chat_id,
        answer=safe_answer,
        sources=normalized_sources,
    )

@app.post("/api/chats/{chat_id}/generate-title", response_model=GenerateTitleResponse)
async def generate_title_for_chat(
    chat_id: str,
    payload: GenerateTitleRequest,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    expected_key = os.getenv("MAITHUYLAW_API_KEY") or os.getenv("AGENT_API_KEY") or "dev-maithuylaw-key"
    if not x_api_key or x_api_key != expected_key:
        raise HTTPException(status_code=401, detail="Missing or invalid X-API-Key.")

    language = "en" if payload.language.lower().startswith("en") else "vi"
    title = generate_chat_title(payload.message, language)

    # Best-effort persistence. The frontend can still use the returned title immediately.
    for args in (
        (chat_id, payload.user_id, title),
        (payload.user_id, chat_id, title),
        (chat_id, title, payload.user_id),
        (chat_id, title),
    ):
        try:
            updated = rename_chat(*args)
            if updated:
                break
        except TypeError:
            continue
        except Exception:
            break

    return GenerateTitleResponse(chat_id=chat_id, title=title)

