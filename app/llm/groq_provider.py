import json

import httpx

from app.llm.base import LLMResult
from app.llm.prompt import SYSTEM_PROMPT, build_object_wrapped_user_message
from app.logging_utils import get_logger

logger = get_logger(__name__)

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# Only reasoning-capable models accept reasoning_effort; sending it to a
# plain instruct model is a hard 400, not a graceful no-op.
_REASONING_MODEL_PREFIXES = ("openai/gpt-oss", "qwen/")


class GroqProvider:
    name = "groq"

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    async def interpret(self, notes: list[str], battery_capacity_kwh: float, timeout_s: float) -> LLMResult:
        if not self.api_key:
            return LLMResult(ok=False, raw_entries=None, error="groq api key not configured")

        payload = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_object_wrapped_user_message(notes, battery_capacity_kwh)},
            ],
        }
        if self.model.startswith(_REASONING_MODEL_PREFIXES):
            payload["reasoning_effort"] = "low"  # cuts token usage sharply, preserves free-tier TPM budget
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                resp = await client.post(GROQ_URL, headers=headers, json=payload)
            if resp.status_code != 200:
                return LLMResult(ok=False, raw_entries=None, error=f"groq http {resp.status_code}")
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            entries = parsed.get("directive_interpretation") if isinstance(parsed, dict) else None
            if not isinstance(entries, list):
                return LLMResult(ok=False, raw_entries=None, error="groq response missing directive_interpretation array")
            return LLMResult(ok=True, raw_entries=entries)
        except Exception as exc:  # noqa: BLE001 - safe failure boundary, never propagate
            logger.warning("groq interpret failed: %s", type(exc).__name__)
            return LLMResult(ok=False, raw_entries=None, error=str(type(exc).__name__))
