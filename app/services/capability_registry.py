from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Awaitable, Callable


class RiskLevel(StrEnum):
    READ = "read"
    WRITE = "write"
    DESTRUCTIVE = "destructive"


CapabilityExecutor = Callable[[dict[str, Any]], Awaitable[str]]
CapabilityVerifier = Callable[[dict[str, Any], str], Awaitable[bool]]


@dataclass(frozen=True)
class Capability:
    name: str
    description: str
    risk: RiskLevel
    execute: CapabilityExecutor
    verify: CapabilityVerifier | None = None


class CapabilityRegistry:
    """Small, explicit capability registry for the autonomous agent.

    Capabilities are opt-in: registering a capability is the only way the
    executor can discover it. No dynamic imports or arbitrary tool execution.
    """

    def __init__(self) -> None:
        self._items: dict[str, Capability] = {}

    def register(self, capability: Capability) -> None:
        if not capability.name.strip():
            raise ValueError("Capability name cannot be empty")
        if capability.name in self._items:
            raise ValueError(f"Capability already registered: {capability.name}")
        self._items[capability.name] = capability

    def get(self, name: str) -> Capability | None:
        return self._items.get(name)

    def list(self) -> tuple[Capability, ...]:
        return tuple(self._items.values())

    async def execute(self, name: str, args: dict[str, Any]) -> str:
        capability = self.get(name)
        if capability is None:
            raise KeyError(f"Unknown capability: {name}")
        result = await capability.execute(args)
        if capability.verify is not None:
            verified = await capability.verify(args, result)
            if not verified:
                raise RuntimeError(f"Capability verification failed: {name}")
        return result
