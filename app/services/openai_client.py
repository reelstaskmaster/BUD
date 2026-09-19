from __future__ import annotations

import base64
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from io import BytesIO
from typing import Any

import httpx
from openai import APIConnectionError, APITimeoutError, AsyncOpenAI, RateLimitError

from app.config import Settings

logger = logging.getLogger(__name__)


class OpenAIQuotaError(RuntimeError):
    """The API account has exhausted its available credits/quota."""


class AIProviderError(RuntimeError):
    """A configured AI provider is temporarily unavailable."""


SUPPORTED_IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}

ToolHandler = Callable[[str, dict[str, Any]], Awaitable[str]]

CHAT_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "remember_fact",
        "description": "Store a durable fact about the user or this conversation: people, names, interests, preferences, places, agreements.",
        "parameters": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "The fact to remember, as a short sentence."},
                "category": {"type": "string", "enum": ["person", "interest", "preference", "name", "other"]},
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
    image_mime_type: str | None = None
    image_prompt: str | None = None


@dataclass
class OpenAIInputMessage:
    role: str
    text: str
    image_bytes: bytes | None = None
    image_mime_type: str | None = None


class OpenAIService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = AsyncOpenAI(api_key=settings.openai_api_key, max_retries=0)
        self._provider_cooldowns: dict[str, float] = {}
        self.openrouter = (
            AsyncOpenAI(
                api_key=settings.openrouter_api_key,
                base_url="https://openrouter.ai/api/v1",
                max_retries=0,
            )
            if settings.openrouter_api_key
            else None
        )

    async def transcribe(self, audio: bytes, filename: str = "voice.ogg") -> str:
        if not audio:
            raise ValueError("Empty audio payload")
        buf = BytesIO(audio)
        buf.name = filename
        response = await self.client.audio.transcriptions.create(
            model=self.settings.stt_model,
            file=(filename, buf, _audio_content_type(filename)),
        )
        return (response.text or "").strip()

    async def embed(self, text: str) -> list[float]:
        cleaned = text.strip() or "empty"
        try:
            response = await self.client.embeddings.create(
                model=self.settings.embedding_model,
                input=cleaned,
            )
        except RateLimitError as exc:
            if _is_insufficient_quota(exc):
                raise OpenAIQuotaError("OpenAI API quota is exhausted") from exc
            raise
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
            instructions="Summarize this chat excerpt in 5-8 concise sentences. Keep names, decisions, open questions, and durable context. Write in the same language as the excerpt.",
            input=transcript[:20000],
        )
        return (response.output_text or "").strip()

    async def extract_facts(self, turn_text: str) -> list[dict[str, str]]:
        response = await self.client.responses.create(
            model=self.settings.extract_model,
            instructions="Extract durable facts worth remembering from this conversation turn: people, names, interests, preferences, places, agreements. Skip small talk and one-off requests. If nothing durable, return an empty list.",
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
        try:
            payload = json.loads(response.output_text or '{"items":[]}')
        except json.JSONDecodeError:
            logger.warning("Fact extraction returned non-JSON")
            return []
        return [item for item in payload.get("items", []) if isinstance(item, dict)]

    async def chat(
        self,
        *,
        instructions: str,
        messages: list[OpenAIInputMessage],
        tool_handler: ToolHandler,
    ) -> ChatResult:
        # Keep existing unit-test doubles and legacy callers on the original OpenAI path.
        if not hasattr(self.settings, "ai_providers"):
            return await self._chat_openai(instructions, messages, tool_handler)

        last_error: Exception | None = None
        for provider in self.settings.ai_providers:
            cooldown_until = getattr(self, "_provider_cooldowns", {}).get(provider, 0.0)
            if cooldown_until > time.monotonic():
                logger.info("AI provider %s is cooling down", provider)
                continue
            self._provider_cooldowns.pop(provider, None)
            if provider == "gemini" and self.settings.gemini_api_key:
                try:
                    logger.info("AI provider: gemini")
                    return await self._chat_gemini(instructions, messages, tool_handler)
                except AIProviderError as exc:
                    last_error = exc
                    self._cool_down(provider)
                    logger.warning("Gemini unavailable; falling back: %s", exc)
            elif provider == "openrouter" and self.openrouter:
                try:
                    logger.info("AI provider: openrouter")
                    return await self._chat_openrouter(instructions, messages, tool_handler)
                except AIProviderError as exc:
                    last_error = exc
                    self._cool_down(provider)
                    logger.warning("OpenRouter unavailable; falling back: %s", exc)
            elif provider == "openai" and self.settings.openai_api_key:
                try:
                    logger.info("AI provider: openai")
                    return await self._chat_openai(instructions, messages, tool_handler)
                except OpenAIQuotaError as exc:
                    last_error = exc
                    self._cool_down(provider, 300.0)
                    logger.warning("OpenAI quota exhausted; cooling provider down")
                except RateLimitError as exc:
                    last_error = exc
                    self._cool_down(provider)
                    logger.warning("OpenAI rate limited; falling back")
                except (APIConnectionError, APITimeoutError) as exc:
                    last_error = AIProviderError(f"OpenAI temporarily unavailable: {exc}")
                    self._cool_down(provider)
                    logger.warning("OpenAI unavailable; falling back")
        if last_error:
            raise last_error
        raise AIProviderError("No AI provider is configured")

    def _cool_down(self, provider: str, seconds: float = 30.0) -> None:
        self._provider_cooldowns[provider] = time.monotonic() + seconds

    async def _chat_openai(
        self,
        instructions: str,
        messages: list[OpenAIInputMessage],
        tool_handler: ToolHandler,
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
            try:
                response = await self.client.responses.create(**kwargs)
            except RateLimitError as exc:
                if _is_insufficient_quota(exc):
                    raise OpenAIQuotaError("OpenAI API quota is exhausted") from exc
                raise
            previous_response_id = response.id
            calls = [item for item in (response.output or []) if getattr(item, "type", None) == "function_call"]
            if not calls:
                return ChatResult((response.output_text or "").strip(), image_bytes, "image/png" if image_bytes else None, image_prompt)
            outputs: list[dict[str, Any]] = []
            for call in calls:
                tool_output, image_bytes, image_prompt = await self._run_tool(call.name, call.arguments, tool_handler, image_bytes, image_prompt)
                outputs.append({"type": "function_call_output", "call_id": call.call_id, "output": tool_output})
            current_input = outputs
        return ChatResult("I could not finish the tool loop. Please try again.", image_bytes, "image/png" if image_bytes else None, image_prompt)

    async def _chat_openrouter(self, instructions: str, messages: list[OpenAIInputMessage], tool_handler: ToolHandler) -> ChatResult:
        if not self.openrouter:
            raise AIProviderError("OpenRouter API key is missing")
        history: list[dict[str, Any]] = [{"role": "system", "content": instructions}]
        history.extend(_to_chat_message(message) for message in messages)
        image_bytes: bytes | None = None
        image_prompt: str | None = None
        for _ in range(8):
            try:
                response = await self.openrouter.chat.completions.create(
                    model=self.settings.openrouter_chat_model,
                    messages=history,
                    tools=[_to_openai_chat_tool(tool) for tool in CHAT_TOOLS],
                )
            except Exception as exc:
                raise _provider_error("OpenRouter", exc) from exc
            choice = response.choices[0].message
            if not choice.tool_calls:
                return ChatResult((choice.content or "").strip(), image_bytes, "image/png" if image_bytes else None, image_prompt)
            history.append(choice.model_dump(exclude_none=True))
            for call in choice.tool_calls:
                tool_output, image_bytes, image_prompt = await self._run_tool(call.function.name, call.function.arguments, tool_handler, image_bytes, image_prompt)
                history.append({"role": "tool", "tool_call_id": call.id, "content": tool_output})
        return ChatResult("I could not finish the tool loop. Please try again.", image_bytes, "image/png" if image_bytes else None, image_prompt)

    async def _chat_gemini(self, instructions: str, messages: list[OpenAIInputMessage], tool_handler: ToolHandler) -> ChatResult:
        contents = [_to_gemini_message(message) for message in messages]
        tools = [{"functionDeclarations": [_to_gemini_tool(tool) for tool in CHAT_TOOLS]}]
        image_bytes: bytes | None = None
        image_prompt: str | None = None
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.settings.gemini_chat_model}:generateContent"
        headers = {"x-goog-api-key": self.settings.gemini_api_key}
        async with httpx.AsyncClient(timeout=60) as http:
            for _ in range(8):
                payload = {"systemInstruction": {"parts": [{"text": instructions}]}, "contents": contents, "tools": tools}
                try:
                    response = await http.post(url, headers=headers, json=payload)
                    response.raise_for_status()
                except Exception as exc:
                    raise _provider_error("Gemini", exc) from exc
                data = response.json()
                candidate = (data.get("candidates") or [{}])[0]
                content = candidate.get("content") or {}
                parts = content.get("parts") or []
                calls = [part.get("functionCall") for part in parts if part.get("functionCall")]
                if not calls:
                    text = "".join(part.get("text", "") for part in parts).strip()
                    return ChatResult(text, image_bytes, "image/png" if image_bytes else None, image_prompt)
                contents.append(content)
                for call in calls:
                    args = call.get("args") or {}
                    tool_output, image_bytes, image_prompt = await self._run_tool(call.get("name", ""), json.dumps(args), tool_handler, image_bytes, image_prompt)
                    contents.append({"role": "user", "parts": [{"functionResponse": {"name": call.get("name", ""), "id": call.get("id"), "response": {"result": tool_output}}}]})
        return ChatResult("I could not finish the tool loop. Please try again.", image_bytes, "image/png" if image_bytes else None, image_prompt)

    async def _run_tool(
        self,
        name: str,
        raw_arguments: str,
        tool_handler: ToolHandler,
        image_bytes: bytes | None,
        image_prompt: str | None,
    ) -> tuple[str, bytes | None, str | None]:
        try:
            args = json.loads(raw_arguments or "{}")
        except json.JSONDecodeError:
            args = {}
        args = args if isinstance(args, dict) else {}
        if name == "generate_image":
            prompt = str(args.get("prompt") or "").strip()
            if not prompt:
                return "Image generation requires a non-empty prompt.", image_bytes, image_prompt
            try:
                image_bytes = await self.generate_image(prompt)
                return "Image generated and will be sent to the user.", image_bytes, prompt
            except Exception:
                logger.exception("Image generation failed")
                return "Image generation failed. Tell the user it did not work.", image_bytes, image_prompt
        return await tool_handler(name, args), image_bytes, image_prompt


def _provider_error(provider: str, exc: Exception) -> AIProviderError:
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status is None:
        status = getattr(exc, "status_code", None)
    if isinstance(exc, httpx.TimeoutException):
        return AIProviderError(f"{provider} timeout")
    if isinstance(exc, httpx.RequestError):
        return AIProviderError(f"{provider} network error")
    if status in {429, 500, 502, 503, 504}:
        return AIProviderError(f"{provider} temporarily unavailable ({status})")
    raise exc


def _to_input_item(message: OpenAIInputMessage) -> dict[str, Any]:
    if message.role == "assistant":
        return {"role": "assistant", "content": message.text or ""}
    if message.image_bytes:
        mime_type = message.image_mime_type or "image/jpeg"
        if mime_type not in SUPPORTED_IMAGE_MIME_TYPES:
            raise ValueError(f"Unsupported image MIME type: {mime_type}")
        b64 = base64.b64encode(message.image_bytes).decode("ascii")
        return {"role": "user", "content": [{"type": "input_text", "text": message.text or "Please look at this image."}, {"type": "input_image", "image_url": f"data:{mime_type};base64,{b64}"}]}
    return {"role": "user", "content": message.text or ""}


def _to_chat_message(message: OpenAIInputMessage) -> dict[str, Any]:
    if message.image_bytes:
        mime = message.image_mime_type or "image/jpeg"
        b64 = base64.b64encode(message.image_bytes).decode("ascii")
        return {"role": "user", "content": [{"type": "text", "text": message.text or "Please look at this image."}, {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}]}
    return {"role": message.role, "content": message.text or ""}


def _to_openai_chat_tool(tool: dict[str, Any]) -> dict[str, Any]:
    return {"type": "function", "function": {"name": tool["name"], "description": tool["description"], "parameters": tool["parameters"]}}


def _to_gemini_tool(tool: dict[str, Any]) -> dict[str, Any]:
    return {"name": tool["name"], "description": tool["description"], "parameters": tool["parameters"]}


def _to_gemini_message(message: OpenAIInputMessage) -> dict[str, Any]:
    role = "model" if message.role == "assistant" else "user"
    parts: list[dict[str, Any]] = []
    if message.text:
        parts.append({"text": message.text})
    if message.image_bytes:
        parts.append({"inlineData": {"mimeType": message.image_mime_type or "image/jpeg", "data": base64.b64encode(message.image_bytes).decode("ascii")}})
    return {"role": role, "parts": parts or [{"text": ""}]}


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


def _is_insufficient_quota(exc: RateLimitError) -> bool:
    return getattr(exc, "code", None) == "insufficient_quota" or "credit_balance_exhausted" in str(exc)