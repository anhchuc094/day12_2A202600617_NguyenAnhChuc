"""12-factor application configuration."""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env.local", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = "0.0.0.0"
    port: int = 8000
    environment: str = "development"
    debug: bool = Field(default=False, validation_alias="APP_DEBUG")
    log_level: str = "INFO"

    app_name: str = "Production AI Agent"
    app_version: str = "1.0.0"
    llm_model: str = "mock"

    agent_api_key: str = "dev-key-change-me"
    allowed_origins: str = "*"

    rate_limit_per_minute: int = 10
    demo_rate_limit_per_minute: int = 5
    monthly_budget_usd: float = 10.0
    redis_url: str = "redis://localhost:6379/0"
    history_limit: int = 20

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",")]

    def validate_production(self) -> None:
        if self.environment == "production" and self.agent_api_key == "dev-key-change-me":
            raise ValueError("AGENT_API_KEY must be changed in production")


@lru_cache
def get_settings() -> Settings:
    configured = Settings()
    configured.validate_production()
    return configured


settings = get_settings()
