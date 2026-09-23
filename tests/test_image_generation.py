import base64
from types import SimpleNamespace

import pytest

from app.services.openai_client import AIProviderError, OpenAIService


class FakeResponse:
    def __init__(self, status_code: int = 200, data: dict | None = None) -> None:
        self.status_code = status_code
        self._data = data or {
            "data": [{"b64_json": base64.b64encode(b"generated-image").decode("ascii")}]
        }
        self.text = '{"error":"test"}'

    def json(self) -> dict:
        return self._data


class FakeClient:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.calls: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, url, *, headers, json):
        self.calls.append({"url": url, "headers": headers, "json": json})
        return self.responses.pop(0)


def _settings(**overrides):
    values = {
        "freellmapi_api_key": "freellmapi-key",
        "freellmapi_base_url": "http://freellmapi/v1",
        "freellmapi_image_model": "auto",
        "gemini_api_key_pool": [],
        "gemini_api_key": "",
        "gemini_image_model": "gemini-3.1-flash-image",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.asyncio
async def test_freellmapi_image_generation_sends_reference_image(monkeypatch) -> None:
    service = object.__new__(OpenAIService)
    service.settings = _settings()

    fake_client = FakeClient([FakeResponse()])
    monkeypatch.setattr(
        "app.services.openai_client.httpx.AsyncClient",
        lambda **_kwargs: fake_client,
    )

    result = await service.generate_image(
        "Put the person on a beach at sunset.",
        reference_image=(b"source-image", "image/jpeg"),
    )

    assert result == b"generated-image"
    call = fake_client.calls[0]
    assert call["url"] == "http://freellmapi/v1/images/generations"
    assert call["headers"]["Authorization"] == "Bearer freellmapi-key"
    reference = call["json"]["input_references"][0]
    assert reference["type"] == "image_url"
    assert reference["image_url"]["url"] == (
        "data:image/jpeg;base64,"
        + base64.b64encode(b"source-image").decode("ascii")
    )


@pytest.mark.asyncio
async def test_freellmapi_image_generation_rejects_invalid_base64(monkeypatch) -> None:
    service = object.__new__(OpenAIService)
    service.settings = _settings()

    fake_client = FakeClient(
        [FakeResponse(data={"data": [{"b64_json": "not-valid-base64!!!"}]})]
    )
    monkeypatch.setattr(
        "app.services.openai_client.httpx.AsyncClient",
        lambda **_kwargs: fake_client,
    )

    with pytest.raises(AIProviderError, match="invalid base64"):
        await service.generate_image("test")


class FakeGeminiClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, url, *, headers, json):
        self.calls.append({"url": url, "headers": headers, "json": json})
        if url.endswith("/images/generations"):
            return FakeResponse(status_code=502)
        return FakeResponse(
            data={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "inlineData": {
                                        "mimeType": "image/png",
                                        "data": base64.b64encode(b"gemini-image").decode("ascii"),
                                    }
                                }
                            ]
                        }
                    }
                ]
            }
        )


@pytest.mark.asyncio
async def test_image_generation_falls_back_to_gemini(monkeypatch) -> None:
    service = object.__new__(OpenAIService)
    service.settings = _settings(gemini_api_key_pool=["gemini-key"])
    service._key_cooldowns = {}

    fake_client = FakeGeminiClient()
    monkeypatch.setattr(
        "app.services.openai_client.httpx.AsyncClient",
        lambda **_kwargs: fake_client,
    )

    result = await service.generate_image("A beach at sunset.")

    assert result == b"gemini-image"
    assert len(fake_client.calls) == 2
    assert fake_client.calls[0]["url"].endswith("/images/generations")
    assert fake_client.calls[1]["headers"]["x-goog-api-key"] == "gemini-key"
    assert fake_client.calls[1]["json"]["generationConfig"]["responseModalities"] == ["IMAGE"]
