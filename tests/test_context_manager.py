from app.services.context_manager import ContextManager
from app.services.openai_client import OpenAIInputMessage


def test_keeps_newest_messages_within_budget() -> None:
    messages = [
        OpenAIInputMessage(role="user", text="old " * 2000),
        OpenAIInputMessage(role="assistant", text="middle " * 2000),
        OpenAIInputMessage(role="user", text="latest"),
    ]
    result = ContextManager(max_chars=3000).trim_messages(messages)
    assert result[-1].text == "latest"
    assert len(result) < len(messages)


def test_keeps_instructions_unchanged_when_under_budget() -> None:
    text = "short instructions"
    assert ContextManager(max_chars=2000).trim_instructions(text) == text


def test_trims_large_instructions() -> None:
    result = ContextManager(max_chars=2000).trim_instructions("x" * 2500)
    assert len(result) <= 2000
    assert result.endswith("[Context trimmed]")
