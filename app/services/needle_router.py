from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any, Iterable

logger = logging.getLogger(__name__)

# BUD does not need usage telemetry from an embedded local router.
os.environ["NEEDLE_TELEMETRY"] = "0"
os.environ["DO_NOT_TRACK"] = "1"


@dataclass(frozen=True)
class NeedleRoute:
    tool_names: tuple[str, ...]
    confidence: float | None
    available: bool


class NeedleRouter:
    """Optional local tool router; never executes tools and never replaces Hermes."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        confidence_threshold: float = 0.35,
    ) -> None:
        self.enabled = enabled
        self.confidence_threshold = confidence_threshold
        self._agent: Any | None = None
        self._lock = asyncio.Lock()

    async def route(
        self,
        query: str,
        tools: Iterable[dict[str, Any]],
    ) -> NeedleRoute:
        if not self.enabled or not query.strip():
            return NeedleRoute((), None, False)

        schemas = self._schemas(tools)
        if not schemas:
            return NeedleRoute((), None, False)

        try:
            agent = await self._get_agent(schemas)
            response = await asyncio.to_thread(agent.complete, query, 256)
            return self._parse(response, {item["name"] for item in schemas})
        except Exception as exc:
            logger.warning("Needle local routing unavailable; keeping full toolset: %s", exc)
            return NeedleRoute((), None, False)

    async def _get_agent(self, schemas: list[dict[str, Any]]) -> Any:
        if self._agent is not None:
            return self._agent
        async with self._lock:
            if self._agent is not None:
                return self._agent
            import needle

            self._agent = needle.Needle(
                tools=schemas,
                generation=3,
                stateless=True,
            )
            return self._agent

    @staticmethod
    def _schemas(tools: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for tool in tools:
            if tool.get("type") != "function":
                continue
            name = str(tool.get("name") or "").strip()
            parameters = tool.get("parameters")
            if not name or not isinstance(parameters, dict) or name in seen:
                continue
            seen.add(name)
            result.append(
                {
                    "name": name,
                    "description": str(tool.get("description") or ""),
                    "parameters": parameters,
                }
            )
        return result

    def _parse(
        self,
        response: dict[str, Any],
        available_names: set[str],
    ) -> NeedleRoute:
        calls = response.get("function_calls") or []
        selected: list[str] = []
        for call in calls:
            name = str(call.get("name") or "").strip()
            if name in available_names and name not in selected:
                selected.append(name)

        confidence_raw = response.get("confidence")
        try:
            confidence = float(confidence_raw) if confidence_raw is not None else None
        except (TypeError, ValueError):
            confidence = None

        if not selected or (confidence is not None and confidence < self.confidence_threshold):
            return NeedleRoute((), confidence, True)
        return NeedleRoute(tuple(selected), confidence, True)

    @staticmethod
    def render_hint(route: NeedleRoute) -> str:
        if not route.tool_names:
            return ""
        confidence = (
            f"{route.confidence:.2f}"
            if route.confidence is not None
            else "unknown"
        )
        names = ", ".join(route.tool_names)
        return (
            "Needle local routing hint (non-authoritative; tools are not executed by Needle): "
            f"prioritize these tools when they match the request: {names}. "
            f"Needle confidence: {confidence}. Independently verify the choice and arguments."
        )

    async def close(self) -> None:
        agent, self._agent = self._agent, None
        if agent is not None:
            try:
                await asyncio.to_thread(agent.close)
            except Exception:
                logger.debug("Needle router close failed", exc_info=True)
