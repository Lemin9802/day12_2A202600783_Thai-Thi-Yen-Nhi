"""Persistent token and estimated-cost accounting.

Redis is the production backend. A local JSON fallback keeps development and
single-process tests deterministic without pretending to be shared storage.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from backend.config import PROJECT_ROOT
from backend.persistence import redis_client

_USAGE_PATH = PROJECT_ROOT / "data" / "runtime" / "usage.json"
_LOCK = threading.RLock()
_USAGE_TTL_SECONDS = 60 * 60 * 24 * 400

# Configurable estimates. Billing remains provider-controlled and may change.
_DEFAULT_MODEL_PRICING_PER_MILLION = {
    "gemini-3.1-flash-lite": (0.10, 0.40),
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.5-flash": (0.30, 2.50),
}


def _month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _usage_key(user_id: str, month: str | None = None) -> str:
    return f"maithuylaw:usage:{month or _month()}:{user_id}"


def _monthly_budget() -> float:
    return max(0.0, float(os.getenv("MONTHLY_BUDGET_USD", "10.0")))


def _pricing(model: str) -> tuple[float, float]:
    model_key = str(model or "").strip().lower()
    default_input, default_output = _DEFAULT_MODEL_PRICING_PER_MILLION.get(model_key, (0.10, 0.40))
    input_rate = float(os.getenv("MAITHUYLAW_INPUT_COST_PER_MILLION_USD", str(default_input)))
    output_rate = float(os.getenv("MAITHUYLAW_OUTPUT_COST_PER_MILLION_USD", str(default_output)))
    return max(input_rate, 0.0), max(output_rate, 0.0)


def estimate_cost_usd(model: str, prompt_tokens: int, output_tokens: int) -> float:
    input_rate, output_rate = _pricing(model)
    return (max(prompt_tokens, 0) * input_rate + max(output_tokens, 0) * output_rate) / 1_000_000


def _empty_record(user_id: str, month: str | None = None) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "month": month or _month(),
        "request_count": 0,
        "llm_request_count": 0,
        "prompt_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "estimated_cost_usd": 0.0,
        "last_model": None,
        "updated_at": None,
    }


def _coerce_record(user_id: str, raw: dict[str, Any] | None, month: str | None = None) -> dict[str, Any]:
    record = _empty_record(user_id, month)
    if raw:
        for key in record:
            if key in raw:
                record[key] = raw[key]
    for key in ("request_count", "llm_request_count", "prompt_tokens", "output_tokens", "total_tokens"):
        record[key] = int(float(record.get(key) or 0))
    record["estimated_cost_usd"] = float(record.get("estimated_cost_usd") or 0.0)
    return record


def _read_local() -> dict[str, Any]:
    if not _USAGE_PATH.exists():
        return {"records": {}}
    try:
        value = json.loads(_USAGE_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) and isinstance(value.get("records"), dict) else {"records": {}}
    except Exception:
        return {"records": {}}


def _write_local(data: dict[str, Any]) -> None:
    _USAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _USAGE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_USAGE_PATH)


def _get_redis_record(user_id: str) -> dict[str, Any] | None:
    client = redis_client()
    if client is None:
        return None
    try:
        raw = client.hgetall(_usage_key(user_id))
        return _coerce_record(user_id, raw) if raw else _empty_record(user_id)
    except Exception:
        return None


def get_usage(user_id: str) -> dict[str, Any]:
    record = _get_redis_record(user_id)
    backend = "redis"
    if record is None:
        backend = "local-json"
        with _LOCK:
            data = _read_local()
            key = _usage_key(user_id)
            record = _coerce_record(user_id, data["records"].get(key))
    budget = _monthly_budget()
    return {
        **record,
        "estimated_cost_usd": round(float(record["estimated_cost_usd"]), 8),
        "monthly_budget_usd": budget,
        "remaining_usd": round(max(0.0, budget - float(record["estimated_cost_usd"])), 8),
        "storage": backend,
    }


def ensure_budget_available(user_id: str) -> None:
    usage = get_usage(user_id)
    if float(usage["estimated_cost_usd"]) >= float(usage["monthly_budget_usd"]):
        raise HTTPException(
            status_code=402,
            detail={
                "error": "Monthly token budget exceeded",
                "user_id": user_id,
                "estimated_cost_usd": usage["estimated_cost_usd"],
                "monthly_budget_usd": usage["monthly_budget_usd"],
                "resets_at": "next month UTC",
            },
        )


def record_generation_usage(user_id: str, generation: dict[str, Any] | None = None) -> dict[str, Any]:
    generation = generation or {}
    provider = str(generation.get("provider") or "none")
    model = str(generation.get("model") or "")
    prompt_tokens = max(0, int(generation.get("prompt_tokens") or 0))
    output_tokens = max(0, int(generation.get("output_tokens") or 0))
    llm_called = bool(generation.get("llm_called") or provider == "gemini")
    cost = estimate_cost_usd(model, prompt_tokens, output_tokens) if llm_called else 0.0
    updated_at = datetime.now(timezone.utc).isoformat()

    client = redis_client()
    if client is not None:
        key = _usage_key(user_id)
        try:
            pipe = client.pipeline()
            pipe.hincrby(key, "request_count", 1)
            pipe.hincrby(key, "llm_request_count", 1 if llm_called else 0)
            pipe.hincrby(key, "prompt_tokens", prompt_tokens)
            pipe.hincrby(key, "output_tokens", output_tokens)
            pipe.hincrby(key, "total_tokens", prompt_tokens + output_tokens)
            pipe.hincrbyfloat(key, "estimated_cost_usd", cost)
            pipe.hset(key, mapping={
                "user_id": user_id,
                "month": _month(),
                "last_model": model,
                "updated_at": updated_at,
            })
            pipe.expire(key, _USAGE_TTL_SECONDS)
            pipe.execute()
            return get_usage(user_id)
        except Exception:
            pass

    with _LOCK:
        data = _read_local()
        key = _usage_key(user_id)
        record = _coerce_record(user_id, data["records"].get(key))
        record["request_count"] += 1
        record["llm_request_count"] += 1 if llm_called else 0
        record["prompt_tokens"] += prompt_tokens
        record["output_tokens"] += output_tokens
        record["total_tokens"] += prompt_tokens + output_tokens
        record["estimated_cost_usd"] += cost
        record["last_model"] = model or record.get("last_model")
        record["updated_at"] = updated_at
        data["records"][key] = record
        _write_local(data)
    return get_usage(user_id)
