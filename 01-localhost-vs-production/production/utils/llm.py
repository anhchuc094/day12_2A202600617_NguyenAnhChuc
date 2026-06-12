from groq import AsyncGroq

from config import settings
from utils.mock_llm import ask as ask_mock


_groq_client = (
    AsyncGroq(api_key=settings.groq_api_key)
    if settings.llm_provider == "groq" and settings.groq_api_key
    else None
)


async def ask(question: str) -> str:
    if _groq_client is None:
        return ask_mock(question)

    completion = await _groq_client.chat.completions.create(
        model=settings.llm_model,
        messages=[{"role": "user", "content": question}],
        max_tokens=settings.max_tokens,
    )
    return completion.choices[0].message.content or ""


def active_provider() -> str:
    return "groq" if _groq_client is not None else "mock"
