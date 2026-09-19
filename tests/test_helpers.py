from aiogram.types import Message

from app.handlers.chat import _audio_filename
from app.services.openai_client import OpenAIInputMessage, _audio_content_type, _to_input_item
from app.services.pipeline import _message_text_for_llm


def test_audio_content_types() -> None:
    assert _audio_content_type("voice.ogg") == "audio/ogg"
    assert _audio_content_type("recording.mp3") == "audio/mpeg"
    assert _audio_content_type("clip.m4a") == "audio/mp4"
    assert _audio_content_type("clip.wav") == "audio/wav"
    assert _audio_content_type("clip.webm") == "audio/webm"


def test_audio_content_type_is_case_insensitive() -> None:
    assert _audio_content_type("VOICE.MP3") == "audio/mpeg"


def test_message_text_for_voice_explains_transcription() -> None:
    message = type(
        "MessageStub",
        (),
        {"content": "Привет", "role": "user", "media_type": "voice"},
    )()
    result = _message_text_for_llm(message)
    assert "Привет" in result
    assert "transcription" in result.lower()


def test_message_text_for_normal_message_is_unchanged() -> None:
    message = type(
        "MessageStub",
        (),
        {"content": "Hello", "role": "user", "media_type": "text"},
    )()
    assert _message_text_for_llm(message) == "Hello"


def test_to_input_item_encodes_image_as_data_url() -> None:
    result = _to_input_item(
        OpenAIInputMessage(role="user", text="Что здесь?", image_bytes=b"abc")
    )
    assert result["role"] == "user"
    assert result["content"][0]["text"] == "Что здесь?"
    assert result["content"][1]["type"] == "input_image"
    assert result["content"][1]["image_url"].startswith("data:image/jpeg;base64,")


def test_to_input_item_keeps_assistant_message_text() -> None:
    result = _to_input_item(OpenAIInputMessage(role="assistant", text="Ответ"))
    assert result == {"role": "assistant", "content": "Ответ"}
