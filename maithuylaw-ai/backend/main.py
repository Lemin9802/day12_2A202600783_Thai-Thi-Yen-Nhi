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

from backend.attachments import (
    delete_attachments_for_chat,
    get_attachment,
    list_attachments_for_chat,
    resolve_attachments,
    save_attachment,
)
from backend.config import APP_NAME, DATASET_PATH, MIN_SCORE, TOP_K
from backend.dataset import dataset_summary, retrieve
from backend.file_checker import evaluate_uploaded_text, extract_upload_text, fetch_link_text
from backend.guards import detect_safety_issue, is_in_domain
from backend.intent import route_intent
from backend.security import (
    apply_session_cookie,
    auth_and_quota,
    effective_user_id,
    session_secret_configured,
    verify_api_key as _verify_api_key_only,
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
from backend.usage import ensure_budget_available, get_usage, record_generation_usage
from backend.workflow import run_legal_workflow
from backend.persistence import storage_status
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

logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","message":"%(message)s"}',
)
logger = logging.getLogger(__name__)

START_TIME = time.time()
APP_VERSION = os.getenv("APP_VERSION", "1.0.0")
ENVIRONMENT = os.getenv("ENVIRONMENT", "production")

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


_is_ready = False
_dataset_chunks = 0
_startup_error: str | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _is_ready, _dataset_chunks, _startup_error
    _is_ready = False
    _startup_error = None
    try:
        summary = dataset_summary()
        _dataset_chunks = int(summary.get("chunks", 0) or 0)
        if _dataset_chunks <= 0:
            raise RuntimeError("RAG dataset is empty")
        _is_ready = True
        logger.info(json.dumps({
            "event": "startup",
            "app": APP_NAME,
            "version": APP_VERSION,
            "environment": ENVIRONMENT,
            "dataset_chunks": _dataset_chunks,
            "storage": storage_status(),
        }, ensure_ascii=False))
    except Exception as exc:
        _startup_error = str(exc)
        logger.exception("Startup validation failed")
    yield
    _is_ready = False
    logger.info(json.dumps({"event": "shutdown"}))


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
async def _response_hardening(request: Request, call_next):
    response = await call_next(request)
    content_type = response.headers.get("content-type", "")
    if content_type.startswith("application/json") and "charset=" not in content_type.lower():
        response.headers["content-type"] = "application/json; charset=utf-8"
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    apply_session_cookie(request, response)
    return response


def _require_auth(request: Request, user_id: str, x_api_key: str | None) -> str:
    """Authenticate, consume quota, and return the server-resolved owner ID."""
    return auth_and_quota(request, user_id=user_id, x_api_key=x_api_key)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "app": APP_NAME,
        "version": APP_VERSION,
        "environment": ENVIRONMENT,
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "dataset_chunks": _dataset_chunks,
        "storage": storage_status(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/ready")
def ready():
    checks = {
        "dataset_available": DATASET_PATH.exists(),
        "dataset_chunks": _dataset_chunks,
        "storage": storage_status(),
        "gemini_configured": bool(os.getenv("GEMINI_API_KEY", "").strip() or os.getenv("GOOGLE_API_KEY", "").strip()),
        "session_secret_configured": session_secret_configured(),
    }
    if not _is_ready or not checks["dataset_available"] or _dataset_chunks <= 0:
        raise HTTPException(
            status_code=503,
            detail={"ready": False, "error": _startup_error or "Required data is unavailable", "checks": checks},
        )
    return {"ready": True, "checks": checks}


@app.get("/usage")
def usage_endpoint(
    request: Request,
    user_id: str = Query("demo-user"),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    uid = _require_auth(request, user_id, x_api_key)
    return get_usage(uid)


class _LegacyAskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)
    user_id: str | None = None


@app.get("/history")
def history_endpoint(
    request: Request,
    user_id: str = Query("demo-user"),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    uid = _require_auth(request, user_id, x_api_key)
    return {
        "user_id": uid,
        "chats": list_chats(user_id=uid),
        "storage": storage_status()["backend"],
    }


@app.post("/ask")
async def legacy_ask(
    body: _LegacyAskRequest,
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    uid = body.user_id or "default-user"
    _verify_api_key_only(request, x_api_key)
    req = ChatRequest(message=body.question, user_id=uid)
    result = await chat(req, request, x_api_key=x_api_key)
    rate_limit_pm = int(os.getenv("MAITHUYLAW_RATE_LIMIT_PER_MINUTE", "10"))
    resolved_uid = effective_user_id(request, uid)
    budget_info = get_usage(resolved_uid)
    return {
        "user_id": uid,
        "question": body.question,
        "answer": result.answer,
        "sources": result.sources,
        "refused": result.refused,
        "history_count": 0,
        "served_by": APP_NAME,
        "storage": storage_status()["backend"],
        "rate_limit": {"limit": rate_limit_pm, "window_seconds": 60, "note": "per-user sliding window"},
        "budget": {
            "estimated_cost_usd": budget_info["estimated_cost_usd"],
            "monthly_budget_usd": budget_info["monthly_budget_usd"],
            "remaining_usd": budget_info["remaining_usd"],
            "request_count": budget_info["request_count"],
        },
    }


@app.get("/api/chats")
def api_list_chats(
    request: Request,
    user_id: str = Query("demo-user"),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    uid = _require_auth(request, user_id, x_api_key)
    return {"chats": list_chats(user_id=uid)}


@app.post("/api/chats")
def api_create_chat(
    req: CreateChatRequest,
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    uid = _require_auth(request, req.user_id, x_api_key)
    return create_chat(user_id=uid, title=req.title or "Cuộc trò chuyện mới")


@app.get("/api/chats/{chat_id}")
def api_get_chat(
    chat_id: str,
    request: Request,
    user_id: str = Query("demo-user"),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    uid = _require_auth(request, user_id, x_api_key)
    chat_obj = get_chat(chat_id, user_id=uid)
    if not chat_obj:
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat_obj


@app.patch("/api/chats/{chat_id}")
def api_rename_chat(
    chat_id: str,
    req: RenameChatRequest,
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    uid = _require_auth(request, req.user_id, x_api_key)
    updated = rename_chat(chat_id, title=req.title, user_id=uid)
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
    uid = _require_auth(request, user_id, x_api_key)
    if not delete_chat(chat_id, user_id=uid):
        raise HTTPException(status_code=404, detail="Chat not found")
    delete_attachments_for_chat(chat_id, user_id=uid)
    return {"deleted": True, "chat_id": chat_id}


def _validated_upload_result(result: dict) -> dict:
    if result.get("ok"):
        return result
    raise HTTPException(status_code=int(result.get("status_code") or 422), detail=result.get("error") or "Không đọc được tệp.")


@app.post("/api/upload-check")
async def api_upload_check(
    request: Request,
    file: UploadFile = File(...),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict:
    claimed = request.headers.get("X-User-ID") or "demo-user"
    _require_auth(request, claimed, x_api_key)
    extracted = _validated_upload_result(await extract_upload_text(file))
    return {"ok": True, **evaluate_uploaded_text(extracted["text"]), "filename": extracted["filename"], "size_bytes": extracted["size_bytes"]}


@app.post("/api/attachments/upload")
async def api_attachment_upload(
    request: Request,
    file: UploadFile = File(...),
    user_id: str = Form("demo-user"),
    chat_id: str | None = Form(None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict:
    uid = _require_auth(request, user_id, x_api_key)
    if chat_id and not get_chat(chat_id, user_id=uid):
        raise HTTPException(status_code=404, detail="Chat not found")
    extracted = _validated_upload_result(await extract_upload_text(file))
    evaluation = evaluate_uploaded_text(extracted["text"])
    return save_attachment(
        user_id=uid,
        chat_id=chat_id,
        name=extracted["filename"],
        kind="file",
        text=extracted["text"],
        size_bytes=extracted["size_bytes"],
        evaluation=evaluation,
    )


@app.post("/api/attachments/link")
async def api_attachment_link(
    req: LinkAttachmentRequest,
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict:
    uid = _require_auth(request, req.user_id, x_api_key)
    if req.chat_id and not get_chat(req.chat_id, user_id=uid):
        raise HTTPException(status_code=404, detail="Chat not found")
    fetched = await fetch_link_text(req.url)
    if not fetched.get("ok"):
        raise HTTPException(status_code=400, detail=fetched.get("error") or "Không đọc được link.")
    canonical_url = fetched["url"]
    evaluation = evaluate_uploaded_text(fetched["text"], source_url=canonical_url)
    return save_attachment(
        user_id=uid,
        chat_id=req.chat_id,
        name=req.title or canonical_url,
        kind="link",
        url=canonical_url,
        text=fetched["text"],
        size_bytes=len(fetched["text"].encode("utf-8")),
        evaluation=evaluation,
    )


@app.get("/api/attachments/{attachment_id}")
def api_get_attachment(
    attachment_id: str,
    request: Request,
    user_id: str = Query("demo-user"),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict:
    uid = _require_auth(request, user_id, x_api_key)
    attachment = get_attachment(attachment_id, user_id=uid)
    if not attachment:
        raise HTTPException(status_code=404, detail="Attachment not found")
    return attachment


@app.get("/api/chats/{chat_id}/attachments")
def api_list_chat_attachments(
    chat_id: str,
    request: Request,
    user_id: str = Query("demo-user"),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> list[dict]:
    uid = _require_auth(request, user_id, x_api_key)
    if not get_chat(chat_id, user_id=uid):
        raise HTTPException(status_code=404, detail="Chat not found")
    return list_attachments_for_chat(chat_id, user_id=uid)


_DATASET_SOURCE_REGISTRY: dict | None = None


def _load_dataset_source_registry() -> dict:
    global _DATASET_SOURCE_REGISTRY
    if _DATASET_SOURCE_REGISTRY is not None:
        return _DATASET_SOURCE_REGISTRY
    registry: dict = {}
    dataset_path = Path(__file__).resolve().parents[1] / "data" / "maithuylaw_dataset" / "data" / "index" / "rag_chunks.json"
    try:
        chunks = json.loads(dataset_path.read_text(encoding="utf-8"))
    except Exception:
        _DATASET_SOURCE_REGISTRY = registry
        return registry
    for chunk in chunks:
        meta = chunk.get("metadata") or {}
        doc_id = meta.get("doc_id") or meta.get("source_id") or chunk.get("doc_id") or ""
        title = meta.get("title") or meta.get("source_title") or chunk.get("title") or meta.get("source") or doc_id
        url = meta.get("canonical_url") or meta.get("url") or meta.get("source_url") or meta.get("link") or chunk.get("canonical_url") or chunk.get("url") or ""
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
        url = d.get("canonical_url") or d.get("url") or d.get("source_url") or d.get("link") or ""
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
    title = meta.get("title") or meta.get("source_title") or meta.get("source") or doc_id or f"Nguồn {index}"
    url = meta.get("canonical_url") or meta.get("url") or meta.get("source_url") or meta.get("link") or ""
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


@app.post("/api/chat", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> ChatResponse:
    uid = _require_auth(request, req.user_id, x_api_key)
    ensure_budget_available(uid)
    message = req.message.strip()
    active = ensure_chat(req.chat_id, uid, first_message=message)
    if active is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    chat_id = active["id"]

    safety_reason = detect_safety_issue(message)
    if safety_reason:
        from backend.guards import REFUSAL_MESSAGE
        response = ChatResponse(
            chat_id=chat_id,
            refused=True,
            reason=safety_reason,
            answer=REFUSAL_MESSAGE,
            sources=[],
            evidence_level="Câu hỏi nhạy cảm",
            confidence=1.0,
            safety={"allowed": False, "risk_level": "disallowed", "reason": safety_reason},
        )
        add_message(chat_id, "user", message, uid)
        add_message(chat_id, "assistant", response.answer, uid, refused=True, reason=response.reason, evidence_level=response.evidence_level, confidence=response.confidence, safety=response.safety, follow_up_suggestions=response.follow_up_suggestions)
        record_generation_usage(uid)
        return response

    saved_link_ids: list[str] = []
    for link in req.links:
        fetched = await fetch_link_text(link)
        if not fetched.get("ok"):
            continue
        evaluation = evaluate_uploaded_text(fetched["text"], source_url=fetched["url"])
        saved = save_attachment(
            user_id=uid,
            chat_id=chat_id,
            name=fetched["url"],
            kind="link",
            url=fetched["url"],
            text=fetched["text"],
            size_bytes=len(fetched["text"].encode("utf-8")),
            evaluation=evaluation,
        )
        if saved.get("id") and saved.get("verdict") == "accepted":
            saved_link_ids.append(saved["id"])

    all_ids = list(req.attachment_ids) + saved_link_ids
    attachments = resolve_attachments(all_ids, user_id=uid, allowed_verdicts=("accepted",))
    attachment_text = "\n\n".join(item.get("text", "")[:2500] for item in attachments)
    attachment_allows_domain = any(float(item.get("domain_score") or 0) >= 0.2 for item in attachments)
    if not is_in_domain(message) and not attachment_allows_domain:
        out_msg = "Mình chỉ hỗ trợ tra cứu thông tin pháp luật, chính sách và nguồn tin chính thống liên quan đến ma túy tại Việt Nam. Bạn hãy đặt câu hỏi trong phạm vi này nhé."
        response = ChatResponse(chat_id=chat_id, refused=True, reason="out_of_domain", answer=out_msg, sources=[], evidence_level="Ngoài phạm vi hỗ trợ", confidence=1.0)
        add_message(chat_id, "user", message, uid)
        add_message(chat_id, "assistant", response.answer, uid, refused=True, reason=response.reason, evidence_level=response.evidence_level, confidence=response.confidence, safety=response.safety, follow_up_suggestions=response.follow_up_suggestions)
        record_generation_usage(uid)
        return response

    intent = route_intent(message)
    retrieval_query = rewrite_with_memory(intent.query_rewrite, chat_id, uid)
    if attachment_text:
        retrieval_query += "\n\nNội dung nguồn đã xác minh:\n" + attachment_text[:2500]
    consented_search = req.controlled_search or message.lower().strip() == "tìm thêm nguồn chính thống"
    language = _request_language(req)
    workflow = run_legal_workflow(
        message=message,
        retrieval_query=retrieval_query,
        intent=intent,
        attachments=attachments,
        language=language,
        controlled_search=consented_search,
        top_k=TOP_K,
    )
    dataset_sources = [_source_label(item, index) for index, item in enumerate(workflow.dataset_results, start=1)]
    attachment_sources = [_attachment_source(item, index) for index, item in enumerate(attachments, start=1)]
    normalized = _normalize_response_sources(dataset_sources + attachment_sources)
    safe_answer = _reduce_citation_spam(_normalize_citations(workflow.answer, normalized), normalized)
    if workflow.blocked_reason:
        logger.warning(json.dumps({"event": "output_safety_block", "reason": workflow.blocked_reason, "chat_id": chat_id}, ensure_ascii=False))
        normalized = []
    response = ChatResponse(
        chat_id=chat_id,
        answer=safe_answer,
        sources=normalized,
        citation_verification=workflow.citation_verification.to_dict() if workflow.citation_verification else {},
    )
    add_message(chat_id, "user", message, uid, attachments=[item.get("id") for item in attachments])
    add_message(
        chat_id,
        "assistant",
        response.answer,
        uid,
        sources=response.sources,
        refused=response.refused,
        reason=response.reason,
        evidence_level=response.evidence_level,
        confidence=response.confidence,
        safety=response.safety,
        follow_up_suggestions=response.follow_up_suggestions,
        citation_verification=response.citation_verification,
    )
    record_generation_usage(uid, workflow.generation_usage)
    logger.info(json.dumps({"event": "chat", "user_id": uid, "chat_id": chat_id, "intent": intent.intent, "required_sources": intent.required_sources, "search_recommended": intent.needs_controlled_search, "agent_trace": workflow.trace, "sources_count": len(normalized)}, ensure_ascii=False))
    return response


@app.post("/api/chats/{chat_id}/generate-title", response_model=GenerateTitleResponse)
async def generate_title_for_chat(
    chat_id: str,
    payload: GenerateTitleRequest,
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    uid = _require_auth(request, payload.user_id, x_api_key)
    if not get_chat(chat_id, user_id=uid):
        raise HTTPException(status_code=404, detail="Chat not found")
    language = "en" if payload.language.lower().startswith("en") else "vi"
    title = generate_chat_title(payload.message, language)
    updated = rename_chat(chat_id, title, uid)
    if not updated:
        raise HTTPException(status_code=404, detail="Chat not found")
    return GenerateTitleResponse(chat_id=chat_id, title=title)


_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"

if _DIST.exists():
    _assets = _DIST / "assets"
    if _assets.exists():
        app.mount("/assets", StaticFiles(directory=str(_assets)), name="assets")
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
        skip = ("api/", "health", "ready", "usage", "ask")
        if any(full_path == s or full_path.startswith(s) for s in skip):
            raise HTTPException(status_code=404)
        index = _DIST / "index.html"
        if index.exists():
            return FileResponse(str(index))
        raise HTTPException(status_code=404)
