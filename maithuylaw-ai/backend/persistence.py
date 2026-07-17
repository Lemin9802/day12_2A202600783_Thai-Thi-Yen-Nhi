from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def redis_client():
    """Return a short-timeout Redis client when REDIS_URL is usable."""
    url = os.getenv("REDIS_URL", "").strip()
    if not url:
        return None
    try:
        import redis

        client = redis.Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=1.5,
            socket_timeout=1.5,
            health_check_interval=30,
        )
        client.ping()
        return client
    except Exception as exc:  # pragma: no cover - depends on external Redis
        logger.warning("Redis unavailable, using local fallback: %s", exc)
        return None


def redis_json_get(key: str) -> dict[str, Any] | None:
    client = redis_client()
    if client is None:
        return None
    try:
        raw = client.get(key)
        if not raw:
            return None
        value = json.loads(raw)
        return value if isinstance(value, dict) else None
    except Exception as exc:  # pragma: no cover
        logger.warning("Redis read failed for %s: %s", key, exc)
        return None


def redis_json_set(key: str, value: dict[str, Any], *, ttl_seconds: int | None = None) -> bool:
    client = redis_client()
    if client is None:
        return False
    try:
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if ttl_seconds:
            client.setex(key, ttl_seconds, payload)
        else:
            client.set(key, payload)
        return True
    except Exception as exc:  # pragma: no cover
        logger.warning("Redis write failed for %s: %s", key, exc)
        return False


def redis_delete(*keys: str) -> bool:
    client = redis_client()
    if client is None:
        return False
    try:
        if keys:
            client.delete(*keys)
        return True
    except Exception as exc:  # pragma: no cover
        logger.warning("Redis delete failed: %s", exc)
        return False


def storage_status() -> dict[str, Any]:
    client = redis_client()
    return {
        "backend": "redis" if client is not None else "local-json",
        "redis_configured": bool(os.getenv("REDIS_URL", "").strip()),
        "redis_available": client is not None,
    }
