from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from app.services.openai_client import AIProviderError, OpenAIService


@dataclass(frozen=True)
class ClaudexReview:
    verdict: str
    summary: str
    findings: tuple[str, ...] = ()
    raw: str = ""


class ClaudexLoop:
    """Bounded cross-provider review/inspection for Hermes.

    Hermes remains the coordinator and builder. A configured independent
    provider only reviews the plan/result; it never receives write tools.
    """

    _VERDICTS = {"APPROVED", "REVISE", "BLOCKED"}

    def __init__(
        self,
        ai: OpenAIService,
        *,
        enabled: bool = True,
        reviewer_provider: str = "gemini",
        reviewer_model: str = "",
        max_rounds: int = 2,
    ) -> None:
        self.ai = ai
        self.enabled = enabled
        self.reviewer_provider = reviewer_provider.strip().lower()
        self.reviewer_model = reviewer_model.strip()
        self.max_rounds = max(1, min(max_rounds, 5))

    async def review_plan(self, *, query: str, plan: str) -> ClaudexReview:
        if not self.enabled:
            return ClaudexReview("APPROVED", "Claudex review is disabled.")

        prompt = (
            "You are the independent reviewer in a Claudex-style engineering loop. "
            "Hermes is the coordinator and will execute the plan after review. "
            "Review the plan adversarially. Do not implement anything. "
            "Do not assume that a claim is true without evidence. "
            "Return ONLY JSON with keys: verdict, summary, findings. "
            "verdict must be APPROVED, REVISE, or BLOCKED. "
            "findings must be an array of concise strings.\n\n"
            f"USER GOAL:\n{query[:12000]}\n\n"
            f"PLAN:\n{plan[:16000]}"
        )
        last = ClaudexReview("BLOCKED", "No review result.")
        for _ in range(self.max_rounds):
            raw = await self.ai.independent_text(
                system=(
                    "You are a strict, independent software reviewer. "
                    "You are not the author of the plan. "
                    "Do not use tools and do not modify files."
                ),
                user=prompt,
                provider=self.reviewer_provider,
                model=self.reviewer_model or None,
            )
            review = self._parse(raw)
            last = review
            if review.verdict == "APPROVED":
                return review
            if review.verdict == "BLOCKED":
                return review
            prompt = (
                prompt
                + "\n\nPREVIOUS REVIEW FINDINGS:\n"
                + "\n".join(f"- {item}" for item in review.findings)
                + "\n\nRe-review the same plan after considering these findings. "
                "Return JSON only."
            )
        return last

    async def inspect_result(
        self,
        *,
        query: str,
        plan: str,
        result: str,
    ) -> ClaudexReview:
        if not self.enabled:
            return ClaudexReview("APPROVED", "Claudex inspection is disabled.")

        prompt = (
            "Independently inspect the result of an engineering task. "
            "The coordinator/builder produced the result; you must not grade your own work. "
            "Look for unsupported completion claims, missing verification, contradictions, "
            "unsafe changes, and failure to satisfy the stated goal. "
            "Return ONLY JSON with keys: verdict, summary, findings. "
            "verdict must be APPROVED, REVISE, or BLOCKED.\n\n"
            f"GOAL:\n{query[:10000]}\n\n"
            f"PLAN:\n{plan[:12000]}\n\n"
            f"RESULT/EVIDENCE:\n{result[:16000]}"
        )
        raw = await self.ai.independent_text(
            system=(
                "You are a fresh, independent final inspector. "
                "You have read-only review authority only. "
                "Do not use tools and do not modify files."
            ),
            user=prompt,
            provider=self.reviewer_provider,
            model=self.reviewer_model or None,
        )
        return self._parse(raw)

    @classmethod
    def _parse(cls, raw: str) -> ClaudexReview:
        value: dict[str, Any] | None = None
        candidates = [raw.strip()]
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if match:
            candidates.append(match.group(0))
        for candidate in reversed(candidates):
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                value = parsed
                break
        if value is None:
            raise AIProviderError("Claudex reviewer returned malformed JSON.")

        verdict = str(value.get("verdict") or "").upper().strip()
        if verdict not in cls._VERDICTS:
            raise AIProviderError("Claudex reviewer returned an invalid verdict.")
        summary = str(value.get("summary") or "").strip()
        findings_value = value.get("findings") or []
        findings = tuple(str(item).strip() for item in findings_value if str(item).strip())
        return ClaudexReview(verdict, summary, findings, raw)
