from app.handlers.chat import _audio_filename


class Obj:
    video_note = None
    audio = None


def test_audio_filename_for_voice() -> None:
    message = Obj()
    assert _audio_filename(message) == "voice.ogg"


def test_audio_filename_for_video_note() -> None:
    message = Obj()
    message.video_note = object()
    assert _audio_filename(message) == "video_note.mp4"


def test_audio_filename_for_audio_without_extension() -> None:
    message = Obj()
    message.audio = type("Audio", (), {"file_name": "recording"})()
    assert _audio_filename(message) == "recording.mp3"


def test_audio_filename_preserves_extension() -> None:
    message = Obj()
    message.audio = type("Audio", (), {"file_name": "recording.M4A"})()
    assert _audio_filename(message) == "recording.M4A"
