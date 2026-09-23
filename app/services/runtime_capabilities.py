from __future__ import annotations

from typing import Any

import httpx

from app.config import Settings


class RuntimeCapabilities:
    """Safe read-only integrations exposed to the agent runtime."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def github_read_file(self, args: dict[str, Any]) -> str:
        repository = str(args.get("repository") or "").strip()
        path = str(args.get("path") or "").strip()
        ref = str(args.get("ref") or "main").strip()
        if not repository or not path:
            return "github_read_file requires repository and path."
        if "/" not in repository:
            return "repository must use owner/name format."

        url = f"https://api.github.com/repos/{repository}/contents/{path.lstrip('/')}"
        headers = {"Accept": "application/vnd.github.raw+json"}
        if self.settings.github_token:
            headers["Authorization"] = f"Bearer {self.settings.github_token}"

        try:
            async with httpx.AsyncClient(timeout=self.settings.capability_timeout_s) as http:
                response = await http.get(url, headers=headers, params={"ref": ref})
        except httpx.TimeoutException:
            return "GitHub read timed out."
        except httpx.RequestError:
            return "GitHub read failed due to a network error."

        if response.status_code == 404:
            return "GitHub file not found or repository is not accessible."
        if response.status_code in {401, 403}:
            return "GitHub access denied. Configure GITHUB_TOKEN for private repositories."
        if response.status_code >= 400:
            return f"GitHub read failed with HTTP {response.status_code}."

        text = response.text
        if len(text) > 16000:
            text = text[:16000] + "\n[Output truncated]"
        return text

    async def railway_health(self, args: dict[str, Any]) -> str:
        url = str(args.get("url") or self.settings.webhook_base_url).strip().rstrip("/")
        if not url:
            return "railway_health requires a URL or WEBHOOK_BASE_URL."
        try:
            async with httpx.AsyncClient(timeout=self.settings.capability_timeout_s) as http:
                response = await http.get(f"{url}/health")
        except httpx.TimeoutException:
            return "Railway health check timed out."
        except httpx.RequestError:
            return "Railway health check failed due to a network error."
        return f"HTTP {response.status_code}: {response.text[:500]}"
