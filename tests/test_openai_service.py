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
