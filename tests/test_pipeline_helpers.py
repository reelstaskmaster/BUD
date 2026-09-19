from app.services.pipeline import _message_text_for_llm


class Obj:
    def __init__(self, role="user", content="", media_type=None):
        self.role = role
        self.content = content
        self.media_type = media_type


def test_voice_text_is_explicitly_marked_for_llm() -> None:
    result = _message_text_for_llm(Obj(content="hello", media_type="voice"))
    assert result.startswith("The user sent a voice/audio message.")
    assert result.endswith("hello")


def test_non_voice_text_is_unchanged() -> None:
    message = Obj(content="hello", media_type="text")
    assert _message_text_for_llm(message) == "hello"


def test_empty_content_is_safe() -> None:
    assert _message_text_for_llm(Obj(content=None)) == ""
