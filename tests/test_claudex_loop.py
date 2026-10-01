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
