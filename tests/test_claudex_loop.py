import pytest

from app.services.claudex_loop import ClaudexLoop
from app.services.openai_client import AIProviderError


class FakeAI:
    def __init__(self, responses: list[str]) -> None:
        self.responses = iter(responses)

    async def independent_text(self, **_: object) -> str:
        return next(self.responses)


@pytest.mark.asyncio
async def test_plan_review_approves_valid_json() -> None:
    ai = FakeAI([
        '{"verdict":"APPROVED","summary":"Plan is coherent.","findings":[]}'
    ])
    review = await ClaudexLoop(ai, max_rounds=2).review_plan(
        query="fix bug",
        plan="1. inspect\n2. fix\n3. verify",
    )
    assert review.verdict == "APPROVED"
    assert review.findings == ()


@pytest.mark.asyncio
async def test_plan_review_revisits_once_then_approves() -> None:
    ai = FakeAI([
        '{"verdict":"REVISE","summary":"Needs explicit rollback.","findings":["Add rollback criteria."]}',
        '{"verdict":"APPROVED","summary":"Rollback criteria added.","findings":[]}',
    ])
    review = await ClaudexLoop(ai, max_rounds=2).review_plan(
        query="migration",
        plan="1. migrate",
    )
    assert review.verdict == "APPROVED"


@pytest.mark.asyncio
async def test_plan_review_blocks_malformed_or_invalid_reviewer_output() -> None:
    ai = FakeAI(["not json"])
    with pytest.raises(AIProviderError):
        await ClaudexLoop(ai).review_plan(query="x", plan="y")


@pytest.mark.asyncio
async def test_final_inspection_is_independent() -> None:
    ai = FakeAI([
        '{"verdict":"REVISE","summary":"Evidence is incomplete.","findings":["No proof command."]}'
    ])
    review = await ClaudexLoop(ai).inspect_result(
        query="implement feature",
        plan="verify with tests",
        result="Implemented.",
    )
    assert review.verdict == "REVISE"
    assert "No proof" in review.findings[0]


from app.services.agent_loop import AgentLoop
from app.services.openai_client import ChatResult
from app.services.claudex_loop import ClaudexReview


class FakeClaudex:
    def __init__(self, verdict: str = "APPROVED") -> None:
        self.verdict = verdict
        self.plan_calls = 0
        self.inspect_calls = 0

    async def review_plan(self, **_: object) -> ClaudexReview:
        self.plan_calls += 1
        return ClaudexReview(self.verdict, "plan review", ())

    async def inspect_result(self, **_: object) -> ClaudexReview:
        self.inspect_calls += 1
        return ClaudexReview("APPROVED", "final review", ())


@pytest.mark.asyncio
async def test_agent_loop_uses_claudex_before_execution_and_after_finalize() -> None:
    claudex = FakeClaudex()
    loop = AgentLoop(claudex)
    calls = 0

    async def executor(_: str) -> ChatResult:
        nonlocal calls
        calls += 1
        return ChatResult("AGENT_STATUS: DONE")

    result = await loop.run(
        query="Проверь и исправь BUD",
        instructions="base",
        executor=executor,
    )
    assert "Claudex independent final inspection: APPROVED." in result.text
    assert claudex.plan_calls == 1
    assert claudex.inspect_calls == 1
    assert calls == 1


@pytest.mark.asyncio
async def test_agent_loop_does_not_execute_when_claudex_blocks_plan() -> None:
    claudex = FakeClaudex("BLOCKED")
    loop = AgentLoop(claudex)
    calls = 0

    async def executor(_: str) -> ChatResult:
        nonlocal calls
        calls += 1
        return ChatResult("should not run")

    result = await loop.run(
        query="Проверь BUD",
        instructions="base",
        executor=executor,
    )
    assert "Claudex plan review: BLOCKED" in result.text
    assert calls == 0
