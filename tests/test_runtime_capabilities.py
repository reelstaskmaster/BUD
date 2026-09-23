import pytest
import httpx

from app.services.runtime_capabilities import RuntimeCapabilities


class FakeSettings:
    capability_timeout_s = 5
    github_token = ""
    webhook_base_url = "https://example.test"


@pytest.mark.asyncio
async def test_github_read_file_returns_text(monkeypatch) -> None:
    class Response:
        status_code = 200
        text = "print('ok')"

    async def fake_get(self, *args, **kwargs):
        return Response()

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    result = await RuntimeCapabilities(FakeSettings()).github_read_file(
        {"repository": "reelstaskmaster/BUD", "path": "README.md"}
    )
    assert result == "print('ok')"


@pytest.mark.asyncio
async def test_railway_health_reports_status(monkeypatch) -> None:
    class Response:
        status_code = 200
        text = '{"status":"ok"}'

    async def fake_get(self, *args, **kwargs):
        return Response()

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    result = await RuntimeCapabilities(FakeSettings()).railway_health({})
    assert result.startswith("HTTP 200")
