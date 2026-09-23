from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlanStep:
    action: str
    description: str


@dataclass(frozen=True)
class TaskPlan:
    goal: str
    steps: tuple[PlanStep, ...]
    stop_condition: str


class Planner:
    """Create a compact deterministic plan; no extra model call."""

    def build(self, query: str) -> TaskPlan:
        goal = query.strip()
        if not goal:
            return TaskPlan("", (), "No task remains.")

        return TaskPlan(
            goal=goal,
            steps=(
                PlanStep("inspect", "Inspect the relevant context and available capabilities."),
                PlanStep("execute", "Execute the smallest useful action toward the goal."),
                PlanStep("verify", "Verify the result against the requested outcome."),
            ),
            stop_condition="Stop only when the requested outcome is verified.",
        )

    def render(self, plan: TaskPlan) -> str:
        if not plan.steps:
            return "No executable plan is required."
        steps = "\n".join(
            f"{index}. {step.description}"
            for index, step in enumerate(plan.steps, start=1)
        )
        return (
            "Execution plan:\n"
            f"Goal: {plan.goal}\n"
            f"{steps}\n"
            f"Stop condition: {plan.stop_condition}"
        )
