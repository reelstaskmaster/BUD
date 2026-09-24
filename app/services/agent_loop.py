from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Awaitable, Callable

from app.services.openai_client import ChatResult
from app.services.planner import Planner


_AGENT_STATUS_RE = re.compile(r"\bAGENT_STATUS\s*:\s*(DONE|CONTINUE|BLOCKED)\b", re.IGNORECASE)


@dataclass(frozen=True)
class AgentDecision:
    mode: str
    max_iterations: int


class AgentLoop:
    """Bounded execution runtime for complex tasks.

    Simple requests keep the existing one-call fast path. Complex requests run
    a bounded observe -> execute -> verify/re-plan cycle. State is carried
    between iterations through the previous result, while tool execution stays
    inside the existing OpenAI tool loop.
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
            "Autonomous execution contract:\n"
            "- Inspect the relevant context before changing anything.\n"
            "- Choose and execute the smallest useful action with available capabilities.\n"
            "- Verify important results against observable evidence before claiming success.\n"
            "- If an action fails, use the actual error to re-plan; do not repeat the same failed action blindly.\n"
            "- Continue until the requested outcome is verified or an external blocker is confirmed.\n"
            "- When the task is verified, end your response with AGENT_STATUS: DONE.\n"
            "- When progress is possible but verification is incomplete, end with AGENT_STATUS: CONTINUE.\n"
            "- When an external dependency genuinely blocks completion, end with AGENT_STATUS: BLOCKED.\n"
            "- Never claim actions, tool results, commits, deployments, or verification that did not happen."
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
        if decision.mode == "fast":
            return await executor(runtime_instructions)

        previous = ""
        last_result: ChatResult | None = None
        for iteration in range(1, decision.max_iterations + 1):
            iteration_instructions = runtime_instructions
            if iteration > 1:
                iteration_instructions += (
                    f"\n\nAgent iteration {iteration}/{decision.max_iterations}. "
                    "Continue from the previous attempt. Do not repeat a failed action blindly. "
                    "Use the observed result below to choose the next action.\n"
                    f"Previous attempt result:\n{previous[:12000]}"
                )

            result = await executor(iteration_instructions)
            last_result = result
            status = _agent_status(result.text)
            cleaned = _strip_agent_status(result.text)
            previous = cleaned or result.text

            if status == "DONE":
                return ChatResult(cleaned, result.image_bytes, result.image_mime_type, result.image_prompt)
            if status == "BLOCKED":
                return ChatResult(cleaned, result.image_bytes, result.image_mime_type, result.image_prompt)

        if last_result is None:
            return ChatResult("Не удалось запустить выполнение задачи.")

        cleaned = _strip_agent_status(last_result.text)
        return ChatResult(
            cleaned or "Не удалось подтвердить завершение задачи.",
            last_result.image_bytes,
            last_result.image_mime_type,
            last_result.image_prompt,
        )


def _agent_status(text: str) -> str | None:
    match = _AGENT_STATUS_RE.search(text or "")
    return match.group(1).upper() if match else None


def _strip_agent_status(text: str) -> str:
    return _AGENT_STATUS_RE.sub("", text or "").strip()
