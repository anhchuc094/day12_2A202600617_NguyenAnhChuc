"""Shared Redis connection and conversation-history helpers."""
import json

from redis import Redis

from app.config import settings


redis_client = Redis.from_url(settings.redis_url, decode_responses=True)


def ping_redis() -> bool:
    return bool(redis_client.ping())


def get_history(user_id: str) -> list[dict[str, str]]:
    values = redis_client.lrange(f"history:{user_id}", 0, settings.history_limit - 1)
    return [json.loads(value) for value in reversed(values)]


def append_history(user_id: str, question: str, answer: str) -> None:
    key = f"history:{user_id}"
    redis_client.lpush(key, json.dumps({"question": question, "answer": answer}))
    redis_client.ltrim(key, 0, settings.history_limit - 1)
    redis_client.expire(key, 30 * 24 * 60 * 60)
