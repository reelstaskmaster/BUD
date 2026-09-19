import pytest

from app.config import Settings
from app.services.memory import MemoryService


class FakeOpenAI:
    async def embed(self, _text: str) -> list[float]:
        return [0.0]


@pytest.fixture
def service() -> MemoryService:
    settings = Settings(telegram_bot_token="token", openai_api_key="key")
    return MemoryService(None, FakeOpenAI(), settings)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_unknown_tool_is_reported(service: MemoryService) -> None:
    result = await service.tool_handler(None, 1, "unknown", {})  # type: ignore[arg-type]
    assert result == "Unknown tool: unknown"


@pytest.mark.asyncio
async def test_empty_remember_is_rejected_without_embedding(service: MemoryService) -> None:
    result = await service.remember_fact(None, 1, "   ", "person")  # type: ignore[arg-type]
    assert result == "Nothing to remember."
