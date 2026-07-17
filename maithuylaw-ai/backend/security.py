"""Authentication, signed anonymous sessions, and shared rate limits."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import HTTPException, Request

from backend.persistence import redis_client

_LOCK = threading.Lock()
_MINUTE_BUCKETS: dict[str, list[float]] = defaultdict(list)
_DAILY_BUCKETS: dict[str, dict[str, int]] = defaultdict(dict)
_PROCESS_SECRET = secrets.token_bytes(32)
SESSION_COOKIE = "maithuylaw_session"


def _api_key() -> str:
    return os.getenv("MAITHUYLAW_API_KEY", os.getenv("AGENT_API_KEY", "")).strip()


def _session_secret() -> bytes:
    configured = os.getenv("MAITHUYLAW_SESSION_SECRET", "").strip()
    if configured:
        return configured.encode("utf-8")
    if _api_key():
        return _api_key().encode("utf-8")
    return _PROCESS_SECRET


def session_secret_configured() -> bool:
    return bool(os.getenv("MAITHUYLAW_SESSION_SECRET", "").strip() or _api_key())


def _sign(value: str) -> str:
    return hmac.new(_session_secret(), value.encode("utf-8"), hashlib.sha256).hexdigest()


def _encode_session(value: str) -> str:
    raw = base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")
    return f"{raw}.{_sign(raw)}"


def _decode_session(cookie: str | None) -> str | None:
    if not cookie or "." not in cookie:
        return None
    raw, signature = cookie.rsplit(".", 1)
    if not hmac.compare_digest(signature, _sign(raw)):
        return None
    try:
        padded = raw + "=" * (-len(raw) % 4)
        value = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    except Exception:
        return None
    return value if 8 <= len(value) <= 128 else None


def ensure_session(request: Request) -> str:
    state_value = getattr(request.state, "session_id", None)
    if state_value:
        return state_value
    existing = _decode_session(request.cookies.get(SESSION_COOKIE))
    if existing:
        request.state.session_id = existing
        return existing
    generated = secrets.token_urlsafe(24)
    request.state.session_id = generated
    request.state.session_cookie_value = _encode_session(generated)
    return generated


def effective_user_id(request: Request, claimed_user_id: str | None) -> str:
    """Use a signed session for public users; retain claimed IDs for keyed integrations."""
    if _api_key():
        claimed = (claimed_user_id or "").strip()
        return f"api:{claimed or 'default-user'}"
    return f"anon:{ensure_session(request)}"


def apply_session_cookie(request: Request, response) -> None:
    value = getattr(request.state, "session_cookie_value", None)
    if not value:
        return
    response.set_cookie(
        key=SESSION_COOKIE,
        value=value,
        httponly=True,
        secure=os.getenv("ENVIRONMENT", "production").lower() == "production",
        samesite="lax",
        max_age=60 * 60 * 24 * 365,
        path="/",
    )


def _rate_per_minute() -> int:
    return max(1, int(os.getenv("MAITHUYLAW_RATE_LIMIT_PER_MINUTE", "10")))


def _daily_limit() -> int:
    return max(1, int(os.getenv("MAITHUYLAW_DAILY_LIMIT", "500")))


def _today_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _network_identity(request: Request) -> str:
    host = request.client.host if request.client else "unknown"
    # Keep user-controlled user_id out of the primary quota identity.
    ua = request.headers.get("user-agent", "")[:256]
    session = ensure_session(request)
    digest = hashlib.sha256(f"{host}|{ua}|{session}".encode("utf-8")).hexdigest()[:32]
    return digest


def verify_api_key(request: Request, x_api_key: str | None) -> None:
    expected = _api_key()
    if not expected:
        ensure_session(request)
        return
    supplied = (x_api_key or "").strip()
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Missing or invalid X-API-Key.")


def _enforce_quota_redis(key: str) -> bool:
    client = redis_client()
    if client is None:
        return False
    now = int(time.time())
    minute_key = f"maithuylaw:quota:minute:{key}:{now // 60}"
    daily_key = f"maithuylaw:quota:day:{key}:{_today_key()}"
    try:
        pipe = client.pipeline()
        pipe.incr(minute_key)
        pipe.expire(minute_key, 120)
        pipe.incr(daily_key)
        pipe.expire(daily_key, 172800)
        minute_count, _, day_count, _ = pipe.execute()
    except Exception:
        return False
    if int(minute_count) > _rate_per_minute():
        retry_after = max(1, 60 - now % 60)
        raise HTTPException(
            status_code=429,
            detail={"error": "Rate limit exceeded", "limit": _rate_per_minute(), "window_seconds": 60},
            headers={"Retry-After": str(retry_after)},
        )
    if int(day_count) > _daily_limit():
        raise HTTPException(
            status_code=429,
            detail={"error": "Daily quota exceeded", "limit": _daily_limit(), "resets_at": "midnight UTC"},
            headers={"Retry-After": "3600"},
        )
    return True


def enforce_quota(request: Request, user_id: str | None = None) -> None:
    now = time.time()
    key = _network_identity(request)
    if _enforce_quota_redis(key):
        return

    window_start = now - 60
    today = _today_key()
    with _LOCK:
        recent = [ts for ts in _MINUTE_BUCKETS[key] if ts >= window_start]
        if len(recent) >= _rate_per_minute():
            retry_after = max(1, int(recent[0] + 60 - now) + 1)
            _MINUTE_BUCKETS[key] = recent
            raise HTTPException(
                status_code=429,
                detail={"error": "Rate limit exceeded", "limit": _rate_per_minute(), "window_seconds": 60},
                headers={"Retry-After": str(retry_after)},
            )
        day_count = _DAILY_BUCKETS[key].get(today, 0)
        if day_count >= _daily_limit():
            raise HTTPException(
                status_code=429,
                detail={"error": "Daily quota exceeded", "limit": _daily_limit(), "resets_at": "midnight UTC"},
                headers={"Retry-After": "3600"},
            )
        recent.append(now)
        _MINUTE_BUCKETS[key] = recent
        _DAILY_BUCKETS[key] = {today: day_count + 1}


def auth_and_quota(request: Request, user_id: str | None = None, x_api_key: str | None = None) -> str:
    verify_api_key(request, x_api_key)
    resolved = effective_user_id(request, user_id)
    enforce_quota(request, user_id=resolved)
    return resolved
