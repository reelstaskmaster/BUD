import pytest

from app.services.agent_loop import AgentLoop
from app.services.openai_client import ChatResult


def test_simple_request_uses_fast_path() -> None:
    decision = AgentLoop().decide("Привет, как дела?")
    assert decision.mode == "fast"
    assert decision.max_iterations == 1


def test_complex_request_gets_agent_contract() -> None:
    loop = AgentLoop()
    decision = loop.decide("Разбери BUD и найди слабые места")
    assert decision.mode == "agent"
    assert decision.max_iterations == 3
    rendered = loop.augment_instructions("base", "Разбери BUD")
    assert "Autonomous execution contract" in rendered
    assert "AGENT_STATUS: DONE" in rendered


def test_fast_path_does_not_change_instructions() -> None:
    loop = AgentLoop()
    assert loop.augment_instructions("base", "Привет") == "base"


@pytest.mark.asyncio
async def test_agent_loop_replans_from_previous_result() -> None:
    loop = AgentLoop()
    calls: list[str] = []

    async def executor(instructions: str) -> ChatResult:
        calls.append(instructions)
        if len(calls) == 1:
            return ChatResult("GitHub action failed with HTTP 403. AGENT_STATUS: CONTINUE")
        return ChatResult("Changed the branch and verified the result. AGENT_STATUS: DONE")

    result = await loop.run(
        query="Исправь проблему в GitHub",
        instructions="base",
        executor=executor,
    )

    assert "verified the result" in result.text
    assert "Previous attempt result" in calls[1]
    assert "HTTP 403" in calls[1]
    assert "AGENT_STATUS" not in result.text


@pytest.mark.asyncio
async def test_agent_loop_stops_on_verified_done() -> None:
    loop = AgentLoop()
    calls = 0

    async def executor(instructions: str) -> ChatResult:
        nonlocal calls
        calls += 1
        return ChatResult("Verified. AGENT_STATUS: DONE")

    result = await loop.run(
        query="Проверь BUD",
        instructions="base",
        executor=executor,
    )

    assert calls == 1
    assert result.text == "Verified."
