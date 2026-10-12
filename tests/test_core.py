import json
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from local_transcribe.core import (
    TranscriptionError,
    publish,
    render_outputs,
    timestamp,
    transcribe,
    validate_result,
)


@pytest.fixture
def result():
    return {
        "text": " Hello world. ",
        "language": "en",
        "segments": [
            {"start": 0.0, "end": 1.25, "text": " Hello\n\nworld. "},
            {"start": 3661.001, "end": 3662.0, "text": " Goodbye. "},
        ],
    }


def test_formats_and_round_trip(result):
    outputs = render_outputs(result, {"source_name": "sample.mp3"})
    assert outputs["transcript.txt"] == "Hello world.\n"
    assert "[01:01:01.001 - 01:01:02.000] Goodbye." in outputs["transcript_timestamps.txt"]
    assert "1\n00:00:00,000 --> 00:00:01,250\nHello world.\n\n" in outputs["transcript.srt"]
    assert outputs["transcript.vtt"].startswith("WEBVTT\n\n00:00:00.000 -->")
    assert json.loads(outputs["transcript.json"])["transcription"] == result


@pytest.mark.parametrize("bad", [-1, float("nan"), float("inf")])
def test_invalid_timestamp(bad):
    with pytest.raises(TranscriptionError):
        timestamp(bad)


def test_rounding_carries():
    assert timestamp(59.9996) == "00:01:00.000"


@pytest.mark.parametrize(
    "segments",
    [None, [{"start": True, "end": 2, "text": "x"}], [{"start": -1, "end": 2, "text": "x"}]],
)
def test_invalid_results(segments):
    with pytest.raises(TranscriptionError):
        validate_result({"text": "x", "segments": segments})


def test_publication_refuses_existing_job(tmp_path):
    job = tmp_path / "job"
    publish(job, {"transcript.txt": "original"})
    with pytest.raises(TranscriptionError, match="already exists"):
        publish(job, {"transcript.txt": "replacement"})
    assert (job / "transcript.txt").read_text() == "original"
    assert not list(tmp_path.glob(".*"))


def test_failure_leaves_no_partial_job(tmp_path):
    with patch("local_transcribe.core.os.fsync", side_effect=OSError("disk full")):
        with pytest.raises(OSError, match="disk full"):
            publish(tmp_path / "job", {"transcript.txt": "content"})
    assert list(tmp_path.iterdir()) == []


def test_concurrent_lock_is_preserved(tmp_path):
    lock = tmp_path / ".job.lock"
    lock.touch()
    with pytest.raises(TranscriptionError, match="locked"):
        publish(tmp_path / "job", {"transcript.txt": "x"})
    assert lock.exists()


def test_engine_options_and_metadata(tmp_path, result):
    audio = tmp_path / "input.mp3"
    audio.write_bytes(b"sample")
    calls = []

    def fake_transcribe(source, **kwargs):
        calls.append((source, kwargs))
        return result

    with patch.dict(sys.modules, {"mlx_whisper": SimpleNamespace(transcribe=fake_transcribe)}):
        with patch("local_transcribe.core.version", return_value="0.4.3"):
            with patch("local_transcribe.core.shutil.which", return_value="ffmpeg"):
                transcribe(audio, tmp_path / "job", language="en", word_timestamps=True)
    assert calls[0][1]["task"] == "transcribe"
    assert calls[0][1]["word_timestamps"] is True
    metadata = json.loads((tmp_path / "job/transcript.json").read_text())["metadata"]
    assert len(metadata["source_sha256"]) == 64
    assert metadata["source_name"] == "input.mp3"


def test_changed_input_is_rejected(tmp_path, result):
    audio = tmp_path / "input.mp3"
    audio.write_bytes(b"before")

    def fake_transcribe(*args, **kwargs):
        audio.write_bytes(b"after")
        return result

    with patch.dict(sys.modules, {"mlx_whisper": SimpleNamespace(transcribe=fake_transcribe)}):
        with patch("local_transcribe.core.shutil.which", return_value="ffmpeg"):
            with pytest.raises(TranscriptionError, match="changed"):
                transcribe(audio, tmp_path / "job")
    assert not (tmp_path / "job").exists()


def test_irregular_engine_timestamps_preserve_transcript():
    result = {
        "text": "first second third",
        "segments": [
            {"start": 10.0, "end": 11.0, "text": "first"},
            {"start": 9.0, "end": 9.5, "text": "second"},
            {"start": 12.0, "end": 11.0, "text": "third"},
        ],
    }
    outputs = render_outputs(result, {})
    assert outputs["transcript.txt"] == "first second third\n"
    stored = json.loads(outputs["transcript.json"])
    assert stored["transcription"] == result
    assert len(stored["metadata"]["subtitle_timing_adjustments"]) == 2
    assert "00:00:10,000 --> 00:00:10,001" in outputs["transcript.srt"]
    assert "00:00:12.000 --> 00:00:12.001" in outputs["transcript.vtt"]
