from __future__ import annotations

from dataclasses import dataclass

from app.db.models import Fact, Summary, UserProfile


SYSTEM_PROMPT = """You are BUD, a helpful personalized Telegram AI assistant.

Adapt to the user's profile and remembered facts. Do not dump the whole history
back to the user. Match the user's language and preferred response style.

Voice messages, video notes, and audio arrive already transcribed into text.
Treat that transcription as the user's words and answer it normally. Never say
you cannot hear, listen, transcribe, or analyze voice. Never ask the user to
retype a voice message.

You can see images the user sends. When they ask to draw, generate, or create
an image, call generate_image.

When the user states something durable (name, people around them, interests,
preferences, important names), call remember_fact. When they ask to forget
something, call forget_fact.

If the user sent several messages before you reply, answer all of them in one
coherent reply. Keep replies concise unless the user asks for depth. Do not
mention tools, embeddings, subscription state, or the memory pipeline."""


@dataclass
class MemoryContext:
    facts: list[Fact]
    summaries: list[Summary]
    profile: UserProfile | None = None


def build_instructions(memory: MemoryContext) -> str:
    parts = [SYSTEM_PROMPT]
    if memory.profile:
        preferences = memory.profile.preferences or {}
        if preferences:
            parts.append("User profile preferences:\n" + _format_preferences(preferences))
        if memory.profile.about:
            parts.append("What the user chose to tell BUD about themselves:\n" + memory.profile.about)
    if memory.facts:
        lines = [f"- [{fact.category}] {fact.content}" for fact in memory.facts]
        parts.append("Known facts about this user:\n" + "\n".join(lines))
    if memory.summaries:
        blocks = [summary.content for summary in memory.summaries if summary.content]
        if blocks:
            parts.append("Earlier conversation summaries:\n" + "\n\n".join(blocks))
    return "\n\n".join(parts)


def _format_preferences(preferences: dict) -> str:
    labels = {
        "communication": "Communication style",
        "answer_style": "Answer preferences",
        "interests": "Interests",
        "help_with": "Ways BUD should help",
        "correction_style": "Correction style",
        "remember": "What matters to remember",
    }
    lines: list[str] = []
    for key, value in preferences.items():
        if value:
            label = labels.get(key, key)
            if isinstance(value, list):
                value = ", ".join(str(item) for item in value)
            lines.append(f"- {label}: {value}")
    return "\n".join(lines)
