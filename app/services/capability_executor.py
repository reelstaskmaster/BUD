from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.capability_registry import CapabilityRegistry, RiskLevel


@dataclass(frozen=True)
class ExecutionResult:
    capability: str
    output: str
    verified: bool


class CapabilityExecutor:
    """Execute only capabilities explicitly present in the registry.

    Destructive actions are blocked unless the caller supplies an explicit
    authorization flag. The executor itself never discovers arbitrary tools.
    """

    def __init__(self, registry: CapabilityRegistry) -> None:
        self.registry = registry

    async def run(
        self,
        name: str,
        args: dict[str, Any],
        *,
        authorize_destructive: bool = False,
    ) -> ExecutionResult:
        capability = self.registry.get(name)
        if capability is None:
            raise KeyError(f"Unknown capability: {name}")

        if capability.risk == RiskLevel.DESTRUCTIVE and not authorize_destructive:
            raise PermissionError(f"Explicit authorization required: {name}")

        output = await self.registry.execute(name, args)
        return ExecutionResult(
            capability=name,
            output=output,
            verified=capability.verify is not None,
        )
