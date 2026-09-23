from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PromptPlan:
    """Deterministic task contract used to compile the runtime system prompt."""

    target: str
    intent: str
    success_criteria: tuple[str, ...]


class PromptEngine:
    """Compile a compact, task-aware instruction block without an extra LLM call.

    This is intentionally deterministic: prompt compilation must not consume a
    second model request or become another failure point in the reply pipeline.
    The inferred target is a hint for the model, not a command that overrides
    the user's actual request.
    """

    _TARGETS: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("codex", ("codex",)),
        ("cursor", ("cursor",)),
        ("claude code", ("claude code",)),
        ("github", ("github", "pull request", "pull-request", "repository", "repo")),
        ("image generation", ("image", "photo", "picture", "draw", "generate an image", "создай изображение", "нарисуй")),
        ("prompt engineering", ("prompt", "промпт", "system prompt", "системный промпт")),
        ("telegram", ("telegram", "телеграм", "telegram bot", "бот")),
        ("code", ("code", "coding", "код", "программ", "bug", "баг", "ошибк")),
    )

    _INTENTS: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("troubleshoot", ("fix", "debug", "troubleshoot", "repair", "исправ", "почин", "ошибк", "баг")),
        ("create", ("create", "build", "make", "generate", "write", "создай", "сделай", "напиши", "сгенерируй")),
        ("modify", ("change", "modify", "update", "refactor", "измен", "обнов", "передел", "рефактор")),
        ("plan", ("plan", "roadmap", "steps", "план", "шаг", "архитектур")),
        ("explain", ("explain", "what is", "how", "объясни", "что такое", "как работает", "почему")),
        ("compare", ("compare", "versus", "vs", "сравни", "разница", "отлич")),
    )

    def compile(self, query: str) -> PromptPlan:
        normalized = query.casefold().strip()
        target = self._detect(normalized)
        intent = self._detect_intent(normalized)
        return PromptPlan(
            target=target,
            intent=intent,
            success_criteria=self._success_criteria(target, intent),
        )

    def render(self, query: str) -> str:
        plan = self.compile(query)
        criteria = "\n".join(f"- {item}" for item in plan.success_criteria)
        return (
            "Task contract (inferred from the current user request):\n"
            f"- Target: {plan.target}\n"
            f"- Intent: {plan.intent}\n"
            "Treat the target and intent as hints; follow the user's explicit request "
            "if it conflicts with an inference.\n"
            "Success criteria:\n"
            f"{criteria}"
        )

    def _detect(self, query: str) -> str:
        for target, keywords in self._TARGETS:
            if any(keyword in query for keyword in keywords):
                return target
        return "general assistant"

    def _detect_intent(self, query: str) -> str:
        for intent, keywords in self._INTENTS:
            if any(keyword in query for keyword in keywords):
                return intent
        return "answer"

    @staticmethod
    def _success_criteria(target: str, intent: str) -> tuple[str, ...]:
        criteria = [
            "Answer the actual request, not an inferred adjacent task.",
            "Use relevant memory and recent conversation context without dumping it.",
            "Do not invent missing facts, actions, tool results, or completed work.",
        ]
        if intent in {"create", "modify", "troubleshoot"}:
            criteria.append("Prefer concrete, executable output and state important assumptions.")
        if target == "code":
            criteria.append("Preserve the existing project architecture unless the request requires a change.")
        if target in {"codex", "cursor", "claude code"}:
            criteria.append("Make scope, constraints, acceptance criteria, and stop conditions explicit.")
        if target == "image generation":
            criteria.append("If an image is requested, use the image-generation tool instead of returning only a textual prompt.")
        return tuple(criteria)
