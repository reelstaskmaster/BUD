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
    assert "repository=reelstaskmaster/BUD" in result
    assert "path=README.md" in result
    assert "print('ok')" in result


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


class WriteSettings(FakeSettings):
    github_token = "test-token"


@pytest.mark.asyncio
async def test_github_create_branch(monkeypatch) -> None:
    class Response:
        status_code = 200
        def json(self):
            return {"object": {"sha": "base-sha"}}

    class PostResponse:
        status_code = 201

    async def fake_get(self, *args, **kwargs):
        return Response()

    async def fake_post(self, *args, **kwargs):
        assert kwargs["json"]["sha"] == "base-sha"
        return PostResponse()

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    result = await RuntimeCapabilities(WriteSettings()).github_create_branch(
        {"repository": "reelstaskmaster/BUD", "branch": "agent/test"}
    )
    assert result == "Created branch agent/test from main."


@pytest.mark.asyncio
async def test_github_update_file(monkeypatch) -> None:
    class PutResponse:
        status_code = 200
        def json(self):
            return {"commit": {"sha": "commit-sha"}}

    class VerifyResponse:
        status_code = 200
        def json(self):
            import base64
            return {
                "encoding": "base64",
                "content": base64.b64encode(b"updated").decode("ascii"),
            }

    async def fake_put(self, *args, **kwargs):
        assert kwargs["json"]["sha"] == "blob-sha"
        return PutResponse()

    async def fake_get(self, *args, **kwargs):
        assert kwargs["params"]["ref"] == "agent/test"
        return VerifyResponse()

    monkeypatch.setattr(httpx.AsyncClient, "put", fake_put)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    result = await RuntimeCapabilities(WriteSettings()).github_update_file(
        {
            "repository": "reelstaskmaster/BUD",
            "path": "README.md",
            "branch": "agent/test",
            "content": "updated",
            "message": "test update",
            "sha": "blob-sha",
        }
    )
    assert "Verified content matches" in result


@pytest.mark.asyncio
async def test_github_create_pr_creates_draft(monkeypatch) -> None:
    class Response:
        status_code = 201
        def json(self):
            return {"number": 7, "html_url": "https://github.com/reelstaskmaster/BUD/pull/7"}

    async def fake_post(self, *args, **kwargs):
        assert kwargs["json"]["draft"] is True
        return Response()

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    result = await RuntimeCapabilities(WriteSettings()).github_create_pr(
        {
            "repository": "reelstaskmaster/BUD",
            "head": "agent/test",
            "title": "Test PR",
        }
    )
    assert "Created draft PR #7" in result
