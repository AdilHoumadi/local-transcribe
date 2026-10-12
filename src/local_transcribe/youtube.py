"""Download a single YouTube recording as MP3 into a private staging directory."""

import shutil
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .core import TranscriptionError


def is_url(source: str) -> bool:
    return source.lower().startswith(("http://", "https://"))


def canonical_url(source: str) -> str:
    parsed = urlparse(source)
    if parsed.scheme not in ("http", "https") or parsed.username or parsed.password:
        raise TranscriptionError("Supply a YouTube video URL.")
    host = (parsed.hostname or "").lower()
    if host == "youtu.be":
        video_id = parsed.path.strip("/")
    elif host in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}:
        if parsed.path == "/watch":
            video_id = parse_qs(parsed.query).get("v", [""])[0]
        elif parsed.path.startswith(("/shorts/", "/live/", "/embed/")):
            video_id = parsed.path.split("/")[2]
        else:
            video_id = ""
    else:
        video_id = ""
    import re

    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise TranscriptionError("Supply a single YouTube video URL, not a playlist or channel.")
    return f"https://www.youtube.com/watch?v={video_id}"


def download(source: str, directory: Path) -> tuple[Path, dict]:
    url = canonical_url(source)
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise TranscriptionError("YouTube MP3 extraction requires FFmpeg: brew install ffmpeg")
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadError

    options = {
        "format": "bestaudio/best",
        "outtmpl": str(directory / "audio.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "noprogress": True,
        "no_warnings": False,
        "socket_timeout": 30,
        "retries": 3,
        "fragment_retries": 3,
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}
        ],
        "match_filter": lambda info, **kwargs: (
            "Live streams are unsupported; use a completed recording."
            if info.get("is_live")
            else None
        ),
    }
    try:
        with YoutubeDL(options) as downloader:
            info = downloader.extract_info(url, download=True)
    except DownloadError as error:
        raise TranscriptionError(f"YouTube download failed: {error}") from error
    audio = directory / "audio.mp3"
    if not info or not audio.is_file() or audio.stat().st_size == 0:
        raise TranscriptionError("YouTube did not produce an MP3 file.")
    return audio, {
        "youtube_url": url,
        "youtube_id": info.get("id"),
        "title": info.get("title"),
        "duration_seconds": info.get("duration"),
    }
