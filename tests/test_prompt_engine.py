from app.services.prompt_engine import PromptEngine


def test_detects_coding_target_and_troubleshoot_intent() -> None:
    plan = PromptEngine().compile("Исправь баг в коде Telegram-бота")
    assert plan.target == "telegram"
    assert plan.intent == "troubleshoot"


def test_detects_codex_target() -> None:
    plan = PromptEngine().compile("Сделай prompt для Codex, чтобы изменить API")
    assert plan.target == "codex"
    assert plan.intent == "create"


def test_detects_image_generation() -> None:
    plan = PromptEngine().compile("Создай изображение футуристического города")
    assert plan.target == "image generation"
    assert plan.intent == "create"


def test_render_contains_contract_and_safety_rules() -> None:
    rendered = PromptEngine().render("Почини баг в коде")
    assert "Task contract" in rendered
    assert "Success criteria" in rendered
    assert "Do not invent missing facts" in rendered
