import asyncio

from app.config import settings
from app.llm.base import LLMResult
from app.llm.gemini_provider import GeminiProvider
from app.llm.groq_provider import GroqProvider
from app.logging_utils import get_logger

logger = get_logger(__name__)


def _build_providers() -> list:
    gemini = GeminiProvider(settings.gemini_api_key, settings.gemini_model)
    groq_primary = GroqProvider(settings.groq_api_key, settings.groq_model)
    # A distinct model on the same Groq key has its own rate-limit bucket, so
    # a 429 on the primary model doesn't have to fall all the way to no_op.
    groq_secondary = GroqProvider(settings.groq_api_key, settings.groq_fallback_model)
    if settings.llm_provider == "groq":
        ordered = [groq_primary, groq_secondary, gemini]
    else:
        ordered = [gemini, groq_primary, groq_secondary]
    # Only keep providers that actually have a key configured.
    return [p for p in ordered if getattr(p, "api_key", "")]


async def interpret_notes(notes: list[str], battery_capacity_kwh: float) -> LLMResult:
    """Try the primary provider, then up to two fallback providers, each
    under its own timeout budget. Never raises — a total failure yields
    ok=False so the orchestrator can degrade every note to no_op (SAFE
    FAILURE)."""
    providers = _build_providers()
    if not providers:
        return LLMResult(ok=False, raw_entries=None, error="no LLM provider configured")

    timeouts = [
        settings.primary_llm_timeout_s,
        settings.fallback_llm_timeout_s,
        settings.second_fallback_llm_timeout_s,
    ]
    last_error = "unknown"
    for provider, timeout_s in zip(providers, timeouts):
        try:
            result = await asyncio.wait_for(
                provider.interpret(notes, battery_capacity_kwh, timeout_s),
                timeout=timeout_s + 1.0,
            )
        except asyncio.TimeoutError:
            logger.warning("%s interpret timed out", provider.name)
            last_error = f"{provider.name} timed out"
            continue
        except Exception as exc:  # noqa: BLE001 - safe failure boundary
            logger.warning("%s interpret raised: %s", provider.name, type(exc).__name__)
            last_error = f"{provider.name} raised {type(exc).__name__}"
            continue

        if result.ok:
            return result
        last_error = result.error or f"{provider.name} failed"
        logger.warning("%s interpret failed: %s", provider.name, last_error)

    return LLMResult(ok=False, raw_entries=None, error=last_error)
