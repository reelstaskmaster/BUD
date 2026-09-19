import base64
from types import SimpleNamespace

import pytest

from app.services.openai_client import OpenAIService


class FakeResponse:
    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"data": [{"b64_json": base64.b64encode(b"generated-image").decode("ascii")}]}


class FakeClient:
    def __init__(self) -> None:
        self.payload = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, _url, *, headers, json):
        self.payload = json
        assert headers["Authorization"].startswith("Bearer ")
        return FakeResponse()


@pytest.mark.asyncio
async def test_openrouter_image_generation_sends_reference_image(monkeypatch) -> None:
    service = object.__new__(OpenAIService)
    service.settings = SimpleNamespace(
        openrouter_api_key_pool=["key-1"],
        openrouter_api_key="",
        openrouter_image_model="google/gemini-3.1-flash-image",
    )
    service._key_cooldowns = {}

    fake_client = FakeClient()
    monkeypatch.setattr(
        "app.services.openai_client.httpx.AsyncClient",
        lambda **_kwargs: fake_client,
    )

    result = await service.generate_image(
        "Put the person on a beach at sunset.",
        reference_image=(b"source-image", "image/jpeg"),
    )

    assert result == b"generated-image"
    assert fake_client.payload["model"] == "google/gemini-3.1-flash-image"
    assert fake_client.payload["n"] == 1
    reference = fake_client.payload["input_references"][0]
    assert reference["type"] == "image_url"
    assert reference["image_url"]["url"] == (
        "data:image/jpeg;base64,"
        + base64.b64encode(b"source-image").decode("ascii")
    )


@pytest.mark.asyncio
async def test_openrouter_image_generation_works_without_reference(monkeypatch) -> None:
    service = object.__new__(OpenAIService)
    service.settings = SimpleNamespace(
        openrouter_api_key_pool=["key-1"],
        openrouter_api_key="",
        openrouter_image_model="google/gemini-3.1-flash-image",
    )
    service._key_cooldowns = {}

    fake_client = FakeClient()
    monkeypatch.setattr(
        "app.services.openai_client.httpx.AsyncClient",
        lambda **_kwargs: fake_client,
    )

    result = await service.generate_image("A cinematic beach at sunset.")

    assert result == b"generated-image"
    assert "input_references" not in fake_client.payload

@pytest.mark.asyncio
async def test_image_generation_falls_back_to_openai(monkeypatch) -> None:
    service = object.__new__(OpenAIService)
    service.settings = SimpleNamespace(
        openrouter_api_key_pool=["key-1"],
        openrouter_api_key="",
        openrouter_image_model="google/gemini-3.1-flash-image",
        image_model="gpt-image-1",
    )
    service._key_cooldowns = {}

    class FailedClient(FakeClient):
        async def post(self, _url, *, headers, json):
            return SimpleNamespace(
                status_code=402,
                raise_for_status=lambda: None,
                json=lambda: {},
            )

    monkeypatch.setattr(
        "app.services.openai_client.httpx.AsyncClient",
        lambda **_kwargs: FailedClient(),
    )

    class OpenAIImages:
        async def generate(self, **_kwargs):
            return SimpleNamespace(
                data=[SimpleNamespace(
                    b64_json=base64.b64encode(b"openai-image").decode("ascii"),
                    url=None,
                )]
            )

    service.client = SimpleNamespace(images=OpenAIImages())
    service.settings.openai_api_key_pool = ["openai-key"]

    result = await service.generate_image("A cinematic city at night.")

    assert result == b"openai-image"
