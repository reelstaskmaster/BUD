import pytest

from app.services.needle_router import NeedleRoute, NeedleRouter


def test_needle_schemas_are_normalized_and_deduplicated() -> None:
    tools = [
        {
            "type": "function",
            "name": "web_fetch",
            "description": "Fetch",
            "parameters": {"type": "object"},
        },
        {
            "type": "function",
            "name": "web_fetch",
            "description": "Duplicate",
            "parameters": {"type": "object"},
        },
    ]
    assert NeedleRouter._schemas(tools) == [
        {
            "name": "web_fetch",
            "description": "Fetch",
            "parameters": {"type": "object"},
        }
    ]


def test_needle_low_confidence_escalates_to_full_toolset() -> None:
    router = NeedleRouter(confidence_threshold=0.5)
    route = router._parse(
        {"function_calls": [{"name": "web_fetch"}], "confidence": 0.2},
        {"web_fetch"},
    )
    assert route.tool_names == ()
    assert route.confidence == 0.2


def test_needle_route_renders_hint() -> None:
    route = NeedleRoute(("web_fetch", "github_read_file"), 0.91, True)
    hint = NeedleRouter.render_hint(route)
    assert "web_fetch" in hint
    assert "github_read_file" in hint
    assert "0.91" in hint


@pytest.mark.asyncio
async def test_needle_router_falls_back_without_blocking(monkeypatch: pytest.MonkeyPatch) -> None:
    router = NeedleRouter()
    async def broken(_: list[dict]) -> object:
        raise RuntimeError("broken")
    monkeypatch.setattr(router, "_get_agent", broken)
    route = await router.route(
        "check github",
        [{"type": "function", "name": "github_read_file", "parameters": {"type": "object"}}],
    )
    assert route.available is False
    assert route.tool_names == ()
