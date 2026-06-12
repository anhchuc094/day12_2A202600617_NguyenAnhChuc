"""
✅ ADVANCED — Centralized Config Management (12-Factor: Config in Env)

Tất cả config đọc từ environment variables.
- Không có giá trị nhạy cảm trong code
- Dễ thay đổi giữa dev/staging/production
- Validation rõ ràng — fail fast nếu thiếu config quan trọng
"""
import os
import logging
from dataclasses import dataclass, field
from dotenv import load_dotenv


load_dotenv()


@dataclass
class Settings:
    # Server
    host: str = field(default_factory=lambda: os.getenv("HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(os.getenv("PORT", "8000")))
    debug: bool = field(default_factory=lambda: os.getenv("DEBUG", "false").lower() == "true")

    # App
    app_name: str = field(default_factory=lambda: os.getenv("APP_NAME", "AI Agent"))
    app_version: str = field(default_factory=lambda: os.getenv("APP_VERSION", "1.0.0"))
    environment: str = field(default_factory=lambda: os.getenv("ENVIRONMENT", "development"))

    # LLM (optional — chỉ warn nếu thiếu, không crash)
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "groq").lower())
    groq_api_key: str = field(default_factory=lambda: os.getenv("GROQ_API_KEY", ""))
    llm_model: str = field(
        default_factory=lambda: os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")
    )
    max_tokens: int = field(default_factory=lambda: int(os.getenv("MAX_TOKENS", "500")))

    # Security
    api_key: str = field(default_factory=lambda: os.getenv("AGENT_API_KEY", ""))
    allowed_origins: list = field(
        default_factory=lambda: os.getenv("ALLOWED_ORIGINS", "*").split(",")
    )

    def validate(self):
        """Fail fast nếu thiếu config bắt buộc."""
        warnings = []
        if self.llm_provider not in {"groq", "mock"}:
            raise ValueError("LLM_PROVIDER must be 'groq' or 'mock'")
        if self.llm_provider == "groq" and not self.groq_api_key:
            warnings.append("GROQ_API_KEY not set - using mock LLM")
        if not self.api_key and self.environment == "production":
            raise ValueError("AGENT_API_KEY must be set in production!")
        for w in warnings:
            logging.warning(w)
        return self


# Singleton — import từ bất kỳ file nào đều dùng chung
settings = Settings().validate()
