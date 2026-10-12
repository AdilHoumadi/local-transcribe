# Validation record

Validated on 2026-10-12 in the local development environment.

- Full isolated installation with `uv sync --locked` succeeded on macOS ARM64,
  Python 3.12.14. A dependency lockfile is included.
- 29 automated tests pass. They cover formatting, timestamp validation, JSON output,
  output collisions, publication locks, write failures, changed inputs, batch error
  continuation, argument validation, and interruption.
- Ruff lint and formatting checks pass.
- Wheel and source distribution build successfully. Contents were inspected to
  confirm no audio, transcripts, virtual environment, or caches were packaged.
- Installed CLI help works without loading Metal.
- Installed `doctor` correctly identifies Apple Silicon and FFmpeg and reports the
  session's inaccessible Metal device.
- An actual transcription attempt of `video.mp3` with `--offline` exits cleanly with
  an actionable Metal error and does not create a partial output job.

## Acceptance check still required

The original standalone script successfully transcribed the user's 18-minute audio
in macOS Terminal. The packaged YouTube command completed inference in macOS Terminal, but its
original timing validator rejected the output. A regression fix now preserves irregular
segment times and normalizes subtitle cues; the corrected complete workflow still
needs a real-audio rerun before claiming fully validated production readiness. The sandbox cannot
access Metal. Run from macOS Terminal:

```bash
cd /path/to/local-transcribe
uv run --locked local-transcribe doctor
uv run --locked local-transcribe transcribe /path/to/video.mp3 --offline --job-name acceptance
```

Check that all five files appear under `transcripts/acceptance/`, listen against the
text at several points, and load SRT/VTT in a subtitle-capable player. Rerunning the
same job name must refuse to overwrite it. CI is configured but has not run remotely;
this repository intentionally remains local.

## YouTube workflow (0.2.0)

The real video https://www.youtube.com/watch?v=wzN6qq08w0U was downloaded
using the project's Python download function and converted to MP3 with FFmpeg.
YouTube reported title “ADRs: The Why and How by Venkat Subramaniam” and
duration 3000 seconds. The downloaded MP3 is an ignored local validation artifact
under `.cache/youtube-validation/`; it is not shipped or committed.

The added tests cover URL normalization, rejection of playlists/non-YouTube URLs,
MP3 downloader configuration, retained audio publication, temporary-file cleanup,
and offline URL rejection. Actual inference remains blocked by Metal access in
this session. For the complete URL acceptance test, run in macOS Terminal:

```bash
uv run --locked local-transcribe transcribe "https://www.youtube.com/watch?v=wzN6qq08w0U" --keep-audio
```
