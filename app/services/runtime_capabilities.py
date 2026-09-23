from __future__ import annotations

import base64
from typing import Any

import httpx

from app.config import Settings


class RuntimeCapabilities:
    """Controlled external integrations exposed to the agent runtime."""

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
        headers = self._github_headers()
        headers["Accept"] = "application/vnd.github.raw+json"

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

    async def github_create_branch(self, args: dict[str, Any]) -> str:
        repository = str(args.get("repository") or "").strip()
        branch = str(args.get("branch") or "").strip()
        base_ref = str(args.get("base_ref") or "main").strip()
        if not repository or not branch:
            return "github_create_branch requires repository and branch."
        if "/" not in repository:
            return "repository must use owner/name format."
        if not _valid_branch_name(branch):
            return "Invalid branch name."

        url = f"https://api.github.com/repos/{repository}/git/refs"
        headers = self._github_headers()
        payload = {"ref": f"refs/heads/{branch}"}

        try:
            base = await self._github_get_ref(repository, base_ref)
            payload["sha"] = base
            async with httpx.AsyncClient(timeout=self.settings.capability_timeout_s) as http:
                response = await http.post(url, headers=headers, json=payload)
        except httpx.TimeoutException:
            return "GitHub branch creation timed out."
        except httpx.RequestError:
            return "GitHub branch creation failed due to a network error."
        except httpx.HTTPStatusError as exc:
            return f"GitHub base ref lookup failed with HTTP {exc.response.status_code}."

        if response.status_code == 422:
            return "GitHub branch creation failed: branch may already exist or base ref is invalid."
        if response.status_code in {401, 403}:
            return "GitHub write access denied. Configure GITHUB_TOKEN with repository write permission."
        if response.status_code >= 400:
            return f"GitHub branch creation failed with HTTP {response.status_code}."
        return f"Created branch {branch} from {base_ref}."

    async def github_update_file(self, args: dict[str, Any]) -> str:
        repository = str(args.get("repository") or "").strip()
        path = str(args.get("path") or "").strip()
        branch = str(args.get("branch") or "").strip()
        content = str(args.get("content") or "")
        message = str(args.get("message") or "").strip()
        sha = str(args.get("sha") or "").strip()
        if not repository or not path or not branch or not message:
            return "github_update_file requires repository, path, branch, and message."
        if "/" not in repository:
            return "repository must use owner/name format."
        if not self.settings.github_token:
            return "GITHUB_TOKEN is required for GitHub write operations."

        url = f"https://api.github.com/repos/{repository}/contents/{path.lstrip('/')}"
        payload: dict[str, Any] = {"message": message, "content": base64.b64encode(content.encode("utf-8")).decode("ascii"), "branch": branch}
        if sha:
            payload["sha"] = sha
        headers = self._github_headers()

        try:
            async with httpx.AsyncClient(timeout=self.settings.capability_timeout_s) as http:
                response = await http.put(url, headers=headers, json=payload)
        except httpx.TimeoutException:
            return "GitHub file update timed out."
        except httpx.RequestError:
            return "GitHub file update failed due to a network error."

        if response.status_code in {401, 403}:
            return "GitHub write access denied. Configure GITHUB_TOKEN with repository write permission."
        if response.status_code == 409:
            return "GitHub file update conflicted with the current repository state."
        if response.status_code == 422:
            return "GitHub file update rejected; check path, branch, SHA, or repository permissions."
        if response.status_code >= 400:
            return f"GitHub file update failed with HTTP {response.status_code}."
        data = response.json()
        commit_sha = ((data.get("commit") or {}).get("sha") or "")
        return f"Updated {path} on {branch}. Commit: {commit_sha or 'created'}"

    async def github_create_pr(self, args: dict[str, Any]) -> str:
        repository = str(args.get("repository") or "").strip()
        head = str(args.get("head") or "").strip()
        base = str(args.get("base") or "main").strip()
        title = str(args.get("title") or "").strip()
        body = str(args.get("body") or "").strip()
        if not repository or not head or not title:
            return "github_create_pr requires repository, head, and title."
        if "/" not in repository:
            return "repository must use owner/name format."
        if not self.settings.github_token:
            return "GITHUB_TOKEN is required for GitHub write operations."

        url = f"https://api.github.com/repos/{repository}/pulls"
        headers = self._github_headers()
        payload = {"title": title, "head": head, "base": base, "body": body, "draft": True}

        try:
            async with httpx.AsyncClient(timeout=self.settings.capability_timeout_s) as http:
                response = await http.post(url, headers=headers, json=payload)
        except httpx.TimeoutException:
            return "GitHub pull request creation timed out."
        except httpx.RequestError:
            return "GitHub pull request creation failed due to a network error."

        if response.status_code in {401, 403}:
            return "GitHub write access denied. Configure GITHUB_TOKEN with repository write permission."
        if response.status_code == 422:
            return "GitHub pull request creation rejected; check branch names and whether a PR already exists."
        if response.status_code >= 400:
            return f"GitHub pull request creation failed with HTTP {response.status_code}."
        data = response.json()
        return f"Created draft PR #{data.get('number', '?')}: {data.get('html_url', '')}"

    def _github_headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.settings.github_token:
            headers["Authorization"] = f"Bearer {self.settings.github_token}"
        return headers

    async def _github_get_ref(self, repository: str, ref: str) -> str:
        url = f"https://api.github.com/repos/{repository}/git/ref/heads/{ref}"
        async with httpx.AsyncClient(timeout=self.settings.capability_timeout_s) as http:
            response = await http.get(url, headers=self._github_headers())
        if response.status_code >= 400:
            raise httpx.HTTPStatusError("GitHub ref lookup failed", request=response.request, response=response)
        return str(((response.json().get("object") or {}).get("sha") or ""))

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


def _valid_branch_name(value: str) -> bool:
    return bool(value) and " " not in value and not value.startswith("-") and not value.endswith(".") and ".." not in value
