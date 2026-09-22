from __future__ import annotations

import base64
import binascii
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
            "properties": {
                "prompt": {"type": "string", "description": "Detailed image generation or editing prompt."},
                "use_reference": {"type": "boolean", "description": "True when the user wants to edit or transform an image they provided in this conversation."},
            },
            "required": ["prompt", "use_reference"],
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
        openai_keys = getattr(settings, "openai_api_key_pool", None) or ([settings.openai_api_key] if settings.openai_api_key else [])
        openrouter_keys = getattr(settings, "openrouter_api_key_pool", None) or ([settings.openrouter_api_key] if settings.openrouter_api_key else [])
        freellmapi_key = getattr(settings, "freellmapi_api_key", "")
        self._openai_clients = [AsyncOpenAI(api_key=key, max_retries=0, timeout=settings.ai_request_timeout_s) for key in openai_keys]
        self.client = self._openai_clients[0] if self._openai_clients else AsyncOpenAI(api_key="", max_retries=0)
        self._openrouter_clients = [
            AsyncOpenAI(api_key=key, base_url="https://openrouter.ai/api/v1", max_retries=0, timeout=settings.ai_request_timeout_s)
            for key in openrouter_keys
        ]
        self.openrouter = self._openrouter_clients[0] if self._openrouter_clients else None
        self._freellmapi_client = AsyncOpenAI(api_key=freellmapi_key or "missing", base_url=settings.freellmapi_base_url, max_retries=0, timeout=settings.ai_request_timeout_s)
        self._provider_cooldowns: dict[str, float] = {}
        self._key_cooldowns: dict[tuple[str, int], float] = {}
        self._provider_next_index: dict[str, int] = {}

    async def transcribe(self, audio: bytes, filename: str = "voice.ogg") -> str:
        if not audio:
            raise ValueError("Empty audio payload")
        buf = BytesIO(audio)
        buf.name = filename
        try:
            response = await self._freellmapi_client.audio.transcriptions.create(
                model=self.settings.freellmapi_stt_model,
                file=(filename, buf, _audio_content_type(filename)),
            )
        except Exception as exc:
            raise _provider_error("FreeLLMAPI transcription", exc) from exc
        return (response.text or "").strip()

    async def embed(self, text: str) -> list[float]:
        cleaned = text.strip() or "empty"
        try:
            response = await self._freellmapi_client.embeddings.create(
                model=self.settings.freellmapi_embedding_model,
                input=cleaned,
            )
        except Exception as exc:
            raise _provider_error("FreeLLMAPI embeddings", exc) from exc
        return list(response.data[0].embedding)

    async def generate_image(
        self,
        prompt: str,
        *,
        reference_image: tuple[bytes, str] | None = None,
    ) -> bytes:
        """Generate an image only through FreeLLMAPI; never fall back to paid providers."""
        payload: dict[str, Any] = {
            "model": self.settings.freellmapi_image_model,
            "prompt": prompt,
        }
        if reference_image:
            image_bytes, mime_type = reference_image
            encoded = base64.b64encode(image_bytes).decode("ascii")
            payload["input_references"] = [{
                "type": "image_url",
                "image_url": {"url": f"data:{mime_type};base64,{encoded}"},
            }]

        url = f"{self.settings.freellmapi_base_url.rstrip('/')}/images/generations"
        try:
            async with httpx.AsyncClient(timeout=120) as http:
                response = await http.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {self.settings.freellmapi_api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
            if response.status_code >= 400:
                detail = response.text[:500].replace("\n", " ")
                raise AIProviderError(
                    f"FreeLLMAPI image generation unavailable ({response.status_code}): {detail}"
                )
            data = response.json()
            items = data.get("data") or []
            if not items:
                raise AIProviderError("FreeLLMAPI image generation returned no image data")
            b64 = items[0].get("b64_json")
            if not b64:
                raise AIProviderError("FreeLLMAPI image generation returned no base64 image")
            return base64.b64decode(b64, validate=True)
        except (httpx.RequestError, httpx.TimeoutException) as exc:
            raise AIProviderError("FreeLLMAPI image generation network error") from exc
        except (ValueError, binascii.Error) as exc:
            raise AIProviderError("FreeLLMAPI image generation returned invalid base64") from exc

    async def summarize(self, transcript: str) -> str:
        response = await self._freellmapi_client.chat.completions.create(
            model=self.settings.freellmapi_chat_model,
            messages=[
                {
                    "role": "system",
                    "content": "Summarize this chat excerpt in 5-8 concise sentences. Keep names, decisions, open questions, and durable context. Write in the same language as the excerpt.",
                },
                {"role": "user", "content": transcript[:20000]},
            ],
        )
        return (response.choices[0].message.content or "").strip()

    async def extract_facts(self, turn_text: str) -> list[dict[str, str]]:
        response = await self._freellmapi_client.chat.completions.create(
            model=self.settings.freellmapi_chat_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Extract durable facts worth remembering. Return ONLY valid JSON with an items array. "
                        "Each item must have content, category (person, interest, preference, name, other), "
                        "and action (add or forget). Skip small talk and one-off requests. "
                        "Return an empty items array when nothing durable exists."
                    ),
                },
                {"role": "user", "content": turn_text[:12000]},
            ],
        )
        try:
            payload = json.loads(response.choices[0].message.content or '{"items":[]}')
        except json.JSONDecodeError:
            logger.warning("FreeLLMAPI fact extraction returned non-JSON")
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
        provider_pools = {
            "freellmapi": self._configured_keys("freellmapi"),
            "gemini": self._configured_keys("gemini"),
            "openrouter": self._configured_keys("openrouter"),
            "openai": self._configured_keys("openai"),
        }
        for provider in self.settings.ai_providers:
            cooldowns = getattr(self, "_provider_cooldowns", None)
            if cooldowns is None:
                cooldowns = self._provider_cooldowns = {}
            if cooldowns.get(provider, 0.0) > time.monotonic():
                logger.info("AI provider %s is cooling down", provider)
                continue
            cooldowns.pop(provider, None)

            keys = provider_pools.get(provider, [])
            if not keys:
                continue
            start_index = self._next_key_index(provider, len(keys))
            attempted = 0
            successful_key = False

            for offset in range(len(keys)):
                index = (start_index + offset) % len(keys)
                if self._key_is_cooling(provider, index):
                    continue
                attempted += 1
                try:
                    logger.info("AI provider: %s key=%d/%d", provider, index + 1, len(keys))
                    if provider == "freellmapi":
                        result = await self._chat_freellmapi(instructions, messages, tool_handler)
                    elif provider == "gemini":
                        if len(keys) == 1:
                            result = await self._chat_gemini(instructions, messages, tool_handler)
                        else:
                            result = await self._chat_gemini(instructions, messages, tool_handler, api_key=keys[index])
                    elif provider == "openrouter":
                        client = self._openrouter_client(index)
                        if len(keys) == 1:
                            result = await self._chat_openrouter(instructions, messages, tool_handler)
                        else:
                            result = await self._chat_openrouter(instructions, messages, tool_handler, client=client)
                    elif provider == "openai":
                        client = self._openai_client(index)
                        if len(keys) == 1:
                            result = await self._chat_openai(instructions, messages, tool_handler)
                        else:
                            result = await self._chat_openai(instructions, messages, tool_handler, client=client)
                    else:
                        continue
                    successful_key = True
                    return result
                except OpenAIQuotaError as exc:
                    last_error = exc
                    self._cool_down_key(provider, index, 300.0)
                    logger.warning("%s key %d quota exhausted; trying next key", provider, index + 1)
                except RateLimitError as exc:
                    last_error = exc
                    self._cool_down_key(provider, index)
                    logger.warning("%s key %d rate limited; trying next key", provider, index + 1)
                except (APIConnectionError, APITimeoutError) as exc:
                    last_error = AIProviderError(f"{provider} temporarily unavailable: {exc}")
                    self._cool_down_key(provider, index)
                    logger.warning("%s key %d unavailable; trying next key", provider, index + 1)
                except AIProviderError as exc:
                    last_error = exc
                    self._cool_down_key(provider, index)
                    logger.warning("%s key %d unavailable; trying next key: %s", provider, index + 1, exc)

            if attempted and not successful_key:
                self._cool_down(provider)

        if last_error:
            raise last_error
        raise AIProviderError("No AI provider is configured")


    async def _chat_freellmapi(
        self,
        instructions: str,
        messages: list[OpenAIInputMessage],
        tool_handler: ToolHandler,
    ) -> ChatResult:
        if not self.settings.freellmapi_api_key:
            raise AIProviderError("FreeLLMAPI API key is missing")
        history: list[dict[str, Any]] = [{"role": "system", "content": instructions}]
        history.extend(_to_chat_message(message) for message in messages)
        image_bytes: bytes | None = None
        image_prompt: str | None = None
        for _ in range(self.settings.ai_max_tool_rounds):
            try:
                response = await self._freellmapi_client.chat.completions.create(
                    model=self.settings.freellmapi_chat_model,
                    messages=history,
                    tools=[_to_openai_chat_tool(tool) for tool in CHAT_TOOLS],
                )
            except Exception as exc:
                raise _provider_error("FreeLLMAPI", exc) from exc
            choice = response.choices[0].message
            if not choice.tool_calls:
                return ChatResult(
                    (choice.content or "").strip(),
                    image_bytes,
                    "image/png" if image_bytes else None,
                    image_prompt,
                )
            history.append(choice.model_dump(exclude_none=True))
            reference_image = _latest_reference_image(messages)
            for call in choice.tool_calls:
                tool_output, image_bytes, image_prompt = await self._run_tool(
                    call.function.name,
                    call.function.arguments,
                    tool_handler,
                    image_bytes,
                    image_prompt,
                    reference_image=reference_image,
                )
                history.append({"role": "tool", "tool_call_id": call.id, "content": tool_output})
        return ChatResult(
            "I could not finish the tool loop. Please try again.",
            image_bytes,
            "image/png" if image_bytes else None,
            image_prompt,
        )

    def _real_api_keys(self, provider: str) -> list[str]:
        pool_attr = f"{provider}_api_key_pool"
        singular_attr = f"{provider}_api_key"
        pool = getattr(self.settings, pool_attr, None)
        if pool:
            return list(pool)
        key = getattr(self.settings, singular_attr, "")
        return [key] if key else []

    def _available_key_indexes(
        self,
        provider: str,
        keys: list[str],
    ) -> list[tuple[int, str]]:
        now = time.monotonic()
        cooldowns = getattr(self, "_key_cooldowns", None) or {}
        return [
            (index, key)
            for index, key in enumerate(keys)
            if cooldowns.get((provider, index), 0.0) <= now
        ]

    def _configured_keys(self, provider: str) -> list[str]:
        pool_attr = f"{provider}_api_key_pool"
        singular_attr = f"{provider}_api_key"
        pool = getattr(self.settings, pool_attr, None)
        if pool:
            return list(pool)
        key = getattr(self.settings, singular_attr, "")
        if key:
            return [key]
        # Preserve lightweight test doubles/legacy callers that expose only
        # an already-created OpenRouter client.
        if provider == "openrouter" and getattr(self, "openrouter", None):
            return ["__configured_client__"]
        return []

    def _next_key_index(self, provider: str, count: int) -> int:
        if count <= 1:
            return 0
        next_indexes = getattr(self, "_provider_next_index", None)
        if next_indexes is None:
            next_indexes = self._provider_next_index = {}
        index = next_indexes.get(provider, 0) % count
        next_indexes[provider] = (index + 1) % count
        return index

    def _key_is_cooling(self, provider: str, index: int) -> bool:
        cooldowns = getattr(self, "_key_cooldowns", None) or {}
        return cooldowns.get((provider, index), 0.0) > time.monotonic()

    def _cool_down_key(self, provider: str, index: int, seconds: float = 30.0) -> None:
        cooldowns = getattr(self, "_key_cooldowns", None)
        if cooldowns is None:
            cooldowns = self._key_cooldowns = {}
        cooldowns[(provider, index)] = time.monotonic() + seconds

    def _openai_client(self, index: int) -> AsyncOpenAI:
        clients = getattr(self, "_openai_clients", None) or [self.client]
        return clients[index % len(clients)]

    def _openrouter_client(self, index: int) -> AsyncOpenAI:
        clients = getattr(self, "_openrouter_clients", None) or ([self.openrouter] if self.openrouter else [])
        if not clients:
            raise AIProviderError("OpenRouter API key is missing")
        return clients[index % len(clients)]

    def _cool_down(self, provider: str, seconds: float = 30.0) -> None:
        self._provider_cooldowns[provider] = time.monotonic() + seconds

    async def _chat_openai(
        self,
        instructions: str,
        messages: list[OpenAIInputMessage],
        tool_handler: ToolHandler,
        client: AsyncOpenAI | None = None,
    ) -> ChatResult:
        client = client or self.client
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
                response = await client.responses.create(**kwargs)
            except RateLimitError as exc:
                if _is_insufficient_quota(exc):
                    raise OpenAIQuotaError("OpenAI API quota is exhausted") from exc
                raise
            previous_response_id = response.id
            calls = [item for item in (response.output or []) if getattr(item, "type", None) == "function_call"]
            if not calls:
                return ChatResult((response.output_text or "").strip(), image_bytes, "image/png" if image_bytes else None, image_prompt)
            outputs: list[dict[str, Any]] = []
            reference_image = _latest_reference_image(messages)
            for call in calls:
                tool_output, image_bytes, image_prompt = await self._run_tool(
                    call.name,
                    call.arguments,
                    tool_handler,
                    image_bytes,
                    image_prompt,
                    reference_image=reference_image,
                )
                outputs.append({"type": "function_call_output", "call_id": call.call_id, "output": tool_output})
            current_input = outputs
        return ChatResult("I could not finish the tool loop. Please try again.", image_bytes, "image/png" if image_bytes else None, image_prompt)

    async def _chat_openrouter(
        self,
        instructions: str,
        messages: list[OpenAIInputMessage],
        tool_handler: ToolHandler,
        client: AsyncOpenAI | None = None,
    ) -> ChatResult:
        client = client or self.openrouter
        if not client:
            raise AIProviderError("OpenRouter API key is missing")
        history: list[dict[str, Any]] = [{"role": "system", "content": instructions}]
        history.extend(_to_chat_message(message) for message in messages)
        image_bytes: bytes | None = None
        image_prompt: str | None = None
        for _ in range(8):
            try:
                response = await client.chat.completions.create(
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
            reference_image = _latest_reference_image(messages)
            for call in choice.tool_calls:
                tool_output, image_bytes, image_prompt = await self._run_tool(
                    call.function.name,
                    call.function.arguments,
                    tool_handler,
                    image_bytes,
                    image_prompt,
                    reference_image=reference_image,
                )
                history.append({"role": "tool", "tool_call_id": call.id, "content": tool_output})
        return ChatResult("I could not finish the tool loop. Please try again.", image_bytes, "image/png" if image_bytes else None, image_prompt)

    async def _chat_gemini(
        self,
        instructions: str,
        messages: list[OpenAIInputMessage],
        tool_handler: ToolHandler,
        api_key: str | None = None,
    ) -> ChatResult:
        api_key = api_key or self.settings.gemini_api_key
        contents = [_to_gemini_message(message) for message in messages]
        tools = [{"functionDeclarations": [_to_gemini_tool(tool) for tool in CHAT_TOOLS]}]
        image_bytes: bytes | None = None
        image_prompt: str | None = None
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.settings.gemini_chat_model}:generateContent"
        headers = {"x-goog-api-key": api_key}
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
                reference_image = _latest_reference_image(messages)
                for call in calls:
                    args = call.get("args") or {}
                    tool_output, image_bytes, image_prompt = await self._run_tool(
                        call.get("name", ""),
                        json.dumps(args),
                        tool_handler,
                        image_bytes,
                        image_prompt,
                        reference_image=reference_image,
                    )
                    contents.append({"role": "user", "parts": [{"functionResponse": {"name": call.get("name", ""), "id": call.get("id"), "response": {"result": tool_output}}}]})
        return ChatResult("I could not finish the tool loop. Please try again.", image_bytes, "image/png" if image_bytes else None, image_prompt)

    async def _run_tool(
        self,
        name: str,
        raw_arguments: str,
        tool_handler: ToolHandler,
        image_bytes: bytes | None,
        image_prompt: str | None,
        *,
        reference_image: tuple[bytes, str] | None = None,
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
            use_reference = bool(args.get("use_reference", False))
            try:
                image_bytes = await self.generate_image(
                    prompt,
                    reference_image=reference_image if use_reference else None,
                )
                return "Image generated and will be sent to the user.", image_bytes, prompt
            except Exception:
                logger.exception("Image generation failed")
                return "Image generation failed. Tell the user it did not work.", image_bytes, image_prompt
        return await tool_handler(name, args), image_bytes, image_prompt


def _latest_reference_image(
    messages: list[OpenAIInputMessage],
) -> tuple[bytes, str] | None:
    for message in reversed(messages):
        if message.role == "user" and message.image_bytes:
            return message.image_bytes, message.image_mime_type or "image/jpeg"
    return None


def _provider_error(provider: str, exc: Exception) -> AIProviderError:
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status is None:
        status = getattr(exc, "status_code", None)
    if isinstance(exc, httpx.TimeoutException):
        return AIProviderError(f"{provider} timeout")
    if isinstance(exc, httpx.RequestError):
        return AIProviderError(f"{provider} network error")
    if status in {401, 402, 403, 408, 429, 500, 502, 503, 504, 524, 529}:
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