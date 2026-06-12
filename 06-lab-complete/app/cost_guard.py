"""Redis-backed monthly per-user budget protection."""
from datetime import datetime, timezone

from fastapi import HTTPException

from app.config import settings
from app.redis_client import redis_client


INPUT_COST_PER_1K = 0.00015
OUTPUT_COST_PER_1K = 0.0006


def estimate_cost(input_tokens: int, output_tokens: int) -> float:
    return (input_tokens / 1000) * INPUT_COST_PER_1K + (
        output_tokens / 1000
    ) * OUTPUT_COST_PER_1K


def record_cost(user_id: str, estimated_cost: float) -> float:
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    key = f"budget:{user_id}:{month}"
    script = """
    local current = tonumber(redis.call('GET', KEYS[1]) or '0')
    local amount = tonumber(ARGV[1])
    local budget = tonumber(ARGV[2])
    if current + amount > budget then
        return -1
    end
    local total = redis.call('INCRBYFLOAT', KEYS[1], amount)
    redis.call('EXPIRE', KEYS[1], 2764800)
    return total
    """
    result = redis_client.eval(
        script,
        1,
        key,
        estimated_cost,
        settings.monthly_budget_usd,
    )
    if float(result) < 0:
        raise HTTPException(status_code=402, detail="Monthly budget exhausted")
    return float(result)


def get_monthly_cost(user_id: str) -> float:
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    return float(redis_client.get(f"budget:{user_id}:{month}") or 0.0)
