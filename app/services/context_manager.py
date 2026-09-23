from __future__ import annotations

from app.services.openai_client import OpenAIInputMessage


class ContextManager:
    """Keep model context bounded without changing the conversation source of truth."""

    def __init__(self, max_chars: int = 24_000) -> None:
        if max_chars < 2_000:
            raise ValueError("max_chars must be at least 2000")
        self.max_chars = max_chars

    def trim_messages(
        self, messages: list[OpenAIInputMessage]
    ) -> list[OpenAIInputMessage]:
        if not messages:
            return []

        selected: list[OpenAIInputMessage] = []
        used = 0

        for message in reversed(messages):
            text_cost = len(message.text or "")
            image_cost = 4_000 if message.image_bytes else 0
            cost = text_cost + image_cost
            if selected and used + cost > self.max_chars:
                break
            selected.append(message)
            used += cost

        return list(reversed(selected))

    def trim_instructions(self, instructions: str) -> str:
        if len(instructions) <= self.max_chars:
            return instructions
        return instructions[: self.max_chars].rstrip() + "\n[Context trimmed]"
