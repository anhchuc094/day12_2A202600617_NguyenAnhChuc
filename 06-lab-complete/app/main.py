"""Production-ready FastAPI agent for the Day 12 final project."""
import json
import hashlib
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
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


async def run_agent(body: AskRequest, request: Request, rate_namespace: str) -> AskResponse:
    try:
        check_rate_limit(
            body.user_id,
            limit=(
                settings.demo_rate_limit_per_minute
                if rate_namespace == "demo-rate"
                else settings.rate_limit_per_minute
            ),
            namespace=rate_namespace,
        )
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
        mode="demo" if rate_namespace == "demo-rate" else "authenticated",
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


@app.get("/", response_class=HTMLResponse, tags=["Info"])
def root():
    return """<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Production AI Agent</title>
  <style>
    :root { color-scheme: dark; --bg:#07111f; --panel:#0d1b2d; --line:#20334d; --text:#edf5ff; --muted:#91a5bd; --cyan:#36d7c7; --blue:#5b8cff; --red:#ff6b7a; }
    * { box-sizing: border-box; }
    body { margin:0; min-height:100vh; font-family:Inter,Segoe UI,Arial,sans-serif; color:var(--text); background:radial-gradient(circle at 15% 0%,#15345d 0,transparent 35%),radial-gradient(circle at 90% 15%,#173a3c 0,transparent 30%),var(--bg); }
    .shell { width:min(1040px,calc(100% - 32px)); margin:auto; padding:40px 0; }
    header { display:flex; justify-content:space-between; align-items:center; gap:20px; margin-bottom:24px; }
    .eyebrow { color:var(--cyan); font-size:12px; font-weight:800; letter-spacing:.16em; text-transform:uppercase; }
    h1 { margin:8px 0 6px; font-size:clamp(30px,5vw,52px); letter-spacing:-.04em; }
    .subtitle,.hint { color:var(--muted); }
    .badge { padding:9px 13px; border:1px solid #2c5261; border-radius:999px; background:#0b252b; color:#8af1e7; white-space:nowrap; }
    .grid { display:grid; grid-template-columns:1.45fr .75fr; gap:20px; }
    .card { background:linear-gradient(160deg,rgba(18,36,59,.96),rgba(9,23,39,.96)); border:1px solid var(--line); border-radius:20px; padding:22px; box-shadow:0 20px 60px rgba(0,0,0,.28); }
    .card h2 { margin:0 0 16px; font-size:18px; }
    label { display:block; color:#bfd0e3; font-size:13px; font-weight:700; margin:14px 0 7px; }
    input,textarea { width:100%; border:1px solid #29415e; border-radius:12px; background:#071423; color:var(--text); padding:12px 14px; outline:none; font:inherit; }
    input:focus,textarea:focus { border-color:var(--cyan); box-shadow:0 0 0 3px rgba(54,215,199,.12); }
    textarea { min-height:130px; resize:vertical; }
    .actions { display:flex; gap:10px; margin-top:16px; flex-wrap:wrap; }
    .mode { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:12px 14px; margin-bottom:14px; border:1px solid #29415e; border-radius:14px; background:#091725; }
    .mode input { width:auto; }
    .hidden { display:none; }
    button { border:0; border-radius:12px; padding:11px 16px; font-weight:800; cursor:pointer; color:#04151a; background:linear-gradient(135deg,var(--cyan),#7ce8bb); }
    button.secondary { color:var(--text); background:#1a304b; border:1px solid #2b4868; }
    button:disabled { opacity:.55; cursor:wait; }
    .status-row { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
    .status { border:1px solid var(--line); border-radius:14px; padding:14px; background:#091725; }
    .status strong { display:block; margin-bottom:4px; }
    .dot { display:inline-block; width:9px; height:9px; margin-right:7px; border-radius:50%; background:#718096; }
    .dot.ok { background:var(--cyan); box-shadow:0 0 12px var(--cyan); }
    pre { margin:16px 0 0; min-height:190px; overflow:auto; white-space:pre-wrap; word-break:break-word; border-radius:14px; padding:16px; background:#050e19; border:1px solid #1c3049; color:#cfe3f6; line-height:1.55; }
    .meta { margin-top:18px; padding-top:16px; border-top:1px solid var(--line); color:var(--muted); font-size:13px; line-height:1.7; }
    footer { text-align:center; color:#71869f; margin-top:22px; font-size:12px; }
    @media (max-width:760px) { .grid { grid-template-columns:1fr; } header { align-items:flex-start; flex-direction:column; } .shell { padding-top:24px; } }
  </style>
</head>
<body>
  <main class="shell">
    <header>
      <div><div class="eyebrow">Railway Production Deployment</div><h1>AI Agent Console</h1><div class="subtitle">Gửi câu hỏi, kiểm tra Redis và quan sát metrics từ một nơi.</div></div>
      <div class="badge">v1.0.0 · production</div>
    </header>
    <section class="grid">
      <div class="card">
        <h2>Chat với agent</h2>
        <div class="mode"><div><strong>Chế độ demo công khai</strong><div class="hint">Không cần API key · 5 request/phút</div></div><label><input id="authMode" type="checkbox"> Dùng API key</label></div>
        <div id="apiKeyGroup" class="hidden"><label for="apiKey">API key</label><input id="apiKey" type="password" autocomplete="off" placeholder="Nhập AGENT_API_KEY trên Railway"></div>
        <label for="userId">User ID</label>
        <input id="userId" value="web-user" maxlength="100" pattern="[A-Za-z0-9_-]+">
        <label for="question">Câu hỏi</label>
        <textarea id="question" placeholder="Ví dụ: Cloud deployment là gì?"></textarea>
        <div class="actions"><button id="send">Thử demo</button><button class="secondary hidden" id="metrics">Xem metrics</button></div>
        <pre id="output">Sẵn sàng. Demo công khai không yêu cầu API key.</pre>
      </div>
      <aside class="card">
        <h2>Trạng thái hệ thống</h2>
        <div class="status-row">
          <div class="status"><strong><span id="healthDot" class="dot"></span>API</strong><span id="healthText" class="hint">Đang kiểm tra</span></div>
          <div class="status"><strong><span id="redisDot" class="dot"></span>Redis</strong><span id="redisText" class="hint">Đang kiểm tra</span></div>
        </div>
        <div class="meta">
          <div>Demo: <code>POST /demo</code></div>
          <div>Protected API: <code>POST /ask</code></div>
          <div>Demo limit: 5 request/phút/IP</div>
          <div>Budget: $10/tháng/user</div>
          <div>Storage: Railway Redis</div>
        </div>
      </aside>
    </section>
    <footer>Production AI Agent · FastAPI · Docker · Railway · Redis</footer>
  </main>
  <script>
    const $ = id => document.getElementById(id);
    const output = $('output');
    const apiKey = $('apiKey');
    const authMode = $('authMode');
    apiKey.value = sessionStorage.getItem('agentApiKey') || '';
    apiKey.addEventListener('input', () => sessionStorage.setItem('agentApiKey', apiKey.value));
    authMode.addEventListener('change', () => {
      $('apiKeyGroup').classList.toggle('hidden', !authMode.checked);
      $('metrics').classList.toggle('hidden', !authMode.checked);
      $('send').textContent = authMode.checked ? 'Gửi bằng API key' : 'Thử demo';
      output.textContent = authMode.checked ? 'Chế độ API bảo vệ đã bật.' : 'Chế độ demo công khai đã bật.';
    });

    async function jsonRequest(path, options = {}) {
      const response = await fetch(path, options);
      const data = await response.json().catch(() => ({ detail: 'Response không phải JSON' }));
      if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
      return data;
    }

    async function checkStatus() {
      try { const h = await jsonRequest('/health'); $('healthDot').classList.add('ok'); $('healthText').textContent = h.status; }
      catch { $('healthText').textContent = 'offline'; }
      try { const r = await jsonRequest('/ready'); $('redisDot').classList.add('ok'); $('redisText').textContent = r.redis; }
      catch { $('redisText').textContent = 'unavailable'; }
    }

    $('send').addEventListener('click', async () => {
      const question = $('question').value.trim();
      const userId = $('userId').value.trim();
      if (!question || !userId) { output.textContent = 'Hãy nhập user ID và câu hỏi.'; return; }
      if (authMode.checked && !apiKey.value) { output.textContent = 'Hãy nhập API key.'; return; }
      $('send').disabled = true; output.textContent = 'Agent đang xử lý...';
      try {
        const path = authMode.checked ? '/ask' : '/demo';
        const headers = {'Content-Type':'application/json'};
        if (authMode.checked) headers['X-API-Key'] = apiKey.value;
        const data = await jsonRequest(path, { method:'POST', headers, body:JSON.stringify({question, user_id:userId}) });
        output.textContent = `${data.answer}\n\nHistory: ${data.history_items} · Cost: $${data.monthly_cost_usd} · Instance: ${data.instance_id}`;
      } catch (error) { output.textContent = `Lỗi: ${error.message}`; }
      finally { $('send').disabled = false; }
    });

    $('metrics').addEventListener('click', async () => {
      if (!apiKey.value) { output.textContent = 'Hãy nhập API key trước.'; return; }
      try { output.textContent = JSON.stringify(await jsonRequest('/metrics', {headers:{'X-API-Key':apiKey.value}}), null, 2); }
      catch (error) { output.textContent = `Lỗi: ${error.message}`; }
    });
    checkStatus();
  </script>
</body>
</html>"""


@app.post("/ask", response_model=AskResponse, tags=["Agent"])
async def ask_agent(
    body: AskRequest,
    request: Request,
    _api_key: str = Depends(verify_api_key),
):
    return await run_agent(body, request, "rate")


@app.post("/demo", response_model=AskResponse, tags=["Agent"])
async def demo_agent(body: AskRequest, request: Request):
    forwarded_for = request.headers.get("x-forwarded-for", "")
    client_ip = forwarded_for.split(",", 1)[0].strip()
    if not client_ip:
        client_ip = request.client.host if request.client else "unknown"
    visitor_id = hashlib.sha256(client_ip.encode("utf-8")).hexdigest()[:16]
    demo_body = AskRequest(question=body.question, user_id=f"demo-{visitor_id}")
    return await run_agent(demo_body, request, "demo-rate")


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
