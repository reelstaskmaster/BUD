from pathlib import Path

from app.services.skill_registry import SkillRegistry


def test_registry_loads_bundled_skills():
    registry = SkillRegistry(Path(__file__).parents[1] / "skills")
    names = {skill.name for skill in registry.list()}
    assert "plan" in names
    assert "systematic-debugging" in names
    assert "requesting-code-review" in names
    assert "hermes-registry-security-gate" in names


def test_registry_limits_selected_skills():
    registry = SkillRegistry(Path(__file__).parents[1] / "skills")
    selected = registry.matching("debugging review plan security", limit=2)
    assert len(selected) <= 2
