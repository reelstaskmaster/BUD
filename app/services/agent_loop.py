from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

from app.services.openai_client import ChatResult


@dataclass(frozen=True)
class AgentDecision:
    mode: str
    max_iterations: int


class AgentLoop:
    """Small autonomous orchestration layer.

    Simple requests keep the existing one-call fast path. Complex requests get
    an explicit goal/definition-of-done contract; no extra LLM planner call is
    made. Future capabilities can plug into the executor without changing the
    fast path.
    """

    _COMPLEX_MARKERS = (
        "analyze", "analyse", "investigate", "debug", "fix", "implement",
        "refactor", "deploy", "check", "review", "разбер", "проанализ",
        "исслед", "почин", "исправ", "реализ", "рефактор", "проверь",
        "провести аудит", "сделай полностью",
    )

    def decide(self, query: str) -> AgentDecision:
        normalized = query.casefold()
        complex_task = any(marker in normalized for marker in self._COMPLEX_MARKERS)
        return AgentDecision("agent" if complex_task else "fast", 3 if complex_task else 1)

    def augment_instructions(self, instructions: str, query: str) -> str:
        decision = self.decide(query)
        if decision.mode == "fast":
            return instructions
        return (
            f"{instructions}\n\n"
            "Autonomous task contract:\n"
            "- Work toward the user's actual goal, not an adjacent task.\n"
            "- Decide the next useful action from the available capabilities.\n"
            "- Verify important results before claiming completion.\n"
            "- If an action fails, reassess and use a safe alternative when available.\n"
            "- Stop when the requested outcome and acceptance criteria are satisfied.\n"
            "- Do not claim actions or results that were not actually performed."
        )

    async def run(
        self,
        *,
        query: str,
        instructions: str,
        executor: Callable[[str], Awaitable[ChatResult]],
    ) -> ChatResult:
        decision = self.decide(query)
        runtime_instructions = self.augment_instructions(instructions, query)
        result = await executor(runtime_instructions)
        if decision.mode == "fast":
            return result
        if result.text.strip():
            return result
        return ChatResult("Не удалось подтвердить завершение задачи. Попробуйте ещё раз.")
