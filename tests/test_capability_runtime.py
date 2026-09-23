import pytest

from app.services.capability_executor import CapabilityExecutor
from app.services.capability_registry import Capability, CapabilityRegistry, RiskLevel


async def _run(args: dict) -> str:
    return "ok"


@pytest.mark.asyncio
async def test_memory_capability_executes_through_registry() -> None:
    registry = CapabilityRegistry()
    registry.register(Capability("remember_fact", "Memory", RiskLevel.WRITE, _run))
    result = await CapabilityExecutor(registry).run("remember_fact", {"content": "x"})
    assert result.output == "ok"
