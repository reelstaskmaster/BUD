from __future__ import annotations

import base64
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from io import BytesIO
from typing import Any

import httpx
from openai import AsyncOpenAI

from app.config import Settings

logger = logging.getLogger(__name__)

ToolHandler = Callable[[str, dict[str, Any]], Awaitable[str]]
ImageGenerationHandler = Callable[[str], Awaitable[bytes | None]]

CHAT_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "remember_fact",
        "description": (
            "Store a durable fact about the user or this conversation: "
            "people, names, interests, preferences, places, agreements."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "The fact to remember, as a short sentence."},
                "category": {
                    "type": "string",
                    "enum": ["person", "interest", "preference", "name", "other"],
                },
            },
            "required": ["content", "category"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "forget_fact",
        "description": "Forget previously stored facts matching the query. Use when the user asks to forget something.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "What to forget, in natural language."}},
            "required": ["query"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "generate_image",
        "description": "Generate an image from a text prompt and send it to the user. Call this when the user asks to draw, generate, or create a picture.",
        "parameters": {
            "type": "object",
            "properties": {"prompt": {"type": "string", "description": "Detailed image generation prompt."}},
            "required": ["prompt"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]


@dataclass
class ChatResult:
    text: str
    image_bytes: bytes | None = None
    image_prompt: str | None = None


@dataclass
class OpenAIInputMessage:
    role: str
    text: str
    image_bytes: bytes | None = None


class OpenAIService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)

    async def transcribe(self, audio: bytes, filename: str = "voice.ogg") -> str:
        if not audio:
            raise ValueError("Empty audio payload")
        buf = BytesIO(audio)
        buf.name = filename
        content_type = _audio_content_type(filename)
        response = await self.client.audio.transcriptions.create(
            model=self.settings.stt_model,
            file=(filename, buf, content_type),
        )
        return (response.text or "").strip()

    async def embed(self, text: str) -> list[float]:
        cleaned = text.strip() or "empty"
        response = await self.client.embeddings.create(
            model=self.settings.embedding_model,
            input=cleaned,
        )
        return list(response.data[0].embedding)

    async def generate_image(self, prompt: str) -> bytes:
        response = await self.client.images.generate(
            model=self.settings.image_model,
            prompt=prompt,
            size="1024x1024",
            n=1,
        )
        item = response.data[0]
        b64 = getattr(item, "b64_json", None)
        if b64:
            return base64.b64decode(b64)
        url = getattr(item, "url", None)
        if url:
            async with httpx.AsyncClient(timeout=60) as http:
                downloaded = await http.get(url)
                downloaded.raise_for_status()
                return downloaded.content
        raise RuntimeError("Image generation returned neither b64 nor url")

    async def summarize(self, transcript: str) -> str:
        response = await self.client.responses.create(
            model=self.settings.extract_model,
            instructions=(
                "Summarize this chat excerpt in 5-8 concise sentences. "
                "Keep names, decisions, open questions, and durable context. "
                "Write in the same language as the excerpt."
            ),
            input=transcript[:20000],
        )
        return (response.output_text or "").strip()

    async def extract_facts(self, turn_text: str) -> list[dict[str, str]]:
        response = await self.client.responses.create(
            model=self.settings.extract_model,
            instructions=(
                "Extract durable facts worth remembering from this conversation turn: "
                "people, names, interests, preferences, places, agreements. "
                "Skip small talk and one-off requests. If nothing durable, return an empty list."
            ),
            input=turn_text[:12000],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "extracted_facts",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "items": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "content": {"type": "string"},
                                        "category": {"type": "string", "enum": ["person", "interest", "preference", "name", "other"]},
                                        "action": {"type": "string", "enum": ["add", "forget"]},
                                    },
                                    "required": ["content", "category", "action"],
                                    "additionalProperties": False,
                                },
                            }
                        },
                        "required": ["items"],
                        "additionalProperties": False,
                    },
                }
            },
        )
        raw = response.output_text or '{"items":[]}'
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Fact extraction returned non-JSON: %s", raw[:300])
            return []
        items = payload.get("items") or []
        return [item for item in items if isinstance(item, dict)]

    async def chat(
        self,
        *,
        instructions: str,
        messages: list[OpenAIInputMessage],
        tool_handler: ToolHandler,
        image_generation_handler: ImageGenerationHandler | None = None,
    ) -> ChatResult:
        openai_input = [_to_input_item(message) for message in messages]
        image_bytes: bytes | None = None
        image_prompt: str | None = None
        previous_response_id: str | None = None
        current_input: Any = openai_input

        for _ in range(8):
            kwargs: dict[str, Any] = {
                "model": self.settings.chat_model,
                "instructions": instructions,
                "input": current_input,
                "tools": CHAT_TOOLS,
            }
            if previous_response_id:
                kwargs["previous_response_id"] = previous_response_id
                kwargs.pop("instructions", None)

            response = await self.client.responses.create(**kwargs)
            previous_response_id = response.id
            calls = [item for item in (response.output or []) if getattr(item, "type", None) == "function_call"]
            if not calls:
                return ChatResult(
                    text=(response.output_text or "").strip(),
                    image_bytes=image_bytes,
                    image_prompt=image_prompt,
                )

            outputs: list[dict[str, Any]] = []
            for call in calls:
                name = call.name
                try:
                    args = json.loads(call.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                if name == "generate_image":
                    prompt = str(args.get("prompt") or "")
                    try:
                        if image_generation_handler is not None:
                            image_bytes = await image_generation_handler(prompt)
                        else:
                            image_bytes = await self.generate_image(prompt)
                        if image_bytes is None:
                            tool_output = "Image generation is unavailable because the user's generation balance is empty."
                        else:
                            image_prompt = prompt
                            tool_output = "Image generated and will be sent to the user."
                    except Exception:
                        logger.exception("Image generation failed")
                        tool_output = "Image generation failed. Tell the user it did not work."
                else:
                    tool_output = await tool_handler(name, args)
                outputs.append({"type": "function_call_output", "call_id": call.call_id, "output": tool_output})
            current_input = outputs

        return ChatResult(text="I could not finish the tool loop. Please try again.", image_bytes=image_bytes, image_prompt=image_prompt)


def _to_input_item(message: OpenAIInputMessage) -> dict[str, Any]:
    if message.role == "assistant":
        return {"role": "assistant", "content": message.text or ""}
    if message.image_bytes:
        b64 = base64.b64encode(message.image_bytes).decode("ascii")
        text = message.text or "Please look at this image."
        return {
            "role": "user",
            "content": [
                {"type": "input_text", "text": text},
                {"type": "input_image", "image_url": f"data:image/jpeg;base64,{b64}"},
            ],
        }
    return {"role": "user", "content": message.text or ""}


def _audio_content_type(filename: str) -> str:
    name = filename.lower()
    if name.endswith(".mp3"):
        return "audio/mpeg"
    if name.endswith(".mp4") or name.endswith(".m4a"):
        return "audio/mp4"
    if name.endswith(".wav"):
        return "audio/wav"
    if name.endswith(".webm"):
        return "audio/webm"
    return "audio/ogg"
