"""API-key authentication dependency."""
import secrets

from fastapi import Header, HTTPException

from app.config import settings


def verify_api_key(x_api_key: str | None = Header(default=None)) -> str:
    if not x_api_key or not secrets.compare_digest(x_api_key, settings.agent_api_key):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key. Include X-API-Key header.",
        )
    return x_api_key
