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
    def __init__(self, response=None) -> None:
        self.payload = None
        self.response = response or FakeResponse()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, _url, *, headers, json):
        self.payload = json
        assert headers["Authorization"].startswith("Bearer ")
        return self.response


def make_service() -> OpenAIService:
    service = object.__new__(OpenAIService)
    service.settings = SimpleNamespace(
        freellmapi_api_key="free-key",
        freellmapi_image_model="auto",
        freellmapi_base_url="http://freellmapi.test/v1",
    )
    return service


@pytest.mark.asyncio
async def test_free_image_generation_sends_reference_image(monkeypatch) -> None:
    service = make_service()
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
    assert fake_client.payload["model"] == "auto"
    assert "n" not in fake_client.payload
    assert "resolution" not in fake_client.payload
    reference = fake_client.payload["input_references"][0]
    assert reference["type"] == "image_url"
    assert reference["image_url"]["url"] == (
        "data:image/jpeg;base64,"
        + base64.b64encode(b"source-image").decode("ascii")
    )


@pytest.mark.asyncio
async def test_free_image_generation_works_without_reference(monkeypatch) -> None:
    service = make_service()
    fake_client = FakeClient()
    monkeypatch.setattr(
        "app.services.openai_client.httpx.AsyncClient",
        lambda **_kwargs: fake_client,
    )

    result = await service.generate_image("A cinematic beach at sunset.")

    assert result == b"generated-image"
    assert "input_references" not in fake_client.payload


class BadBase64Response(FakeResponse):
    def json(self) -> dict:
        return {"data": [{"b64_json": "not-valid-base64!!!"}]}


@pytest.mark.asyncio
async def test_free_image_generation_rejects_invalid_base64(monkeypatch) -> None:
    service = make_service()
    fake_client = FakeClient(response=BadBase64Response())
    monkeypatch.setattr(
        "app.services.openai_client.httpx.AsyncClient",
        lambda **_kwargs: fake_client,
    )

    with pytest.raises(Exception, match="invalid base64"):
        await service.generate_image("test")
