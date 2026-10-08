from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    body: str
    path: str


class SkillRegistry:
    """Local, read-only Hermes-style skill registry.

    Skills are shipped with BUD and never execute code by themselves.
    Only their instructions are injected into the agent context when a
    trigger matches the current task.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self._skills = self._load()

    def list(self) -> tuple[Skill, ...]:
        return tuple(self._skills.values())

    def matching(self, query: str, limit: int = 3) -> list[Skill]:
        text = query.casefold()
        scored: list[tuple[int, Skill]] = []
        for skill in self._skills.values():
            haystack = f"{skill.name} {skill.description}".casefold()
            tokens = [token for token in re.findall(r"[a-zа-я0-9_-]{4,}", haystack)]
            score = sum(1 for token in set(tokens) if token in text)
            if score:
                scored.append((score, skill))
        scored.sort(key=lambda item: (-item[0], item[1].name))
        return [skill for _, skill in scored[:limit]]

    def render_for_query(self, query: str, limit: int = 3) -> str:
        selected = self.matching(query, limit=limit)
        if not selected:
            return ""
        blocks = []
        for skill in selected:
            blocks.append(
                f"Hermes skill: {skill.name}\n"
                f"Use when relevant; treat this as procedure, not as proof of execution.\n"
                f"{skill.body.strip()}"
            )
        return "\n\n".join(blocks)

    def _load(self) -> dict[str, Skill]:
        if not self.root.exists():
            return {}
        result: dict[str, Skill] = {}
        for path in sorted(self.root.glob("*/*/SKILL.md")):
            try:
                content = path.read_text(encoding="utf-8")
                name, description, body = _parse_skill(content)
            except (OSError, ValueError):
                continue
            if name in result:
                continue
            result[name] = Skill(
                name=name,
                description=description,
                body=body,
                path=str(path),
            )
        return result


def _parse_skill(content: str) -> tuple[str, str, str]:
    if not content.startswith("---\n"):
        raise ValueError("skill frontmatter missing")
    end = content.find("\n---\n", 4)
    if end < 0:
        raise ValueError("skill frontmatter is not closed")
    frontmatter = content[4:end]
    body = content[end + 6 :]
    fields: dict[str, str] = {}
    for line in frontmatter.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip().strip('"')
    name = fields.get("name", "").strip()
    description = fields.get("description", "").strip()
    if not name or not description:
        raise ValueError("skill name/description missing")
    if len(name) > 64 or len(description) > 1024 or len(body) > 100_000:
        raise ValueError("skill exceeds registry limits")
    return name, description, body
