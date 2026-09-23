import pytest

from app.services.capability_registry import (
    Capability,
    CapabilityRegistry,
    RiskLevel,
)


async def _read(args: dict) -> str:
    return args["value"]


async def _verify(args: dict, result: str) -> bool:
    return result == args["value"]


@pytest.mark.asyncio
async def test_registry_registers_and_verifies_capability() -> None:
    registry = CapabilityRegistry()
    registry.register(
        Capability(
            name="test.read",
            description="Read test data",
            risk=RiskLevel.READ,
            execute=_read,
            verify=_verify,
        )
    )
    assert await registry.execute("test.read", {"value": "ok"}) == "ok"


def test_registry_rejects_duplicate_capability() -> None:
    registry = CapabilityRegistry()
    capability = Capability("test.read", "Read", RiskLevel.READ, _read)
    registry.register(capability)
    with pytest.raises(ValueError):
        registry.register(capability)


@pytest.mark.asyncio
async def test_registry_rejects_unknown_capability() -> None:
    registry = CapabilityRegistry()
    with pytest.raises(KeyError):
        await registry.execute("missing", {})
