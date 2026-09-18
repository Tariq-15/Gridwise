import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    llm_provider: str = os.getenv("LLM_PROVIDER", "groq").lower()

    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    groq_model: str = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
    # Distinct model on the same Groq key: separate per-model rate-limit bucket,
    # so a 429 on the primary model doesn't take down interpretation entirely.
    groq_fallback_model: str = os.getenv("GROQ_FALLBACK_MODEL", "allam-2-7b")

    port: int = int(os.getenv("PORT", "8000"))

    primary_llm_timeout_s: float = 8.0
    fallback_llm_timeout_s: float = 5.0
    second_fallback_llm_timeout_s: float = 4.0

    @property
    def secret_values(self) -> list[str]:
        return [v for v in (self.gemini_api_key, self.groq_api_key) if v]


settings = Settings()
