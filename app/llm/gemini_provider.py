import json

import httpx

from app.llm.base import LLMResult
from app.llm.prompt import SYSTEM_PROMPT, build_array_user_message
from app.logging_utils import get_logger

logger = get_logger(__name__)

GEMINI_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    async def interpret(self, notes: list[str], battery_capacity_kwh: float, timeout_s: float) -> LLMResult:
        if not self.api_key:
            return LLMResult(ok=False, raw_entries=None, error="gemini api key not configured")

        url = GEMINI_URL_TEMPLATE.format(model=self.model)
        payload = {
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [
                {"role": "user", "parts": [{"text": build_array_user_message(notes, battery_capacity_kwh)}]}
            ],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
            },
        }
        try:
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                resp = await client.post(url, params={"key": self.api_key}, json=payload)
            if resp.status_code != 200:
                return LLMResult(ok=False, raw_entries=None, error=f"gemini http {resp.status_code}")
            data = resp.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            parsed = json.loads(text)
            if not isinstance(parsed, list):
                return LLMResult(ok=False, raw_entries=None, error="gemini response was not a JSON array")
            return LLMResult(ok=True, raw_entries=parsed)
        except Exception as exc:  # noqa: BLE001 - safe failure boundary, never propagate
            logger.warning("gemini interpret failed: %s", type(exc).__name__)
            return LLMResult(ok=False, raw_entries=None, error=str(type(exc).__name__))
