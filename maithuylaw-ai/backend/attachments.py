from __future__ import annotations

import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Iterable

from backend.config import PROJECT_ROOT
from backend.file_checker import clean_text, evaluate_uploaded_text
from backend.persistence import redis_client

RUNTIME_DIR = PROJECT_ROOT / "data" / "runtime"
ATTACHMENTS_PATH = RUNTIME_DIR / "attachments.json"
_LOCK = threading.RLock()
_TTL = max(3600, int(os.getenv("MAITHUYLAW_ATTACHMENT_TTL_SECONDS", str(60 * 60 * 24 * 30))))
_MAX_TEXT = max(2000, int(os.getenv("MAITHUYLAW_ATTACHMENT_TEXT_CHARS", "12000")))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty_store() -> dict:
    return {"attachments": {}}


def _load_store() -> dict:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    if not ATTACHMENTS_PATH.exists():
        return _empty_store()
    try:
        data = json.loads(ATTACHMENTS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) and isinstance(data.get("attachments"), dict) else _empty_store()
    except Exception:
        return _empty_store()


def _save_store(data: dict) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    tmp = ATTACHMENTS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(ATTACHMENTS_PATH)


def _attachment_key(attachment_id: str) -> str:
    return f"maithuylaw:attachment:{attachment_id}"


def _chat_index(chat_id: str) -> str:
    return f"maithuylaw:chat:{chat_id}:attachments"


def _redis_save(item: dict) -> bool:
    client = redis_client()
    if client is None:
        return False
    try:
        payload = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
        pipe = client.pipeline()
        pipe.setex(_attachment_key(item["id"]), _TTL, payload)
        if item.get("chat_id"):
            pipe.zadd(_chat_index(item["chat_id"]), {item["id"]: time.time()})
            pipe.expire(_chat_index(item["chat_id"]), _TTL)
        pipe.execute()
        return True
    except Exception:
        return False


def save_attachment(
    *,
    user_id: str,
    chat_id: str | None,
    name: str,
    kind: str,
    text: str,
    size_bytes: int | None = None,
    url: str | None = None,
    evaluation: dict | None = None,
) -> dict:
    check = evaluation or evaluate_uploaded_text(text, source_url=url)
    attachment_id = str(uuid.uuid4())
    item = {
        "id": attachment_id,
        "user_id": user_id or "demo-user",
        "chat_id": chat_id,
        "name": name,
        "kind": kind,
        "url": url,
        "size_bytes": size_bytes,
        "created_at": _now(),
        "text": clean_text(text)[:_MAX_TEXT],
        **check,
    }
    if not _redis_save(item):
        with _LOCK:
            data = _load_store()
            data["attachments"][attachment_id] = item
            _save_store(data)
    return public_attachment(item, include_text=False)


def _raw_attachment(attachment_id: str) -> dict | None:
    client = redis_client()
    if client is not None:
        try:
            raw = client.get(_attachment_key(attachment_id))
            value = json.loads(raw) if raw else None
            return value if isinstance(value, dict) else None
        except Exception:
            return None
    return _load_store().get("attachments", {}).get(attachment_id)


def get_attachment(attachment_id: str, user_id: str = "demo-user", include_text: bool = False) -> dict | None:
    item = _raw_attachment(attachment_id)
    if not item or item.get("user_id") != (user_id or "demo-user"):
        return None
    return public_attachment(item, include_text=include_text)


def list_attachments_for_chat(chat_id: str, user_id: str = "demo-user") -> list[dict]:
    uid = user_id or "demo-user"
    client = redis_client()
    raw_items: list[dict] = []
    if client is not None:
        try:
            ids = client.zrevrange(_chat_index(chat_id), 0, -1)
            raw_items = [item for attachment_id in ids if (item := _raw_attachment(attachment_id))]
        except Exception:
            raw_items = []
    else:
        raw_items = list(_load_store().get("attachments", {}).values())
    return sorted(
        [public_attachment(item) for item in raw_items if item.get("user_id") == uid and item.get("chat_id") == chat_id],
        key=lambda item: item.get("created_at") or "",
        reverse=True,
    )


def resolve_attachments(
    attachment_ids: list[str],
    user_id: str = "demo-user",
    *,
    allowed_verdicts: Iterable[str] = ("accepted",),
) -> list[dict]:
    allowed = set(allowed_verdicts)
    resolved: list[dict] = []
    for attachment_id in dict.fromkeys(attachment_ids or []):
        item = get_attachment(attachment_id, user_id=user_id, include_text=True)
        if item and item.get("verdict") in allowed:
            resolved.append(item)
    return resolved


def delete_attachments_for_chat(chat_id: str, user_id: str = "demo-user") -> int:
    items = list_attachments_for_chat(chat_id, user_id)
    if not items:
        return 0
    client = redis_client()
    if client is not None:
        try:
            pipe = client.pipeline()
            for item in items:
                pipe.delete(_attachment_key(item["id"]))
            pipe.delete(_chat_index(chat_id))
            pipe.execute()
            return len(items)
        except Exception:
            return 0
    with _LOCK:
        data = _load_store()
        for item in items:
            data["attachments"].pop(item["id"], None)
        _save_store(data)
    return len(items)


def public_attachment(item: dict, include_text: bool = False) -> dict:
    result = {
        "id": item.get("id"),
        "user_id": item.get("user_id"),
        "chat_id": item.get("chat_id"),
        "name": item.get("name"),
        "kind": item.get("kind"),
        "url": item.get("url"),
        "size_bytes": item.get("size_bytes"),
        "created_at": item.get("created_at"),
        "verdict": item.get("verdict"),
        "reason": item.get("reason"),
        "safety_reason": item.get("safety_reason"),
        "domain_score": item.get("domain_score"),
        "official_score": item.get("official_score"),
        "dataset_match_score": item.get("dataset_match_score"),
        "source_matches": item.get("source_matches", []),
        "preview": item.get("preview", ""),
    }
    if include_text:
        result["text"] = item.get("text", "")
    return result
