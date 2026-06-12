"""Production-ready FastAPI agent for the Day 12 final project."""
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from redis.exceptions import RedisError

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import estimate_cost, get_monthly_cost, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import append_history, get_history, ping_redis, redis_client
from utils.mock_llm import ask as llm_ask


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "level": record.levelname,
                "message": record.getMessage(),
            },
            ensure_ascii=False,
        )


handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    handlers=[handler],
    force=True,
)
logger = logging.getLogger(__name__)

START_TIME = time.time()
INSTANCE_ID = os.getenv("HOSTNAME", "local")
_is_ready = False


def log_event(event: str, **fields: object) -> None:
    logger.info(json.dumps({"event": event, **fields}, ensure_ascii=False))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _is_ready
    log_event(
        "startup",
        app=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
        instance=INSTANCE_ID,
    )
    try:
        ping_redis()
        _is_ready = True
        log_event("ready", redis="ok")
    except RedisError as exc:
        _is_ready = False
        logger.error("Redis unavailable during startup: %s", exc)

    yield

    # Uvicorn handles SIGTERM, drains in-flight requests, then enters this block.
    _is_ready = False
    log_event("shutdown", instance=INSTANCE_ID)


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/docs" if settings.environment != "production" else None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-API-Key"],
)


@app.middleware("http")
async def request_middleware(request: Request, call_next):
    started = time.perf_counter()
    try:
        response: Response = await call_next(request)
    except Exception:
        try:
            redis_client.incr("metrics:errors")
        except RedisError:
            pass
        raise

    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Agent-Instance"] = INSTANCE_ID
    duration_ms = round((time.perf_counter() - started) * 1000, 1)

    try:
        redis_client.incr("metrics:requests")
    except RedisError:
        pass

    log_event(
        "request",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        duration_ms=duration_ms,
        instance=INSTANCE_ID,
    )
    return response


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    user_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")


class AskResponse(BaseModel):
    question: str
    answer: str
    user_id: str
    model: str
    history_items: int
    monthly_cost_usd: float
    instance_id: str
    timestamp: str


@app.get("/", tags=["Info"])
def root():
    return {
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "instance_id": INSTANCE_ID,
        "endpoints": {
            "ask": "POST /ask (requires X-API-Key)",
            "health": "GET /health",
            "ready": "GET /ready",
            "metrics": "GET /metrics (requires X-API-Key)",
        },
    }


@app.post("/ask", response_model=AskResponse, tags=["Agent"])
async def ask_agent(
    body: AskRequest,
    request: Request,
    _api_key: str = Depends(verify_api_key),
):
    try:
        check_rate_limit(body.user_id)
        history = get_history(body.user_id)

        input_tokens = max(1, len(body.question.split()) * 2)
        answer = await run_in_threadpool(llm_ask, body.question)
        output_tokens = max(1, len(answer.split()) * 2)
        monthly_cost = record_cost(
            body.user_id,
            estimate_cost(input_tokens, output_tokens),
        )
        append_history(body.user_id, body.question, answer)
    except RedisError as exc:
        logger.exception("Redis operation failed")
        raise HTTPException(status_code=503, detail="Storage unavailable") from exc

    log_event(
        "agent_call",
        user_id=body.user_id,
        question_length=len(body.question),
        history_items=len(history),
        client=request.client.host if request.client else "unknown",
        instance=INSTANCE_ID,
    )

    return AskResponse(
        question=body.question,
        answer=answer,
        user_id=body.user_id,
        model=settings.llm_model,
        history_items=len(history) + 1,
        monthly_cost_usd=round(monthly_cost, 8),
        instance_id=INSTANCE_ID,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@app.get("/health", tags=["Operations"])
def health():
    return {
        "status": "ok",
        "version": settings.app_version,
        "environment": settings.environment,
        "instance_id": INSTANCE_ID,
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/ready", tags=["Operations"])
def ready():
    try:
        redis_ready = ping_redis()
    except RedisError as exc:
        raise HTTPException(status_code=503, detail="Redis unavailable") from exc
    if not _is_ready or not redis_ready:
        raise HTTPException(status_code=503, detail="Agent not ready")
    return {"ready": True, "redis": "ok", "instance_id": INSTANCE_ID}


@app.get("/metrics", tags=["Operations"])
def metrics(api_key: str = Depends(verify_api_key)):
    user_id = f"key-{api_key[:8]}"
    try:
        request_count = int(redis_client.get("metrics:requests") or 0)
        error_count = int(redis_client.get("metrics:errors") or 0)
        monthly_cost = get_monthly_cost(user_id)
    except RedisError as exc:
        raise HTTPException(status_code=503, detail="Metrics unavailable") from exc

    return {
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "total_requests": request_count,
        "error_count": error_count,
        "monthly_cost_usd": round(monthly_cost, 8),
        "monthly_budget_usd": settings.monthly_budget_usd,
        "instance_id": INSTANCE_ID,
    }


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        timeout_graceful_shutdown=30,
    )
