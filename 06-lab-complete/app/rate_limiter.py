"""Redis-backed sliding-window rate limiting."""
import time
import uuid
from fastapi import HTTPException

from app.config import settings
from app.redis_client import redis_client


def check_rate_limit(
    user_id: str,
    limit: int | None = None,
    namespace: str = "rate",
) -> None:
    request_limit = limit or settings.rate_limit_per_minute
    key = f"{namespace}:{user_id}"
    now_ms = int(time.time() * 1000)
    window_start = now_ms - 60_000
    script = """
    redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, ARGV[1])
    local count = redis.call('ZCARD', KEYS[1])
    if count >= tonumber(ARGV[4]) then
        return 0
    end
    redis.call('ZADD', KEYS[1], ARGV[2], ARGV[3])
    redis.call('EXPIRE', KEYS[1], 60)
    return 1
    """
    allowed = redis_client.eval(
        script,
        1,
        key,
        window_start,
        now_ms,
        f"{now_ms}:{uuid.uuid4().hex}",
        request_limit,
    )

    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: {request_limit} requests/minute",
            headers={"Retry-After": "60"},
        )
