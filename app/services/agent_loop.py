from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

from app.services.openai_client import ChatResult
from app.services.planner import Planner


@dataclass(frozen=True)
class AgentDecision:
    mode: str
    max_iterations: int


class AgentLoop:
    """Bounded autonomous orchestration.

    Fast requests keep the one-call path. Complex tasks run through three
    explicit phases: execute, verify, and finalize. Each phase is another
    model/tool turn, so external state can be inspected again after actions.
    The loop is bounded to prevent runaway tool use and cost.
    """

    _COMPLEX_MARKERS = (
        "analyze", "analyse", "investigate", "debug", "fix", "implement",
        "refactor", "deploy", "check", "review", "разбер", "проанализ",
        "исслед", "почин", "исправ", "реализ", "рефактор", "проверь",
        "провести аудит", "сделай полностью",
    )

    def __init__(self) -> None:
        self.planner = Planner()

    def decide(self, query: str) -> AgentDecision:
        normalized = query.casefold()
        complex_task = any(marker in normalized for marker in self._COMPLEX_MARKERS)
        return AgentDecision("agent" if complex_task else "fast", 3 if complex_task else 1)

    def augment_instructions(self, instructions: str, query: str) -> str:
        decision = self.decide(query)
        if decision.mode == "fast":
            return instructions
        plan = self.planner.build(query)
        return (
            f"{instructions}\n\n"
            f"{self.planner.render(plan)}\n\n"
            "Autonomous task contract:\n"
            "- Work toward the user's actual goal, not an adjacent task.\n"
            "- Decide the next useful action from the available capabilities.\n"
            "- Verify important results before claiming completion.\n"
            "- If an action fails, reassess and use a safe alternative when available.\n"
            "- Stop when the requested outcome and acceptance criteria are satisfied.\n"
            "- Do not claim actions or results that were not actually performed."
        )

    def _phase_instructions(
        self,
        base: str,
        phase: int,
        previous: str,
    ) -> str:
        phase_text = {
            1: (
                "AGENT PHASE 1 — EXECUTE. Inspect the relevant state and capabilities, "
                "then perform the smallest useful action toward the goal. Use tools when "
                "they provide real evidence or are required to act. Do not stop at a plan."
            ),
            2: (
                "AGENT PHASE 2 — VERIFY. Independently verify the real external state "
                "against the goal and acceptance criteria. Prefer read-only evidence. "
                "If phase 1 failed or the result is incomplete, re-plan and take one "
                "safe corrective action. Never repeat a completed write or create a "
                "duplicate PR/branch just to appear active."
            ),
            3: (
                "AGENT PHASE 3 — FINALIZE. Perform a final evidence check. If the goal "
                "is not yet satisfied, take the minimum safe corrective action and "
                "verify it. If it is satisfied, stop acting and report only what was "
                "actually observed or executed. Do not invent success."
            ),
        }[phase]
        prior = previous[-6000:] if previous else "No previous phase output."
        return (
            f"{base}\n\n{phase_text}\n"
            "Previous phase output (may be incomplete; do not treat it as proof):\n"
            f"{prior}"
        )

    async def run(
        self,
        *,
        query: str,
        instructions: str,
        executor: Callable[[str], Awaitable[ChatResult]],
    ) -> ChatResult:
        decision = self.decide(query)
        if decision.mode == "fast":
            return await executor(instructions)

        base = self.augment_instructions(instructions, query)
        last_result: ChatResult | None = None
        previous = ""

        for phase in range(1, decision.max_iterations + 1):
            result = await executor(self._phase_instructions(base, phase, previous))
            last_result = result
            previous = result.text

        if last_result is not None and last_result.text.strip():
            return last_result
        return ChatResult(
            "Не удалось подтвердить завершение задачи после ограниченного цикла агента."
        )
