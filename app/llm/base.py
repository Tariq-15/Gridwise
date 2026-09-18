from dataclasses import dataclass
from typing import Protocol


@dataclass
class LLMResult:
    ok: bool
    raw_entries: list | None  # parsed JSON array, or None on failure
    error: str | None = None


class LLMProvider(Protocol):
    name: str

    async def interpret(self, notes: list[str], battery_capacity_kwh: float, timeout_s: float) -> LLMResult:
        ...
