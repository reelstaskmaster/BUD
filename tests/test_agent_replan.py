import pytest

from app.services.agent_loop import AgentLoop
from app.services.openai_client import ChatResult


@pytest.mark.asyncio
async def test_complex_task_retries_when_first_execution_has_no_result() -> None:
    calls = 0

    async def execute(_: str) -> ChatResult:
        nonlocal calls
        calls += 1
        return ChatResult("") if calls == 1 else ChatResult("verified")

    result = await AgentLoop().run(
        query="fix the issue",
        instructions="instructions",
        executor=execute,
    )
    assert result.text == "verified"
    assert calls == 3
