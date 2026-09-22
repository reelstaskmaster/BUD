import pytest
from pydantic import ValidationError

from app.config import Settings


def test_default_runtime_bounds() -> None:
    settings = Settings(telegram_bot_token="token", openai_api_key="key")
    assert settings.recent_messages == 16
    assert settings.coalesce_debounce_s == 0.7


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("recent_messages", 0),
        ("fact_top_k", 0),
        ("summarize_every", 0),
        ("coalesce_debounce_ms", -1),
        ("embedding_dims", 0),
    ],
)
def test_rejects_invalid_runtime_bounds(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        Settings(
            telegram_bot_token="token",
            openai_api_key="key",
            **{field: value},
        )


def test_rejects_excessive_debounce() -> None:
    with pytest.raises(ValidationError):
        Settings(
            telegram_bot_token="token",
            openai_api_key="key",
            coalesce_debounce_ms=60_001,
        )


def test_freellmapi_defaults() -> None:
    settings = Settings(telegram_bot_token="token")
    assert settings.freellmapi_base_url == "http://localhost:3001/v1"
    assert settings.freellmapi_chat_model == "auto"
    assert "freellmapi" in settings.ai_providers
