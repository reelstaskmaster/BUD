from app.services.planner import Planner


def test_builds_compact_verified_plan() -> None:
    plan = Planner().build("fix the bug")
    assert plan.goal == "fix the bug"
    assert [step.action for step in plan.steps] == ["inspect", "execute", "verify"]
    assert "verified" in plan.stop_condition


def test_empty_query_has_no_plan() -> None:
    plan = Planner().build("")
    assert plan.steps == ()


def test_render_contains_goal_and_steps() -> None:
    text = Planner().render(Planner().build("review code"))
    assert "Goal: review code" in text
    assert "1." in text
    assert "Stop condition:" in text
