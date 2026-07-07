"""
MaiThuyLaw AI — Auth & Quota

Auth model:
  - If MAITHUYLAW_API_KEY env is empty/unset → public access, no key required.
    Rate limit + safety guard + domain guard are the protection layers.
    Use this for the public web UI on Railway (same-origin, no key in JS bundle).
  - If MAITHUYLAW_API_KEY is set → requests must supply matching X-API-Key header.
    Use this when you want to restrict access (external integrations, admin tools).

Rate limit:
  - Default: 10 req/min per user (MAITHUYLAW_RATE_LIMIT_PER_MINUTE to override).
  - Daily cap: 500 req/day per user (MAITHUYLAW_DAILY_LIMIT to override).
  - Sliding-window in-memory; resets on process restart.
  - Returns Retry-After header on 429.
"""
from __future__ import annotations

import os
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import HTTPException, Request

_LOCK = threading.Lock()
_MINUTE_BUCKETS: dict[str, list[float]] = defaultdict(list)
_DAILY_BUCKETS: dict[str, dict[str, int]] = defaultdict(dict)


# ── Config helpers ─────────────────────────────────────────────────────────────

def _api_key() -> str:
    """Return the expected API key, or '' if public access is allowed."""
    raw = os.getenv("MAITHUYLAW_API_KEY", os.getenv("AGENT_API_KEY", "")).strip()
    return raw


def _rate_per_minute() -> int:
    return int(os.getenv("MAITHUYLAW_RATE_LIMIT_PER_MINUTE", "10"))


def _daily_limit() -> int:
    return int(os.getenv("MAITHUYLAW_DAILY_LIMIT", "500"))


def _today_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _client_key(request: Request, user_id: str | None) -> str:
    user = (user_id or "").strip() or request.headers.get("X-User-ID", "").strip() or "anonymous"
    host = request.client.host if request.client else "unknown"
    return f"{user}:{host}"


# ── Auth-only (no quota consumed) ─────────────────────────────────────────────

def verify_api_key(request: Request, x_api_key: str | None) -> None:
    """
    Check API key only — does NOT consume rate-limit quota.
    Use this when you want to authenticate without incrementing the counter
    (e.g. in a wrapper that immediately delegates to an inner handler that
    will also call auth_and_quota).
    """
    expected = _api_key()
    if not expected:
        return  # public access — no key required
    if not x_api_key or x_api_key.strip() != expected:
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid X-API-Key.",
        )


# ── Quota-only ─────────────────────────────────────────────────────────────────

def enforce_quota(request: Request, user_id: str | None = None) -> None:
    """Consume one request slot. Raises 429 with Retry-After if limit hit."""
    now = time.time()
    window_start = now - 60
    key = _client_key(request, user_id)
    today = _today_key()
    limit = _rate_per_minute()

    with _LOCK:
        recent = [ts for ts in _MINUTE_BUCKETS[key] if ts >= window_start]

        if len(recent) >= limit:
            retry_after = max(1, int(recent[0] + 60 - now) + 1)
            _MINUTE_BUCKETS[key] = recent
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "Rate limit exceeded",
                    "limit": limit,
                    "window_seconds": 60,
                    "retry_after_seconds": retry_after,
                },
                headers={"Retry-After": str(retry_after)},
            )

        day_count = _DAILY_BUCKETS[key].get(today, 0)
        if day_count >= _daily_limit():
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "Daily quota exceeded",
                    "limit": _daily_limit(),
                    "resets_at": "midnight UTC",
                },
                headers={"Retry-After": "3600"},
            )

        recent.append(now)
        _MINUTE_BUCKETS[key] = recent
        _DAILY_BUCKETS[key] = {today: day_count + 1}


# ── Combined: auth + quota (standard endpoint guard) ──────────────────────────

def auth_and_quota(
    request: Request,
    user_id: str | None = None,
    x_api_key: str | None = None,
) -> None:
    """
    Authenticate AND consume one quota slot.
    This is the standard guard for product endpoints (/api/chat, /api/chats, etc.).
    Call this exactly once per request — never chain two calls or you double-count.
    """
    verify_api_key(request, x_api_key)
    enforce_quota(request, user_id=user_id)
