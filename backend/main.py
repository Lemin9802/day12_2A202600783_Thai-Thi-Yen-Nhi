from __future__ import annotations
from pathlib import Path
import re
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from contextlib import asynccontextmanager
import os
from fastapi import FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

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
from backend.security import auth_and_quota, verify_api_key as _verify_api_key_only
from backend.realtime import (
    extract_urls,
    realtime_enabled,
    realtime_unavailable_answer,
    wants_realtime,
)
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

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","message":"%(message)s"}',
)
logger = logging.getLogger(__name__)

START_TIME = time.time()
APP_VERSION = os.getenv("APP_VERSION", "1.0.0")
ENVIRONMENT = os.getenv("ENVIRONMENT", "production")

# ── Budget guard (ported from app/cost_guard.py) ───────────────────────────────
from dataclasses import dataclass, field as dc_field

PRICE_PER_REQUEST_USD = 0.001
_budget_records: dict[str, object] = {}


@dataclass
class _BudgetRecord:
    user_id: str
    month: str = dc_field(default_factory=lambda: time.strftime("%Y-%m"))
    request_count: int = 0
    spent_usd: float = 0.0


def _monthly_budget() -> float:
    return float(os.getenv("MONTHLY_BUDGET_USD", "10.0"))


def _get_budget_record(user_id: str) -> _BudgetRecord:
    month = time.strftime("%Y-%m")
    rec = _budget_records.get(user_id)
    if not rec or rec.month != month:  # type: ignore[union-attr]
        rec = _BudgetRecord(user_id=user_id, month=month)
        _budget_records[user_id] = rec
    return rec  # type: ignore[return-value]


def check_budget(user_id: str) -> None:
    rec = _get_budget_record(user_id)
    budget = _monthly_budget()
    if rec.spent_usd + PRICE_PER_REQUEST_USD > budget:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "Monthly budget exceeded",
                "user_id": user_id,
                "spent_usd": round(rec.spent_usd, 6),
                "monthly_budget_usd": budget,
                "resets_at": "next month",
            },
        )


def record_budget_usage(user_id: str) -> _BudgetRecord:
    rec = _get_budget_record(user_id)
    rec.request_count += 1
    rec.spent_usd += PRICE_PER_REQUEST_USD
    return rec


def get_usage(user_id: str) -> dict:
    rec = _get_budget_record(user_id)
    budget = _monthly_budget()
    return {
        "user_id": user_id,
        "month": rec.month,
        "request_count": rec.request_count,
        "spent_usd": round(rec.spent_usd, 6),
        "monthly_budget_usd": budget,
        "remaining_usd": round(max(0.0, budget - rec.spent_usd), 6),
    }


# ── CORS origins ──────────────────────────────────────────────────────────────
def _cors_origins() -> list[str]:
    base = [
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:8020",
        "http://localhost:8020",
    ]
    extra = os.getenv("MAITHUYLAW_ALLOWED_ORIGINS", "")
    for o in extra.split(","):
        o = o.strip()
        if o and o not in base:
            base.append(o)
    return base


# ── App lifespan ───────────────────────────────────────────────────────────────
_is_ready = False
_dataset_chunks = 0


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _is_ready, _dataset_chunks
    try:
        summary = dataset_summary()
        _dataset_chunks = summary.get("chunks", 0)
        logger.info(json.dumps({
            "event": "startup",
            "app": APP_NAME,
            "version": APP_VERSION,
            "environment": ENVIRONMENT,
            "dataset_chunks": _dataset_chunks,
        }))
    except Exception as e:
        logger.warning(json.dumps({"event": "startup_dataset_warning", "error": str(e)}))
    _is_ready = True
    yield
    _is_ready = False
    logger.info(json.dumps({"event": "shutdown"}))


# ── FastAPI app ────────────────────────────────────────────────────────────────
app = FastAPI(
    title="MaiThuyLaw AI",
    version=APP_VERSION,
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _ensure_json_utf8(request: Request, call_next):
    response = await call_next(request)
    content_type = response.headers.get("content-type", "")
    if content_type.startswith("application/json") and "charset=" not in content_type.lower():
        response.headers["content-type"] = "application/json; charset=utf-8"
    return response


# ── Auth helper ────────────────────────────────────────────────────────────────
def _require_auth(
    request: Request,
    user_id: str,
    x_api_key: str | None,
) -> None:
    """Uniform auth + quota for all /api/* endpoints."""
    auth_and_quota(request, user_id=user_id, x_api_key=x_api_key)


# ── /health ────────────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {
        "status": "ok",
        "app": APP_NAME,
        "version": APP_VERSION,
        "environment": ENVIRONMENT,
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "dataset_chunks": _dataset_chunks,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ── /ready ─────────────────────────────────────────────────────────────────────
@app.get("/ready")
def ready():
    if not _is_ready:
        raise HTTPException(status_code=503, detail="Service not ready")
    gemini_key = bool(os.getenv("GEMINI_API_KEY", "").strip())
    return {
        "ready": True,
        "dataset_chunks": _dataset_chunks,
        "gemini_configured": gemini_key,
    }


# ── /usage ─────────────────────────────────────────────────────────────────────
@app.get("/usage")
def usage_endpoint(
    request: Request,
    user_id: str = Query("demo-user"),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    _require_auth(request, user_id, x_api_key)
    return get_usage(user_id)


# ── /ask  (legacy compatibility wrapper) ──────────────────────────────────────
# Keeps the old response shape: question, answer, rate_limit, budget, served_by, storage.
# Internally delegates to the /api/chat logic.

class _LegacyAskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)
    user_id: str | None = None


@app.post("/ask")
async def legacy_ask(
    body: _LegacyAskRequest,
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    """Backward-compatible /ask — delegates to /api/chat, returns old response shape.

    Auth/quota is handled exactly once inside chat(). This wrapper only verifies
    the API key (no quota consumed) so the inner chat() call is the single point
    that increments the rate-limit counter.
    """
    uid = body.user_id or "default-user"
    # Key check only — no quota consumed here. chat() will do full auth_and_quota.
    _verify_api_key_only(request, x_api_key)
    req = ChatRequest(message=body.question, user_id=uid)
    result = await chat(req, request, x_api_key=x_api_key)

    # Build rate_limit metadata for response (read current config, not counters)
    rate_limit_pm = int(os.getenv("MAITHUYLAW_RATE_LIMIT_PER_MINUTE", "10"))
    budget_info = get_usage(uid)

    return {
        "user_id": uid,
        "question": body.question,
        "answer": result.answer,
        "sources": result.sources,
        "refused": result.refused,
        "history_count": 0,
        "served_by": APP_NAME,
        "storage": "json",
        "rate_limit": {
            "limit": rate_limit_pm,
            "window_seconds": 60,
            "note": "per-user sliding window",
        },
        "budget": {
            "spent_usd": budget_info["spent_usd"],
            "monthly_budget_usd": budget_info["monthly_budget_usd"],
            "remaining_usd": budget_info["remaining_usd"],
            "request_count": budget_info["request_count"],
        },
    }


# ── /api/chats — unified store (backend/store.py only) ────────────────────────
# ALL endpoints require auth for consistency.

@app.get("/api/chats")
def api_list_chats(
    request: Request,
    user_id: str = Query("demo-user"),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    _require_auth(request, user_id, x_api_key)
    chats = list_chats(user_id=user_id)
    return {"chats": chats}


@app.post("/api/chats")
def api_create_chat(
    request: Request,
    payload: dict = Body(default_factory=dict),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    uid = str(payload.get("user_id") or "demo-user")
    _require_auth(request, uid, x_api_key)
    title = str(payload.get("title") or "Cuộc trò chuyện mới")
    return create_chat(user_id=uid, title=title)


@app.get("/api/chats/{chat_id}")
def api_get_chat(
    chat_id: str,
    request: Request,
    user_id: str = Query("demo-user"),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    _require_auth(request, user_id, x_api_key)
    chat_obj = get_chat(chat_id, user_id=user_id)
    if not chat_obj:
        # Auto-create lightweight shell so frontend doesn't 404 on new chat
        now = datetime.now(timezone.utc).isoformat()
        return {
            "id": chat_id,
            "user_id": user_id,
            "title": "Cuộc trò chuyện mới",
            "messages": [],
            "created_at": now,
            "updated_at": now,
        }
    return chat_obj


@app.patch("/api/chats/{chat_id}")
def api_rename_chat(
    chat_id: str,
    req: RenameChatRequest,
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    _require_auth(request, req.user_id, x_api_key)
    updated = rename_chat(chat_id, title=req.title, user_id=req.user_id)
    if not updated:
        raise HTTPException(status_code=404, detail="Chat not found")
    return updated


@app.delete("/api/chats/{chat_id}")
def api_delete_chat(
    chat_id: str,
    request: Request,
    user_id: str = Query("demo-user"),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    _require_auth(request, user_id, x_api_key)
    ok = delete_chat(chat_id, user_id=user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Chat not found")
    return {"deleted": True, "chat_id": chat_id}


# ── Attachments ────────────────────────────────────────────────────────────────
@app.post("/api/upload-check")
async def api_upload_check(
    request: Request,
    file: UploadFile = File(...),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict:
    uid = request.headers.get("X-User-ID") or "demo-user"
    _require_auth(request, uid, x_api_key)
    raw = await file.read()
    text = await extract_upload_text(raw, filename=file.filename or "")
    if not text.strip():
        return {"ok": False, "error": "Không đọc được nội dung tệp."}
    return await evaluate_uploaded_text(text, filename=file.filename or "")


@app.post("/api/attachments/upload")
async def api_attachment_upload(
    request: Request,
    file: UploadFile = File(...),
    user_id: str = Form("demo-user"),
    chat_id: str | None = Form(None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict:
    _require_auth(request, user_id, x_api_key)
    raw = await file.read()
    text = await extract_upload_text(raw, filename=file.filename or "")
    check = await evaluate_uploaded_text(text, filename=file.filename or "")
    return save_attachment(
        user_id=user_id,
        chat_id=chat_id,
        name=file.filename or "upload",
        kind="file",
        url=None,
        text=text,
        size_bytes=len(raw),
        verdict=check.get("verdict", "needs_review"),
        reason=check.get("reason"),
        preview=check.get("preview"),
        domain_score=check.get("domain_score", 0.0),
        official_score=check.get("official_score", 0.0),
        dataset_match_score=check.get("dataset_match_score", 0.0),
        source_matches=check.get("source_matches", []),
        safety_reason=check.get("safety_reason"),
    )


@app.post("/api/attachments/link")
async def api_attachment_link(
    req: LinkAttachmentRequest,
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict:
    _require_auth(request, req.user_id, x_api_key)
    fetched = await fetch_link_text(req.url)
    if not fetched.get("ok"):
        return {
            "id": None, "user_id": req.user_id, "chat_id": req.chat_id,
            "name": req.url, "kind": "link", "url": req.url,
            "verdict": "rejected", "reason": fetched.get("error") or "Không đọc được link.",
            "safety_reason": None, "domain_score": 0.0, "official_score": 0.0,
            "dataset_match_score": 0.0, "source_matches": [], "preview": "", "text": "",
        }
    text = fetched["text"]
    check = await evaluate_uploaded_text(text, filename=req.url)
    return save_attachment(
        user_id=req.user_id,
        chat_id=req.chat_id,
        name=req.title or req.url,
        kind="link",
        url=req.url,
        text=f"URL: {req.url}\n\n{text}",
        size_bytes=len(text.encode("utf-8")),
        verdict=check.get("verdict", "needs_review"),
        reason=check.get("reason"),
        preview=check.get("preview"),
        domain_score=check.get("domain_score", 0.0),
        official_score=check.get("official_score", 0.0),
        dataset_match_score=check.get("dataset_match_score", 0.0),
        source_matches=check.get("source_matches", []),
        safety_reason=check.get("safety_reason"),
    )


@app.get("/api/attachments/{attachment_id}")
def api_get_attachment(
    attachment_id: str,
    request: Request,
    user_id: str = Query("demo-user"),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict:
    _require_auth(request, user_id, x_api_key)
    att = get_attachment(attachment_id, user_id=user_id)
    if not att:
        raise HTTPException(status_code=404, detail="Attachment not found")
    return att


@app.get("/api/chats/{chat_id}/attachments")
def api_list_chat_attachments(
    chat_id: str,
    request: Request,
    user_id: str = Query("demo-user"),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> list[dict]:
    _require_auth(request, user_id, x_api_key)
    return list_attachments_for_chat(chat_id, user_id=user_id)


# ── Source helpers ─────────────────────────────────────────────────────────────
_DATASET_SOURCE_REGISTRY: dict | None = None


def _load_dataset_source_registry() -> dict:
    global _DATASET_SOURCE_REGISTRY
    if _DATASET_SOURCE_REGISTRY is not None:
        return _DATASET_SOURCE_REGISTRY
    registry: dict = {}
    dataset_path = (
        Path(__file__).resolve().parents[1]
        / "data" / "maithuylaw_dataset" / "data" / "index" / "rag_chunks.json"
    )
    try:
        chunks = json.loads(dataset_path.read_text(encoding="utf-8"))
    except Exception:
        _DATASET_SOURCE_REGISTRY = registry
        return registry

    for chunk in chunks:
        meta = chunk.get("metadata") or {}
        doc_id = meta.get("doc_id") or meta.get("source_id") or chunk.get("doc_id") or ""
        title = (
            meta.get("title") or meta.get("source_title")
            or chunk.get("title") or meta.get("source") or doc_id
        )
        url = (
            meta.get("canonical_url") or meta.get("url")
            or meta.get("source_url") or meta.get("link")
            or chunk.get("canonical_url") or chunk.get("url") or ""
        )
        info = {
            "doc_id": doc_id,
            "title": title,
            "url": url,
            "publisher": meta.get("publisher") or chunk.get("publisher") or "",
            "official_domain": meta.get("official_domain") or chunk.get("official_domain") or "",
            "source_type": meta.get("source_type") or meta.get("type") or chunk.get("source_type") or "",
        }
        for key in (doc_id, meta.get("chunk_id"), meta.get("exact_number_symbol")):
            k = str(key or "").strip()
            if k and k not in registry:
                registry[k] = info

    _DATASET_SOURCE_REGISTRY = registry
    return registry


def _source_to_dict(source) -> dict:
    if isinstance(source, dict):
        return source
    try:
        return source.model_dump(exclude_none=True)
    except Exception:
        return {}


def _normalize_response_sources(sources: list) -> list[dict]:
    if not sources:
        return []
    registry = _load_dataset_source_registry()
    seen: set[str] = set()
    result = []
    for item in sources:
        d = _source_to_dict(item)
        doc_id = d.get("doc_id") or d.get("source_id") or ""
        title = d.get("title") or d.get("source_title") or doc_id or "Nguồn tham khảo"
        url = (
            d.get("canonical_url") or d.get("url")
            or d.get("source_url") or d.get("link") or ""
        )
        reg = registry.get(doc_id) or {}
        publisher = d.get("publisher") or reg.get("publisher") or ""
        official_domain = d.get("official_domain") or reg.get("official_domain") or ""
        source_type = d.get("source_type") or d.get("type") or reg.get("source_type") or ""
        if not url:
            url = reg.get("url") or ""
        key = doc_id or url or title
        if key in seen:
            continue
        if key:
            seen.add(key)
        result.append({
            "title": title,
            "url": url or None,
            "canonical_url": url or None,
            "publisher": publisher or None,
            "official_domain": official_domain or None,
            "source_type": source_type or None,
            "doc_id": doc_id or None,
        })
    return result


def _reduce_citation_spam(answer: str, sources: list[dict]) -> str:
    if len(sources) != 1:
        return answer
    return re.sub(r"(\[1\]\s*){3,}", "[1] ", answer).strip()


def _normalize_citations(answer: str, sources: list[dict]) -> str:
    if not answer or not sources:
        return answer

    def fix(match):
        nums = sorted(set(int(n) for n in re.findall(r"\d+", match.group(1))))
        valid = [n for n in nums if 1 <= n <= len(sources)]
        return "[" + ",".join(str(n) for n in valid) + "]" if valid else ""

    return re.sub(r"\[([0-9,\s]+)\]", fix, answer)


def _source_label(item: dict, index: int) -> Source:
    meta = item.get("metadata") or {}
    doc_id = meta.get("doc_id") or item.get("doc_id") or ""
    title = (
        meta.get("title") or meta.get("source_title")
        or meta.get("source") or doc_id or f"Nguồn {index}"
    )
    url = (
        meta.get("canonical_url") or meta.get("url")
        or meta.get("source_url") or meta.get("link") or ""
    )
    return Source(
        title=title,
        canonical_url=url or None,
        url=url or None,
        publisher=meta.get("publisher") or None,
        official_domain=meta.get("official_domain") or None,
        source_type=meta.get("source_type") or meta.get("type") or "",
        doc_id=doc_id or None,
        score=item.get("score"),
    )


def _attachment_source(att: dict, index: int) -> Source:
    return Source(
        title=att.get("name") or att.get("url") or f"Tệp đính kèm {index}",
        url=att.get("url") or None,
        canonical_url=att.get("url") or None,
        source_type="attachment",
    )


def _request_language(req: ChatRequest) -> str:
    lang = getattr(req, "language", "vi") or "vi"
    return "en" if str(lang).lower().startswith("en") else "vi"


# ── /api/chat — main product endpoint ─────────────────────────────────────────
@app.post("/api/chat", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> ChatResponse:
    _require_auth(request, req.user_id, x_api_key)
    check_budget(req.user_id)

    message = req.message.strip()
    active = ensure_chat(req.chat_id, req.user_id, first_message=message)
    chat_id = active["id"]

    # Collect link attachments from message body
    message_urls = extract_urls(message)
    merged_links: list[str] = []
    for url in list(req.links or []) + message_urls:
        if url not in merged_links:
            merged_links.append(url)

    saved_links, failed_links = [], []
    for url in merged_links:
        fetched = await fetch_link_text(url)
        if fetched.get("ok"):
            saved_links.append(save_attachment(
                user_id=req.user_id, chat_id=chat_id,
                name=url, kind="link", url=url,
                text=f"URL: {url}\n\n{fetched['text']}",
                size_bytes=len(fetched["text"].encode("utf-8")),
            ))
        else:
            failed_links.append({
                "id": None, "user_id": req.user_id, "chat_id": chat_id,
                "name": url, "kind": "link", "url": url, "verdict": "rejected",
                "reason": fetched.get("error") or "Không đọc được link.",
                "safety_reason": None, "domain_score": 0.0, "official_score": 0.0,
                "dataset_match_score": 0.0, "source_matches": [], "preview": "", "text": "",
            })

    all_ids = list(req.attachment_ids or []) + [a["id"] for a in saved_links if a.get("id")]
    attachments = resolve_attachments(all_ids, user_id=req.user_id)
    attachments.extend(failed_links)

    attachment_text = "\n\n".join(a.get("text", "")[:2500] for a in attachments)

    # Safety guard — runs before Gemini
    safety_reason = detect_safety_issue(message + "\n" + attachment_text[:3000])
    if safety_reason:
        from backend.guards import REFUSAL_MESSAGE
        add_message(chat_id, "user", message, req.user_id)
        add_message(chat_id, "assistant", REFUSAL_MESSAGE, req.user_id)
        record_budget_usage(req.user_id)
        logger.info(json.dumps({"event": "safety_refused", "user_id": req.user_id}))
        return ChatResponse(chat_id=chat_id, refused=True, reason=safety_reason, answer=REFUSAL_MESSAGE, sources=[])

    # Domain guard
    attachment_allows_domain = any(
        a.get("verdict") in {"accepted", "needs_review"} and float(a.get("domain_score") or 0) >= 0.3
        for a in attachments
    )
    if not attachments and not is_in_domain(message):
        out_msg = (
            "Mình chỉ hỗ trợ tra cứu thông tin pháp luật, chính sách và tin tức chính thống "
            "liên quan đến ma túy. Bạn hãy đặt câu hỏi trong phạm vi này nhé."
        )
        add_message(chat_id, "user", message, req.user_id)
        add_message(chat_id, "assistant", out_msg, req.user_id)
        return ChatResponse(chat_id=chat_id, refused=True, reason="out_of_domain", answer=out_msg, sources=[])

    if attachments and not attachment_allows_domain and not is_in_domain(message):
        out_msg = (
            "Nội dung đính kèm chưa đủ phù hợp với phạm vi pháp luật về ma túy. "
            "Bạn có thể gửi nguồn chính thống hơn hoặc hỏi lại trong đúng phạm vi."
        )
        add_message(chat_id, "user", message, req.user_id)
        add_message(chat_id, "assistant", out_msg, req.user_id)
        return ChatResponse(chat_id=chat_id, refused=True, reason="attachment_out_of_domain", answer=out_msg, sources=[])

    # Retrieval
    retrieval_query = rewrite_with_memory(message, chat_id, req.user_id)
    if attachment_text:
        retrieval_query += "\n\nNội dung đính kèm:\n" + attachment_text[:2500]

    dataset_results = retrieve(retrieval_query, top_k=TOP_K)
    dataset_sources = [_source_label(item, i) for i, item in enumerate(dataset_results, start=1)]
    attachment_sources = [_attachment_source(att, i) for i, att in enumerate(attachments, start=1)]

    language = _request_language(req)
    answer = generate_answer(
        message=message,
        dataset_results=dataset_results,
        attachments=attachments,
        language=language,
    )

    if not attachments and wants_realtime(message) and not realtime_enabled():
        answer = realtime_unavailable_answer(language)

    add_message(chat_id, "user", message, req.user_id)
    add_message(chat_id, "assistant", answer, req.user_id)
    record_budget_usage(req.user_id)

    normalized = _normalize_response_sources(attachment_sources + dataset_sources)
    safe_answer = _normalize_citations(answer, normalized)
    safe_answer = _reduce_citation_spam(safe_answer, normalized)

    logger.info(json.dumps({
        "event": "chat",
        "user_id": req.user_id,
        "chat_id": chat_id,
        "sources_count": len(normalized),
    }))

    return ChatResponse(chat_id=chat_id, answer=safe_answer, sources=normalized)


# ── Generate chat title ────────────────────────────────────────────────────────
@app.post("/api/chats/{chat_id}/generate-title", response_model=GenerateTitleResponse)
async def generate_title_for_chat(
    chat_id: str,
    payload: GenerateTitleRequest,
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    _require_auth(request, payload.user_id, x_api_key)
    language = "en" if payload.language.lower().startswith("en") else "vi"
    title = generate_chat_title(payload.message, language)
    for args in ((chat_id, title, payload.user_id), (chat_id, title)):
        try:
            updated = rename_chat(*args)
            if updated:
                break
        except (TypeError, Exception):
            continue
    return GenerateTitleResponse(chat_id=chat_id, title=title)


# ── Serve React SPA (frontend/dist) ───────────────────────────────────────────
_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"

if _DIST.exists():
    _assets = _DIST / "assets"
    if _assets.exists():
        app.mount("/assets", StaticFiles(directory=str(_assets)), name="assets")

    # Serve favicon and public assets
    for _static_file in ("favicon.png", "favicon.svg", "maithuylaw-logo.png", "maithuylaw-logo.svg"):
        _fp = _DIST / _static_file
        if _fp.exists():
            _path = f"/{_static_file}"

            def _make_handler(path=str(_fp)):
                async def _handler():
                    return FileResponse(path)
                return _handler

            app.get(_path, include_in_schema=False)(_make_handler())

    @app.get("/", include_in_schema=False)
    async def root():
        index = _DIST / "index.html"
        if index.exists():
            return FileResponse(str(index))
        raise HTTPException(status_code=404)

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        # Don't intercept API or utility routes
        skip = ("api/", "health", "ready", "usage", "ask")
        if any(full_path == s or full_path.startswith(s) for s in skip):
            raise HTTPException(status_code=404)
        index = _DIST / "index.html"
        if index.exists():
            return FileResponse(str(index))
        raise HTTPException(status_code=404)
