"""Validated transcription results and transactional output publication."""

import hashlib
import json
import math
import os
import shutil
import tempfile
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

from . import __version__

DEFAULT_MODEL = "mlx-community/whisper-large-v3-turbo"


class TranscriptionError(Exception):
    """An actionable failure that can be displayed without a traceback."""


def timestamp(seconds: float, separator: str = ".") -> str:
    if not math.isfinite(seconds) or seconds < 0:
        raise TranscriptionError("Timestamps must be finite and non-negative.")
    hours, rest = divmod(round(seconds * 1000), 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    whole_seconds, milliseconds = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}{separator}{milliseconds:03d}"


def validate_result(result: Any) -> dict:
    if not isinstance(result, dict) or not isinstance(result.get("text"), str):
        raise TranscriptionError("Whisper returned an invalid transcript.")
    if not isinstance(result.get("segments"), list):
        raise TranscriptionError("Whisper returned invalid segments.")
    for segment in result["segments"]:
        if not isinstance(segment, dict) or not isinstance(segment.get("text"), str):
            raise TranscriptionError("Whisper returned an invalid segment.")
        for key in ("start", "end"):
            value = segment.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TranscriptionError("Whisper returned a non-numeric timestamp.")
            timestamp(value)
    return result


def render_outputs(result: dict, metadata: dict) -> dict[str, str]:
    validate_result(result)
    segments = result["segments"]
    timed, srt, vtt = [], [], ["WEBVTT\n\n"]
    cue = 0
    previous_cue_start = 0.0
    timing_adjustments = []
    for segment in segments:
        text = segment["text"].strip()
        timed.append(f"[{timestamp(segment['start'])} - {timestamp(segment['end'])}] {text}\n")
        if not text:
            continue
        cue += 1
        # Keep engine text order and raw timing in TXT/JSON; repair subtitle cues only.
        start_ms = max(round(segment["start"] * 1000), round(previous_cue_start * 1000))
        end_ms = max(round(segment["end"] * 1000), start_ms + 1)
        start, end = start_ms / 1000, end_ms / 1000
        if start_ms != round(segment["start"] * 1000) or end_ms != round(segment["end"] * 1000):
            timing_adjustments.append({"cue": cue, "start": start, "end": end})
        previous_cue_start = start
        # A blank line inside a cue would terminate it prematurely.
        subtitle = " ".join(text.split())
        srt.append(f"{cue}\n{timestamp(start, ',')} --> {timestamp(end, ',')}\n{subtitle}\n\n")
        vtt.append(f"{timestamp(start)} --> {timestamp(end)}\n{subtitle}\n\n")
    metadata = {**metadata, "subtitle_timing_adjustments": timing_adjustments}
    try:
        structured = (
            json.dumps(
                {"schema_version": 1, "metadata": metadata, "transcription": result},
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
            + "\n"
        )
    except (TypeError, ValueError) as error:
        raise TranscriptionError(f"Result cannot be serialized: {error}") from error
    return {
        "transcript.txt": result["text"].strip() + "\n",
        "transcript_timestamps.txt": "".join(timed),
        "transcript.srt": "".join(srt),
        "transcript.vtt": "".join(vtt),
        "transcript.json": structured,
    }


def publish(destination: Path, outputs: dict[str, str], *, audio: Path | None = None) -> None:
    """Reserve a job, then atomically rename its complete bundle into place.

    Cooperating processes use an exclusive lock. Existing jobs are never replaced.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    lock = destination.parent / f".{destination.name}.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise TranscriptionError(f"Output is locked by another run: {lock}") from error
    staging = None
    try:
        os.close(descriptor)
        if destination.exists() or destination.is_symlink():
            raise TranscriptionError(f"Output already exists: {destination}")
        staging = Path(tempfile.mkdtemp(prefix=".transcribe-", dir=destination.parent))
        for name, content in outputs.items():
            with (staging / name).open("w", encoding="utf-8") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        if audio is not None:
            shutil.copyfile(audio, staging / "audio.mp3")
        staging.rename(destination)
    finally:
        if staging is not None and staging.exists():
            shutil.rmtree(staging)
        lock.unlink(missing_ok=True)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def transcribe(
    audio: Path,
    destination: Path,
    *,
    model: str = DEFAULT_MODEL,
    language: str | None = None,
    word_timestamps: bool = False,
    offline: bool = False,
    source_metadata: dict | None = None,
    keep_audio: bool = False,
) -> Path:
    if not audio.is_file():
        raise TranscriptionError(f"Audio file not found: {audio}")
    if destination.exists() or destination.is_symlink():
        raise TranscriptionError(f"Output already exists: {destination}")
    if not shutil.which("ffmpeg"):
        raise TranscriptionError("FFmpeg is missing. Install it with: brew install ffmpeg")
    if offline:
        os.environ["HF_HUB_OFFLINE"] = "1"
    # Import only after offline policy is set; --help and tests do not initialize Metal.
    try:
        import mlx_whisper
    except ImportError as error:
        raise TranscriptionError(
            "Cannot load MLX Whisper. Install on Apple Silicon with `uv sync --locked`; "
            "if Metal is unavailable, run in your Mac's Terminal. " + str(error)
        ) from error
    before = sha256(audio)
    started = datetime.now(UTC)
    try:
        result = mlx_whisper.transcribe(
            str(audio),
            path_or_hf_repo=model,
            language=language,
            task="transcribe",
            word_timestamps=word_timestamps,
            verbose=False,
        )
    except Exception as error:
        raise TranscriptionError(f"Whisper failed for {audio.name}: {error}") from error
    if before != sha256(audio):
        raise TranscriptionError(
            "The input file changed during transcription; output was discarded."
        )
    metadata = {
        "source_name": audio.name,
        "source_sha256": before,
        "model": model,
        "requested_language": language,
        "word_timestamps": word_timestamps,
        "started_at": started.isoformat(),
        "completed_at": datetime.now(UTC).isoformat(),
        "tool_version": __version__,
        "mlx_whisper_version": version("mlx-whisper"),
    }
    if source_metadata:
        metadata["source"] = source_metadata
    publish(destination, render_outputs(result, metadata), audio=audio if keep_audio else None)
    return destination
