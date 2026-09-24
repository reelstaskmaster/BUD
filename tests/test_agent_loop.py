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
    assert "Autonomous task contract" in rendered


def test_fast_path_does_not_change_instructions() -> None:
    loop = AgentLoop()
    assert loop.augment_instructions("base", "Привет") == "base"


async def test_complex_request_runs_execute_verify_finalize_phases() -> None:
    loop = AgentLoop()
    calls: list[str] = []

    async def executor(instructions: str) -> ChatResult:
        calls.append(instructions)
        return ChatResult(f"phase {len(calls)}")

    result = await loop.run(
        query="Проверь BUD и исправь проблему",
        instructions="base",
        executor=executor,
    )

    assert result.text == "phase 3"
    assert len(calls) == 3
    assert "AGENT PHASE 1 — EXECUTE" in calls[0]
    assert "AGENT PHASE 2 — VERIFY" in calls[1]
    assert "AGENT PHASE 3 — FINALIZE" in calls[2]
    assert "phase 1" in calls[1]
    assert "phase 2" in calls[2]


async def test_complex_empty_results_still_end_bounded() -> None:
    loop = AgentLoop()
    calls = 0

    async def executor(_: str) -> ChatResult:
        nonlocal calls
        calls += 1
        return ChatResult("")

    result = await loop.run(
        query="Проверь BUD",
        instructions="base",
        executor=executor,
    )

    assert calls == 3
    assert "Не удалось подтвердить" in result.text
