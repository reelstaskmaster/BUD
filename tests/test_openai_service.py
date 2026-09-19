import base64
import json

import pytest

from app.services.openai_client import OpenAIService


class FakeResponse:
    def __init__(self, output_text: str = "", output=None, response_id: str = "r1"):
        self.output_text = output_text
        self.output = output or []
        self.id = response_id


class FakeCall:
    type = "function_call"

    def __init__(self, name: str, arguments: str, call_id: str = "c1"):
        self.name = name
        self.arguments = arguments
        self.call_id = call_id


class FakeResponses:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return next(self.responses)


class FakeClient:
    def __init__(self, responses):
        self.responses = FakeResponses(responses)


@pytest.mark.asyncio
async def test_chat_returns_plain_response_without_tool_calls() -> None:
    service = object.__new__(OpenAIService)
    service.settings = type("Settings", (), {"chat_model": "test"})()
    service.client = FakeClient([FakeResponse(output_text="готово")])

    async def handler(_name, _args):
        raise AssertionError("tool handler must not be called")

    result = await service.chat(instructions="i", messages=[], tool_handler=handler)
    assert result.text == "готово"
    assert len(service.client.responses.calls) == 1


@pytest.mark.asyncio
async def test_chat_executes_function_call_and_continues() -> None:
    service = object.__new__(OpenAIService)
    service.settings = type("Settings", (), {"chat_model": "test"})()
    service.client = FakeClient([
        FakeResponse(output=[FakeCall("remember_fact", json.dumps({"content": "X", "category": "name"}))], response_id="r1"),
        FakeResponse(output_text="сохранено", response_id="r2"),
    ])
    seen = []

    async def handler(name, args):
        seen.append((name, args))
        return "Fact stored."

    result = await service.chat(instructions="i", messages=[], tool_handler=handler)
    assert result.text == "сохранено"
    assert seen == [("remember_fact", {"content": "X", "category": "name"})]
    assert service.client.responses.calls[1]["previous_response_id"] == "r1"
    assert service.client.responses.calls[1]["input"][0]["type"] == "function_call_output"


@pytest.mark.asyncio
async def test_chat_stops_after_tool_loop_limit() -> None:
    service = object.__new__(OpenAIService)
    service.settings = type("Settings", (), {"chat_model": "test"})()
    service.client = FakeClient([
        FakeResponse(output=[FakeCall("unknown", "{}")], response_id=str(i))
        for i in range(8)
    ])

    async def handler(_name, _args):
        return "ok"

    result = await service.chat(instructions="i", messages=[], tool_handler=handler)
    assert "tool loop" in result.text.lower()
    assert len(service.client.responses.calls) == 8


def test_generate_image_result_is_base64_decodable() -> None:
    payload = b"png-bytes"
    encoded = base64.b64encode(payload).decode("ascii")
    assert base64.b64decode(encoded) == payload


@pytest.mark.asyncio
async def test_chat_normalizes_non_object_tool_arguments() -> None:
    service = object.__new__(OpenAIService)
    service.settings = type("Settings", (), {"chat_model": "test"})()
    service.client = FakeClient([
        FakeResponse(
            output=[FakeCall("remember_fact", "[\"bad\"]")],
            response_id="r1",
        ),
        FakeResponse(output_text="ok", response_id="r2"),
    ])
    seen = []

    async def handler(name, args):
        seen.append((name, args))
        return "ok"

    result = await service.chat(instructions="i", messages=[], tool_handler=handler)
    assert result.text == "ok"
    assert seen == [("remember_fact", {})]


@pytest.mark.asyncio
async def test_chat_rejects_empty_image_prompt() -> None:
    service = object.__new__(OpenAIService)
    service.settings = type("Settings", (), {"chat_model": "test"})()
    service.client = FakeClient([
        FakeResponse(
            output=[FakeCall("generate_image", '{"prompt":"   "}')],
            response_id="r1",
        ),
        FakeResponse(output_text="ok", response_id="r2"),
    ])

    async def handler(_name, _args):
        raise AssertionError("generate_image must not use the generic handler")

    async def fail_generate(_prompt):
        raise AssertionError("image API must not be called")

    service.generate_image = fail_generate
    result = await service.chat(instructions="i", messages=[], tool_handler=handler)
    assert result.text == "ok"


def test_to_input_item_rejects_unsupported_image_mime() -> None:
    from app.services.openai_client import OpenAIInputMessage, _to_input_item

    message = OpenAIInputMessage(
        role="user",
        text="look",
        image_bytes=b"svg",
        image_mime_type="image/svg+xml",
    )
    with pytest.raises(ValueError, match="Unsupported image MIME type"):
        _to_input_item(message)


def test_to_input_item_uses_persisted_supported_image_mime() -> None:
    from app.services.openai_client import OpenAIInputMessage, _to_input_item

    message = OpenAIInputMessage(
        role="user",
        text="look",
        image_bytes=b"png",
        image_mime_type="image/png",
    )
    item = _to_input_item(message)
    assert item["content"][1]["image_url"].startswith("data:image/png;base64,")


@pytest.mark.asyncio
async def test_chat_falls_back_from_gemini_to_openrouter() -> None:
    service = object.__new__(OpenAIService)
    service.settings = type(
        "Settings",
        (),
        {
            "ai_providers": ["gemini", "openrouter", "openai"],
            "gemini_api_key": "gemini-key",
            "openai_api_key": "",
        },
    )()
    service.openrouter = object()

    async def gemini(_instructions, _messages, _handler):
        from app.services.openai_client import AIProviderError
        raise AIProviderError("Gemini timeout")

    async def openrouter(_instructions, _messages, _handler):
        return type("Result", (), {"text": "router ok"})()

    service._chat_gemini = gemini
    service._chat_openrouter = openrouter

    async def handler(_name, _args):
        return "ok"

    result = await service.chat(instructions="i", messages=[], tool_handler=handler)
    assert result.text == "router ok"


@pytest.mark.asyncio
async def test_chat_does_not_fallback_on_bad_request() -> None:
    service = object.__new__(OpenAIService)
    service.settings = type(
        "Settings",
        (),
        {
            "ai_providers": ["gemini", "openrouter"],
            "gemini_api_key": "gemini-key",
            "openai_api_key": "",
        },
    )()
    service.openrouter = object()

    async def gemini(_instructions, _messages, _handler):
        raise ValueError("bad request")

    async def openrouter(_instructions, _messages, _handler):
        raise AssertionError("must not fall back on a bad request")

    service._chat_gemini = gemini
    service._chat_openrouter = openrouter

    async def handler(_name, _args):
        return "ok"

    with pytest.raises(ValueError, match="bad request"):
        await service.chat(instructions="i", messages=[], tool_handler=handler)


@pytest.mark.asyncio
async def test_provider_network_error_is_fallbackable() -> None:
    service = object.__new__(OpenAIService)
    service.settings = type(
        "Settings",
        (),
        {
            "ai_providers": ["gemini", "openrouter"],
            "gemini_api_key": "gemini-key",
            "openai_api_key": "",
        },
    )()
    service.openrouter = object()

    async def gemini(_instructions, _messages, _handler):
        import httpx
        from app.services.openai_client import _provider_error
        raise _provider_error("Gemini", httpx.ConnectError("offline"))

    async def openrouter(_instructions, _messages, _handler):
        return type("Result", (), {"text": "router ok"})()

    service._chat_gemini = gemini
    service._chat_openrouter = openrouter

    async def handler(_name, _args):
        return "ok"

    result = await service.chat(instructions="i", messages=[], tool_handler=handler)
    assert result.text == "router ok"


@pytest.mark.asyncio
async def test_unavailable_provider_is_cooled_down() -> None:
    service = object.__new__(OpenAIService)
    service.settings = type(
        "Settings",
        (),
        {
            "ai_providers": ["gemini", "openrouter"],
            "gemini_api_key": "gemini-key",
            "openai_api_key": "",
        },
    )()
    service.openrouter = object()
    service._provider_cooldowns = {"gemini": 10**12}

    async def gemini(_instructions, _messages, _handler):
        raise AssertionError("cooled provider must not be called")

    async def openrouter(_instructions, _messages, _handler):
        return type("Result", (), {"text": "router ok"})()

    service._chat_gemini = gemini
    service._chat_openrouter = openrouter

    async def handler(_name, _args):
        return "ok"

    result = await service.chat(instructions="i", messages=[], tool_handler=handler)
    assert result.text == "router ok"
