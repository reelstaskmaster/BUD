# BUD Agent Development Contract

## Mission
Develop BUD as a reliable Telegram AI assistant. Preserve existing behavior unless a task explicitly changes it.

## Roles

### Developer / Architect
- Inspect the existing code before changing it.
- Implement the smallest coherent change that satisfies the task.
- Add or update tests for behavior that can be tested.
- Run the relevant test suite and record failures.
- Never commit secrets, tokens, or local .env files.
- Do not declare a task complete until Reviewer criteria are satisfied.

### Reviewer / QA
- Review the actual diff, not only the task description.
- Check correctness, regressions, error handling, security, configuration, database migrations, and tests.
- Treat failing tests and unhandled startup/configuration errors as blockers.
- Return concrete findings with file paths and requested fixes.
- Approve only when no blocking issues remain.

## Required loop
1. Create/accept a task.
2. Developer inspects the relevant code.
3. Developer implements the change.
4. Tests and static checks run.
5. Reviewer inspects the diff and test results.
6. If blockers exist, Developer fixes them and the review repeats.
7. Only after approval may the change be merged/deployed.

## Safety
- Keep production credentials out of Git.
- Do not silently alter database schemas; migrations are required.
- Do not change model names, Telegram behavior, or deployment configuration without documenting the reason.
- Prefer reversible changes and small commits.

## Current project facts
- Telegram framework: aiogram 3.x.
- Python requirement in pyproject.toml: >=3.12.
- Persistence: SQLAlchemy async + PostgreSQL/pgvector.
- Configuration: pydantic-settings from .env/environment.
- Entry point: app/main.py.
