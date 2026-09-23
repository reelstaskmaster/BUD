import pytest

from app.services.capability_registry import Capability, CapabilityRegistry, RiskLevel
from app.services.capability_verifier import CapabilityVerifier


async def _run(args: dict) -> str:
    return "done"


async def _verify(args: dict, output: str) -> bool:
    return output == "done"


@pytest.mark.asyncio
async def test_verifier_accepts_verified_result() -> None:
    capability = Capability("test.read", "Read", RiskLevel.READ, _run, _verify)
    result = await CapabilityVerifier().verify(capability, {}, "done")
    assert result.verified is True


@pytest.mark.asyncio
async def test_verifier_rejects_invalid_result() -> None:
    capability = Capability("test.read", "Read", RiskLevel.READ, _run, _verify)
    result = await CapabilityVerifier().verify(capability, {}, "bad")
    assert result.verified is False


@pytest.mark.asyncio
async def test_verifier_accepts_capability_without_custom_check() -> None:
    capability = Capability("test.read", "Read", RiskLevel.READ, _run)
    result = await CapabilityVerifier().verify(capability, {}, "done")
    assert result.verified is True
