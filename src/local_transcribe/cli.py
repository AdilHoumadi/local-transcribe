"""Command-line interface for local transcription."""

import argparse
import json
import platform
import re
import shutil
import sys
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

from . import __version__
from .core import DEFAULT_MODEL, TranscriptionError, transcribe
from .youtube import canonical_url, download, is_url


def doctor() -> int:
    checks = {
        "apple_silicon": platform.system() == "Darwin" and platform.machine() == "arm64",
        "ffmpeg": bool(shutil.which("ffmpeg")),
    }
    details = {}
    try:
        import mlx.core as mx
        import mlx_whisper  # noqa: F401

        details["device"] = str(mx.default_device())
        checks["mlx_whisper"] = True
    except Exception as error:
        checks["mlx_whisper"] = False
        details["mlx_error"] = str(error)
    print(json.dumps({"checks": checks, "details": details}, indent=2))
    return 0 if all(checks.values()) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local Apple Silicon audio transcription")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="Check Apple Silicon, FFmpeg, and MLX/Metal availability")
    run = commands.add_parser("transcribe", help="Transcribe one or more audio/video files")
    run.add_argument("audio", nargs="+", help="Local files or single YouTube video URLs")
    run.add_argument("--keep-audio", action="store_true", help="Save downloaded MP3 with outputs")
    run.add_argument("--output-dir", type=Path, default=Path("transcripts"), help="Output root")
    run.add_argument("--job-name", help="Exact output directory name; single input only")
    run.add_argument("--model", default=DEFAULT_MODEL, help="Hugging Face model ID or local folder")
    run.add_argument("--language", help="Whisper language code/name; default: auto-detect")
    run.add_argument("--word-timestamps", action="store_true")
    run.add_argument("--offline", action="store_true", help="Require cached/local model weights")
    args = parser.parse_args(argv)
    if args.command == "doctor":
        return doctor()
    if args.job_name and (
        len(args.audio) != 1 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}", args.job_name)
    ):
        parser.error(
            "--job-name requires one input and 1–100 letters, digits, underscores or hyphens"
        )
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        print(
            "error: Transcription requires macOS and an Apple Silicon Python installation.",
            file=sys.stderr,
        )
        return 1
    if args.offline and any(is_url(source) for source in args.audio):
        parser.error("--offline cannot download YouTube URLs; use a local file")
    failures = 0
    for source in args.audio:
        audio = Path(source).expanduser().resolve() if not is_url(source) else None
        slug = (
            re.sub(r"[^A-Za-z0-9_-]+", "-", (audio.stem if audio else "youtube")).strip("-")[:60]
            or "audio"
        )
        name = args.job_name or (f"{slug}-{datetime.now(UTC):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:8]}")
        destination = args.output_dir.expanduser().absolute() / name
        try:
            if destination.exists():
                raise TranscriptionError(f"Output already exists: {destination}")
            if audio is None:
                canonical_url(source)
                with tempfile.TemporaryDirectory(prefix="local-transcribe-") as temporary:
                    print("Downloading YouTube audio…", file=sys.stderr, flush=True)
                    downloaded, metadata = download(source, Path(temporary))
                    completed = transcribe(
                        downloaded,
                        destination,
                        model=args.model,
                        language=args.language,
                        word_timestamps=args.word_timestamps,
                        source_metadata=metadata,
                        keep_audio=args.keep_audio,
                    )
            else:
                print(f"Transcribing {audio.name}…", file=sys.stderr, flush=True)
                completed = transcribe(
                    audio,
                    destination,
                    model=args.model,
                    language=args.language,
                    word_timestamps=args.word_timestamps,
                    offline=args.offline,
                )
            print(completed, flush=True)
        except (TranscriptionError, OSError) as error:
            failures += 1
            print(f"error: {error}", file=sys.stderr)
        except KeyboardInterrupt:
            print("Interrupted. Completed jobs remain available.", file=sys.stderr)
            return 130
    return 1 if failures else 0
