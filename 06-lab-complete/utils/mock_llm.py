"""Small mock LLM used to keep the deployment lab API-key free."""
import random
import time


MOCK_RESPONSES = {
    "default": [
        "Day la cau tra loi tu AI agent (mock).",
        "Agent dang hoat dong tot. Day la mock response.",
    ],
    "docker": ["Container dong goi ung dung va dependencies de chay nhat quan."],
    "deploy": ["Deployment dua ung dung len server de nguoi dung co the truy cap."],
    "health": ["Agent dang hoat dong binh thuong."],
}


def ask(question: str, delay: float = 0.1) -> str:
    time.sleep(delay + random.uniform(0, 0.05))
    normalized = question.lower()
    for keyword, responses in MOCK_RESPONSES.items():
        if keyword != "default" and keyword in normalized:
            return random.choice(responses)
    return random.choice(MOCK_RESPONSES["default"])
