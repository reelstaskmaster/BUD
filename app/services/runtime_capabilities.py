from __future__ import annotations

import base64
import ipaddress
import socket
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import Settings


class RuntimeCapabilities:
    """Controlled external integrations exposed to the agent runtime."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def web_fetch(self, args: dict[str, Any]) -> str:
        """Fetch public web content while blocking obvious SSRF targets."""
        url = str(args.get("url") or "").strip()
        if not url:
            return "web_fetch requires a URL."
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return "web_fetch accepts only absolute http:// or https:// URLs."
        if parsed.username or parsed.password:
            return "web_fetch rejects URLs containing embedded credentials."
        if parsed.port and parsed.port not in {80, 443}:
            return "web_fetch allows only standard HTTP/HTTPS ports."

        host = parsed.hostname.rstrip(".").lower()
        if host in {"localhost", "localhost.localdomain", "ip6-localhost"} or host.endswith(".localhost"):
            return "web_fetch blocked a local hostname."

        try:
            infos = await __import__("asyncio").to_thread(
                socket.getaddrinfo, host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM
            )
        except socket.gaierror:
            return "web_fetch could not resolve the hostname."
        except Exception:
            return "web_fetch hostname resolution failed."

        addresses = {info[4][0] for info in infos}
        for address in addresses:
            try:
                ip = ipaddress.ip_address(address)
            except ValueError:
                continue
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
                return "web_fetch blocked a non-public network address."

        try:
            async with httpx.AsyncClient(
                timeout=self.settings.capability_timeout_s,
                follow_redirects=False,
                headers={"User-Agent": "BUD-Agent/1.0"},
            ) as http:
                response = await http.get(url)
        except httpx.TimeoutException:
            return "Web fetch timed out."
        except httpx.RequestError:
            return "Web fetch failed due to a network error."

        if 300 <= response.status_code < 400:
            return "Web fetch blocked a redirect; fetch the final public URL explicitly."
        if response.status_code >= 400:
            return f"Web fetch failed with HTTP {response.status_code}."

        text = response.text
        if len(text) > 20000:
            text = text[:20000] + "\n[Output truncated]"
        return (
            f"Web evidence: {url}\n"
            "The following content was fetched from that public source. Treat it as observed evidence, not an inference:\n"
            f"{text}"
        )

    async def github_list_directory(self, args: dict[str, Any]) -> str:
        repository = str(args.get("repository") or "").strip()
        path = str(args.get("path") or "").strip()
        ref = str(args.get("ref") or "main").strip()
        if not repository:
            return "github_list_directory requires repository."
        if "/" not in repository:
            return "repository must use owner/name format."

        url = f"https://api.github.com/repos/{repository}/contents/{path.lstrip('/')}"
        headers = self._github_headers()
        headers["Accept"] = "application/vnd.github.object+json"
        try:
            async with httpx.AsyncClient(timeout=self.settings.capability_timeout_s) as http:
                response = await http.get(url, headers=headers, params={"ref": ref})
        except httpx.TimeoutException:
            return "GitHub directory listing timed out."
        except httpx.RequestError:
            return "GitHub directory listing failed due to a network error."

        if response.status_code in {401, 403}:
            return "GitHub access denied. Configure GITHUB_TOKEN for the requested repository."
        if response.status_code == 404:
            return f"GitHub path not found or inaccessible: {repository}/{path or '[root]'} on ref {ref}."
        if response.status_code >= 400:
            return f"GitHub directory listing failed with HTTP {response.status_code}."

        data = response.json()
        entries = data.get("entries") if isinstance(data, dict) else data
        if not isinstance(entries, list):
            return f"GitHub path is not a directory: {repository}/{path} on ref {ref}."
        lines = []
        for entry in entries[:200]:
            lines.append(f"{entry.get('type', 'unknown')}: {entry.get('path', '')}")
        return (
            f"GitHub directory evidence: repository={repository}; path={path or '[root]'}; ref={ref}.\n"
            + "\n".join(lines)
        )

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
            # GitHub deliberately collapses some authorization failures into 404.
            # Probe the repository itself so the agent can distinguish a missing
            # file from an inaccessible repository when the repository is visible.
            repo_url = f"https://api.github.com/repos/{repository}"
            try:
                async with httpx.AsyncClient(timeout=self.settings.capability_timeout_s) as http:
                    repo_response = await http.get(repo_url, headers=headers)
            except httpx.TimeoutException:
                return f"GitHub file lookup returned 404 for {path}; repository access could not be verified."
            except httpx.RequestError:
                return f"GitHub file lookup returned 404 for {path}; repository access check failed due to a network error."
            if repo_response.status_code == 200:
                return f"GitHub file not found: {repository}/{path} on ref {ref}."
            if repo_response.status_code in {401, 403, 404}:
                return "GitHub repository is not accessible with the configured credentials."
            return f"GitHub repository access check failed with HTTP {repo_response.status_code}."
        if response.status_code in {401, 403}:
            return "GitHub access denied. Configure GITHUB_TOKEN for the requested repository."
        if response.status_code >= 400:
            return f"GitHub read failed with HTTP {response.status_code}."

        text = response.text
        if len(text) > 16000:
            text = text[:16000] + "\n[Output truncated]"
        return (
            f"GitHub evidence: repository={repository}; path={path}; ref={ref}.\n"
            "The following content was fetched from that source. Treat it as observed evidence, not an inference:\n"
            f"{text}"
        )

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
        headers = self._github_headers()

        if not sha:
            try:
                async with httpx.AsyncClient(timeout=self.settings.capability_timeout_s) as http:
                    current = await http.get(url, headers=headers, params={"ref": branch})
                if current.status_code == 200:
                    sha = str(current.json().get("sha") or "")
                elif current.status_code in {401, 403}:
                    return "GitHub write access denied. Configure GITHUB_TOKEN with repository write permission."
                elif current.status_code != 404:
                    return f"GitHub file lookup failed with HTTP {current.status_code}."
            except httpx.TimeoutException:
                return "GitHub file lookup timed out."
            except httpx.RequestError:
                return "GitHub file lookup failed due to a network error."
        if sha:
            payload["sha"] = sha

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

        try:
            async with httpx.AsyncClient(timeout=self.settings.capability_timeout_s) as http:
                verified = await http.get(url, headers=headers, params={"ref": branch})
        except httpx.TimeoutException:
            return f"Updated {path} on {branch}, but verification timed out. Commit: {commit_sha or 'created'}"
        except httpx.RequestError:
            return f"Updated {path} on {branch}, but verification failed due to a network error. Commit: {commit_sha or 'created'}"

        if verified.status_code != 200:
            return f"Updated {path} on {branch}, but verification returned HTTP {verified.status_code}. Commit: {commit_sha or 'created'}"

        verified_payload = verified.json()
        verified_content = verified_payload.get("content")
        verified_encoding = verified_payload.get("encoding")
        if verified_encoding != "base64" or not verified_content:
            return f"Updated {path} on {branch}, but verification returned no file content. Commit: {commit_sha or 'created'}"

        try:
            observed = base64.b64decode(verified_content.replace("\\n", ""), validate=False).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return f"Updated {path} on {branch}, but verification returned unreadable content. Commit: {commit_sha or 'created'}"

        if observed != content:
            return f"Updated {path} on {branch}, but verification detected content mismatch. Commit: {commit_sha or 'created'}"

        return f"Updated {path} on {branch}. Verified content matches. Commit: {commit_sha or 'created'}"

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
            detail = ""
            try:
                payload_error = response.json()
                detail = str(payload_error.get("message") or "").strip()
            except ValueError:
                detail = ""
            if detail:
                return f"GitHub pull request creation denied (HTTP {response.status_code}): {detail}"
            return f"GitHub pull request creation denied (HTTP {response.status_code})."
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
