from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.capability_registry import Capability


@dataclass(frozen=True)
class VerificationResult:
    verified: bool
    detail: str = ""


class CapabilityVerifier:
    """Small verification layer for capability results."""

    async def verify(
        self,
        capability: Capability,
        args: dict[str, Any],
        output: str,
    ) -> VerificationResult:
        if capability.verify is None:
            return VerificationResult(True, "No custom verifier required")
        verified = await capability.verify(args, output)
        if not verified:
            return VerificationResult(False, f"Verification failed: {capability.name}")
        return VerificationResult(True, "Verified")
