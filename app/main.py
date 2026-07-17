import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from .auth import verify_api_key
from .config import settings
from .cost_guard import check_budget, get_usage, record_usage
from .rate_limiter import check_rate_limit
from utils.mock_llm import ask as mock_ask
from app.ui import render_home


logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format='{"time":"%(asctime)s","level":"%(levelname)s","message":"%(message)s"}',
)
logger = logging.getLogger(__name__)

START_TIME = time.time()
INSTANCE_ID = os.getenv("INSTANCE_ID", f"instance-{uuid.uuid4().hex[:6]}")
_is_ready = False
_in_flight_requests = 0

try:
    import redis

    redis_client = redis.from_url(settings.redis_url, decode_responses=True)
    redis_client.ping()
    USE_REDIS = True
except Exception:
    redis_client = None
    USE_REDIS = False
    memory_sessions: dict[str, list[dict]] = {}


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)
    user_id: str | None = None


class AskResponse(BaseModel):
    user_id: str
    question: str
    answer: str
    history_count: int
    served_by: str
    storage: str
    rate_limit: dict
    budget: dict


def _history_key(user_id: str) -> str:
    return f"history:{user_id}"


def load_history(user_id: str) -> list[dict]:
    if USE_REDIS and redis_client:
        raw_items = redis_client.lrange(_history_key(user_id), 0, -1)
        return [json.loads(item) for item in raw_items]

    return memory_sessions.get(user_id, [])


def append_history(user_id: str, role: str, content: str) -> None:
    message = {
        "role": role,
        "content": content,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "instance_id": INSTANCE_ID,
    }

    if USE_REDIS and redis_client:
        key = _history_key(user_id)
        redis_client.rpush(key, json.dumps(message))
        redis_client.ltrim(key, -20, -1)
        redis_client.expire(key, 30 * 24 * 3600)
        return

    history = memory_sessions.setdefault(user_id, [])
    history.append(message)
    memory_sessions[user_id] = history[-20:]


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _is_ready
    logger.info(json.dumps({
        "event": "startup",
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "instance_id": INSTANCE_ID,
        "storage": "redis" if USE_REDIS else "in-memory",
    }))
    _is_ready = True

    yield

    _is_ready = False
    logger.info(json.dumps({
        "event": "shutdown",
        "in_flight_requests": _in_flight_requests,
        "instance_id": INSTANCE_ID,
    }))


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)

@app.get("/", include_in_schema=False)
async def home():
    return render_home()



@app.middleware("http")
async def track_in_flight_requests(request, call_next):
    global _in_flight_requests
    _in_flight_requests += 1
    try:
        return await call_next(request)
    finally:
        _in_flight_requests -= 1


@app.get("/health")
def health():
    redis_ok = False

    if USE_REDIS and redis_client:
        try:
            redis_client.ping()
            redis_ok = True
        except Exception:
            redis_ok = False

    return {
        "status": "ok" if (not USE_REDIS or redis_ok) else "degraded",
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "version": settings.app_version,
        "environment": settings.environment,
        "instance_id": INSTANCE_ID,
        "storage": "redis" if USE_REDIS else "in-memory",
        "redis_connected": redis_ok if USE_REDIS else "not_configured",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/ready")
def ready():
    if not _is_ready:
        raise HTTPException(status_code=503, detail="Agent is not ready")

    if USE_REDIS and redis_client:
        try:
            redis_client.ping()
        except Exception:
            raise HTTPException(status_code=503, detail="Redis is not ready")

    return {
        "ready": True,
        "instance_id": INSTANCE_ID,
        "in_flight_requests": _in_flight_requests,
    }


@app.post("/ask", response_model=AskResponse)
def ask_agent(body: AskRequest, auth_user_id: str = Depends(verify_api_key)):
    user_id = body.user_id or auth_user_id
    rate_info = check_rate_limit(user_id)
    check_budget(user_id)

    append_history(user_id, "user", body.question)
    answer = mock_ask(body.question)
    append_history(user_id, "assistant", answer)

    usage = record_usage(user_id)
    history = load_history(user_id)

    logger.info(json.dumps({
        "event": "ask",
        "user_id": user_id,
        "question_length": len(body.question),
        "history_count": len(history),
        "instance_id": INSTANCE_ID,
    }))

    return AskResponse(
        user_id=user_id,
        question=body.question,
        answer=answer,
        history_count=len(history),
        served_by=INSTANCE_ID,
        storage="redis" if USE_REDIS else "in-memory",
        rate_limit=rate_info,
        budget=get_usage(user_id),
    )


@app.get("/history")
def history(user_id: str = Depends(verify_api_key)):
    return {
        "user_id": user_id,
        "messages": load_history(user_id),
    }


@app.get("/usage")
def usage(user_id: str = Depends(verify_api_key)):
    return get_usage(user_id)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )
