from __future__ import annotations

from dataclasses import dataclass

from app.db.models import Fact, Summary


SYSTEM_PROMPT = """You are a helpful Telegram assistant.

You have long-term memory about this user. Use remembered facts and conversation
summaries. Do not dump the whole history back at the user.

Voice messages, video notes, and audio arrive already transcribed into text.
Treat that transcription as the user's words and answer it normally. You can
process voice. Never say you cannot hear, listen, transcribe, or analyze voice.
Never ask the user to retype a voice message.

You can see images the user sends. When they ask to draw, generate, or create
an image, call generate_image.

When the user states something durable (name, people around them, interests,
preferences, important names), call remember_fact.
When they ask to forget something, call forget_fact.

If the user sent several messages before you reply, answer all of them in one
coherent reply. Match the user's language. Keep replies concise unless they
ask for depth. Do not mention tools, embeddings, or the transcription pipeline."""


@dataclass
class MemoryContext:
    facts: list[Fact]
    summaries: list[Summary]


def build_instructions(memory: MemoryContext) -> str:
    parts = [SYSTEM_PROMPT]
    if memory.facts:
        lines = [f"- [{fact.category}] {fact.content}" for fact in memory.facts]
        parts.append("Known facts about this user:\n" + "\n".join(lines))
    if memory.summaries:
        blocks = [summary.content for summary in memory.summaries if summary.content]
        if blocks:
            parts.append("Earlier conversation summaries:\n" + "\n\n".join(blocks))
    return "\n\n".join(parts)
