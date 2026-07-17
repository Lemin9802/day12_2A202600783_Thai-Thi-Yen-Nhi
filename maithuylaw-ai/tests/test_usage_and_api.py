from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import backend.security as security
import backend.usage as usage
from backend.main import app


class FakeRedisPipeline:
    def __init__(self, redis):
        self.redis = redis
        self.commands = []

    def hincrby(self, key, field, value): self.commands.append(("hincrby", key, field, value)); return self
    def hincrbyfloat(self, key, field, value): self.commands.append(("hincrbyfloat", key, field, value)); return self
    def hset(self, key, mapping): self.commands.append(("hset", key, mapping)); return self
    def expire(self, key, ttl): self.commands.append(("expire", key, ttl)); return self

    def execute(self):
        for command in self.commands:
            name, key, *args = command
            record = self.redis.data.setdefault(key, {})
            if name == "hincrby":
                field, value = args; record[field] = str(int(float(record.get(field, 0))) + int(value))
            elif name == "hincrbyfloat":
                field, value = args; record[field] = str(float(record.get(field, 0)) + float(value))
            elif name == "hset":
                mapping = args[0]; record.update({field: str(value) for field, value in mapping.items()})
        return []


class FakeRedis:
    def __init__(self): self.data = {}
    def pipeline(self): return FakeRedisPipeline(self)
    def hgetall(self, key): return dict(self.data.get(key, {}))


def test_token_cost_is_persisted_with_atomic_redis_updates(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(usage, "redis_client", lambda: fake)
    monkeypatch.setenv("MAITHUYLAW_INPUT_COST_PER_MILLION_USD", "1")
    monkeypatch.setenv("MAITHUYLAW_OUTPUT_COST_PER_MILLION_USD", "2")
    result = usage.record_generation_usage("user-1", {
        "provider": "gemini", "model": "test", "prompt_tokens": 1000,
        "output_tokens": 500, "llm_called": True,
    })
    assert result["request_count"] == 1
    assert result["llm_request_count"] == 1
    assert result["total_tokens"] == 1500
    assert result["estimated_cost_usd"] == pytest.approx(0.002)
    assert result["storage"] == "redis"


def test_budget_guard_uses_persisted_estimated_cost(monkeypatch):
    monkeypatch.setattr(usage, "get_usage", lambda user_id: {"estimated_cost_usd": 1.0, "monthly_budget_usd": 1.0})
    with pytest.raises(HTTPException) as exc:
        usage.ensure_budget_available("user-1")
    assert exc.value.status_code == 402


def test_history_compatibility_endpoint():
    with TestClient(app) as client:
        created = client.post("/api/chats", json={"user_id": "demo", "title": "History test"})
        assert created.status_code == 200
        history = client.get("/history", params={"user_id": "demo"})
        assert history.status_code == 200
        assert any(chat["id"] == created.json()["id"] for chat in history.json()["chats"])


def test_api_key_and_rate_limit(monkeypatch):
    security._MINUTE_BUCKETS.clear()
    security._DAILY_BUCKETS.clear()
    monkeypatch.setenv("MAITHUYLAW_API_KEY", "secret")
    monkeypatch.setenv("MAITHUYLAW_RATE_LIMIT_PER_MINUTE", "1")
    with TestClient(app) as client:
        assert client.get("/api/chats", params={"user_id": "demo"}).status_code == 401
        headers = {"X-API-Key": "secret"}
        assert client.get("/api/chats", params={"user_id": "demo"}, headers=headers).status_code == 200
        limited = client.get("/api/chats", params={"user_id": "demo"}, headers=headers)
        assert limited.status_code == 429
