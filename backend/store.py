from __future__ import annotations

import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from backend.config import PROJECT_ROOT
from backend.persistence import redis_client

RUNTIME_DIR = PROJECT_ROOT / "data" / "runtime"
STORE_PATH = RUNTIME_DIR / "chats.json"
_LOCK = threading.RLock()
_MAX_MESSAGES = max(20, int(os.getenv("MAITHUYLAW_MAX_MESSAGES_PER_CHAT", "200")))
_MAX_CHATS = max(20, int(os.getenv("MAITHUYLAW_MAX_CHATS_PER_USER", "200")))
_CHAT_TTL = max(3600, int(os.getenv("MAITHUYLAW_CHAT_TTL_SECONDS", str(60 * 60 * 24 * 90))))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _timestamp() -> float:
    return time.time()


def _empty_store() -> dict:
    return {"chats": {}}


def _load_store() -> dict:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    if not STORE_PATH.exists():
        return _empty_store()
    try:
        data = json.loads(STORE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) and isinstance(data.get("chats"), dict) else _empty_store()
    except Exception:
        return _empty_store()


def _save_store(data: dict) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STORE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STORE_PATH)


def _chat_key(chat_id: str) -> str:
    return f"maithuylaw:chat:{chat_id}"


def _user_index_key(user_id: str) -> str:
    return f"maithuylaw:user:{user_id}:chats"


def _auto_title(message: str) -> str:
    text = " ".join(str(message or "").split())
    return (text[:48] + ("..." if len(text) > 48 else "")) if text else "Đoạn chat mới"


def _new_chat(user_id: str, title: str | None, first_message: str | None = None) -> dict:
    now = _now()
    return {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "title": title or _auto_title(first_message or ""),
        "created_at": now,
        "updated_at": now,
        "messages": [],
    }


def _redis_get_chat(chat_id: str) -> dict | None:
    client = redis_client()
    if client is None:
        return None
    try:
        raw = client.get(_chat_key(chat_id))
        value = json.loads(raw) if raw else None
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def _redis_save_chat(chat: dict) -> bool:
    client = redis_client()
    if client is None:
        return False
    try:
        payload = json.dumps(chat, ensure_ascii=False, separators=(",", ":"))
        pipe = client.pipeline()
        pipe.setex(_chat_key(chat["id"]), _CHAT_TTL, payload)
        pipe.zadd(_user_index_key(chat["user_id"]), {chat["id"]: _timestamp()})
        pipe.expire(_user_index_key(chat["user_id"]), _CHAT_TTL)
        pipe.execute()
        return True
    except Exception:
        return False


def create_chat(user_id: str = "demo-user", title: str | None = None) -> dict:
    uid = user_id or "demo-user"
    chat = _new_chat(uid, title)
    if _redis_save_chat(chat):
        client = redis_client()
        if client is not None:
            stale = client.zrange(_user_index_key(uid), 0, -_MAX_CHATS - 1)
            if stale:
                pipe = client.pipeline()
                for chat_id in stale:
                    pipe.delete(_chat_key(chat_id))
                    pipe.zrem(_user_index_key(uid), chat_id)
                pipe.execute()
        return chat
    with _LOCK:
        data = _load_store()
        data["chats"][chat["id"]] = chat
        user_chats = [c for c in data["chats"].values() if c.get("user_id") == uid]
        for old in sorted(user_chats, key=lambda c: c.get("updated_at") or "")[:-_MAX_CHATS]:
            data["chats"].pop(old["id"], None)
        _save_store(data)
    return chat


def ensure_chat(chat_id: str | None, user_id: str, first_message: str | None = None) -> dict | None:
    uid = user_id or "demo-user"
    if chat_id:
        return get_chat(chat_id, uid)
    return create_chat(uid, _auto_title(first_message or ""))


def list_chats(user_id: str = "demo-user") -> list[dict]:
    uid = user_id or "demo-user"
    client = redis_client()
    chats: list[dict] = []
    if client is not None:
        try:
            ids = client.zrevrange(_user_index_key(uid), 0, _MAX_CHATS - 1)
            stale: list[str] = []
            for chat_id in ids:
                chat = _redis_get_chat(chat_id)
                if chat and chat.get("user_id") == uid:
                    chats.append(chat)
                else:
                    stale.append(chat_id)
            if stale:
                client.zrem(_user_index_key(uid), *stale)
        except Exception:
            chats = []
    if not chats and client is None:
        data = _load_store()
        chats = [c for c in data.get("chats", {}).values() if c.get("user_id") == uid]
    summaries = [
        {
            "id": c["id"],
            "user_id": uid,
            "title": c.get("title", "Đoạn chat mới"),
            "created_at": c.get("created_at"),
            "updated_at": c.get("updated_at"),
            "message_count": len(c.get("messages", [])),
        }
        for c in chats
    ]
    return sorted(summaries, key=lambda c: c.get("updated_at") or "", reverse=True)


def get_chat(chat_id: str, user_id: str = "demo-user") -> dict | None:
    uid = user_id or "demo-user"
    client = redis_client()
    if client is not None:
        chat = _redis_get_chat(chat_id)
    else:
        chat = _load_store().get("chats", {}).get(chat_id)
    if not chat or chat.get("user_id") != uid:
        return None
    return chat


def _mutate_chat(chat_id: str, user_id: str, mutator) -> dict | None:
    uid = user_id or "demo-user"
    client = redis_client()
    if client is not None:
        key = _chat_key(chat_id)
        for _ in range(3):
            try:
                with client.pipeline() as pipe:
                    pipe.watch(key)
                    raw = pipe.get(key)
                    chat = json.loads(raw) if raw else None
                    if not isinstance(chat, dict) or chat.get("user_id") != uid:
                        pipe.unwatch()
                        return None
                    mutator(chat)
                    pipe.multi()
                    pipe.setex(key, _CHAT_TTL, json.dumps(chat, ensure_ascii=False, separators=(",", ":")))
                    pipe.zadd(_user_index_key(uid), {chat_id: _timestamp()})
                    pipe.execute()
                    return chat
            except Exception:
                continue
        return None
    with _LOCK:
        data = _load_store()
        chat = data.get("chats", {}).get(chat_id)
        if not chat or chat.get("user_id") != uid:
            return None
        mutator(chat)
        _save_store(data)
        return chat


def rename_chat(chat_id: str, title: str, user_id: str = "demo-user") -> dict | None:
    def mutate(chat: dict) -> None:
        chat["title"] = " ".join(str(title or "Đoạn chat mới").split())[:80]
        chat["updated_at"] = _now()

    return _mutate_chat(chat_id, user_id, mutate)


def delete_chat(chat_id: str, user_id: str = "demo-user") -> bool:
    uid = user_id or "demo-user"
    if not get_chat(chat_id, uid):
        return False
    client = redis_client()
    if client is not None:
        try:
            pipe = client.pipeline()
            pipe.delete(_chat_key(chat_id))
            pipe.zrem(_user_index_key(uid), chat_id)
            pipe.execute()
            return True
        except Exception:
            return False
    with _LOCK:
        data = _load_store()
        chat = data.get("chats", {}).get(chat_id)
        if not chat or chat.get("user_id") != uid:
            return False
        del data["chats"][chat_id]
        _save_store(data)
        return True


def add_message(
    chat_id: str,
    role: str,
    content: str,
    user_id: str = "demo-user",
    **metadata: Any,
) -> dict | None:
    created: dict[str, Any] = {}

    def mutate(chat: dict) -> None:
        nonlocal created
        created = {
            "id": str(uuid.uuid4()),
            "role": role,
            "content": content,
            "created_at": _now(),
        }
        for key in ("sources", "refused", "reason", "evidence_level", "confidence", "safety", "follow_up_suggestions", "attachments"):
            if key in metadata and metadata[key] is not None:
                created[key] = metadata[key]
        messages = chat.setdefault("messages", [])
        messages.append(created)
        if len(messages) > _MAX_MESSAGES:
            del messages[:-_MAX_MESSAGES]
        chat["updated_at"] = created["created_at"]

    return created if _mutate_chat(chat_id, user_id, mutate) else None


def history_text(chat_id: str, user_id: str = "demo-user", limit: int = 4) -> str:
    chat = get_chat(chat_id, user_id)
    if not chat:
        return ""
    lines = []
    for msg in chat.get("messages", [])[-limit * 2 :]:
        content = " ".join(str(msg.get("content", "")).split())
        lines.append(f"{msg.get('role', '')}: {content[:417] + '...' if len(content) > 420 else content}")
    return "\n".join(lines)


FOLLOWUP_MARKERS = [
    "vậy", "thế", "còn", "trường hợp đó", "người đó", "họ", "nó",
    "tiếp", "như trên", "ý đó", "cái đó", "thì sao",
]


def rewrite_with_memory(message: str, chat_id: str, user_id: str = "demo-user") -> str:
    q = str(message or "").strip()
    lower = q.lower()
    if len(lower.split()) > 8 and not any(marker in lower for marker in FOLLOWUP_MARKERS):
        return q
    chat = get_chat(chat_id, user_id)
    if not chat:
        return q
    previous = [m.get("content", "") for m in chat.get("messages", []) if m.get("role") == "user"]
    return f"{previous[-1]}. Câu hỏi tiếp theo: {q}" if previous else q
