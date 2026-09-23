import pytest

from app.services.capability_executor import CapabilityExecutor
from app.services.capability_registry import Capability, CapabilityRegistry, RiskLevel


async def _run(args: dict) -> str:
    return "done"


@pytest.mark.asyncio
async def test_executor_runs_registered_capability() -> None:
    registry = CapabilityRegistry()
    registry.register(Capability("test.read", "Read", RiskLevel.READ, _run))
    result = await CapabilityExecutor(registry).run("test.read", {})
    assert result.output == "done"


@pytest.mark.asyncio
async def test_executor_blocks_destructive_action_without_authorization() -> None:
    registry = CapabilityRegistry()
    registry.register(Capability("test.delete", "Delete", RiskLevel.DESTRUCTIVE, _run))
    with pytest.raises(PermissionError):
        await CapabilityExecutor(registry).run("test.delete", {})


@pytest.mark.asyncio
async def test_executor_allows_explicit_destructive_authorization() -> None:
    registry = CapabilityRegistry()
    registry.register(Capability("test.delete", "Delete", RiskLevel.DESTRUCTIVE, _run))
    result = await CapabilityExecutor(registry).run(
        "test.delete", {}, authorize_destructive=True
    )
    assert result.output == "done"
