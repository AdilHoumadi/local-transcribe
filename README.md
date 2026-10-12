# local-transcribe

![Video and audio becoming local transcripts](docs/assets/readme-banner.png)

**Turn recordings into readable text. Keep transcription on your Mac.**

YouTube URLs · Local audio & video · Apple Silicon · TXT / SRT / VTT / JSON

Local audio and video transcription on Apple Silicon using MLX Whisper. No audio is
sent to a transcription service. The first run downloads model weights from Hugging
Face; subsequent runs reuse the cache. Use `--offline` to prevent model downloads.

## Quick start

Requires an Apple Silicon Mac, native ARM64 Python 3.11–3.13, and Metal GPU access.
Run these commands from macOS Terminal inside the repository:

```bash
brew install ffmpeg uv deno
uv sync --locked
uv run --locked local-transcribe doctor

# Download YouTube audio, transcribe it, and keep the MP3.
uv run --locked local-transcribe transcribe "https://www.youtube.com/watch?v=wzN6qq08w0U" --keep-audio

# Or transcribe a file already on your Mac.
uv run --locked local-transcribe transcribe /path/to/video.mp3
```

Results appear in a separate job folder under `transcripts/`. Existing job folders
are never overwritten. The first run downloads model weights; later runs use the cache.
`uv.lock` pins the application and development dependencies. Installation needs network
access; do not use sudo or install dependencies into the system Python.

## How it works

```text
YouTube URL → yt-dlp → MP3 ─┐
                          ├→ MLX Whisper on your Mac → Text + subtitles + JSON
Local audio or video ─────┘
```

## What you get

| File | Contents |
| --- | --- |
| `transcript.txt` | Complete transcript |
| `transcript_timestamps.txt` | Original segment timestamps and text |
| `transcript.srt` | SubRip subtitles |
| `transcript.vtt` | WebVTT subtitles |
| `transcript.json` | Full engine result, source details, input hash, versions and run times |
| `audio.mp3` | Downloaded YouTube audio, when `--keep-audio` is used |

## YouTube → MP3 → transcript

```bash
uv run --locked local-transcribe transcribe "https://www.youtube.com/watch?v=wzN6qq08w0U" --keep-audio
```

Downloads one video's best available audio with yt-dlp, converts it to MP3 with
FFmpeg, and transcribes it locally. `--keep-audio` saves `audio.mp3` in the completed
job directory. Otherwise downloaded audio is temporary and removed after the job,
including on normal failures. YouTube title, ID, URL and duration are saved in JSON.
Mixed URL/local-file batches are supported. Playlists/channels and active live streams
are excluded; a watch URL with a playlist parameter still downloads only that video.
URL inputs require network access and cannot be combined with `--offline`.

Deno supplies the JavaScript runtime used by current YouTube extractors; the locked
`yt-dlp[default]` dependency supplies its supporting components. Private/restricted
videos that need authentication are not supported by this CLI. YouTube changes can
break downloads: update with `uv lock --upgrade-package yt-dlp --upgrade-package yt-dlp-ejs`,
then `uv sync --locked` and rerun checks. Download errors have bounded retries;
no transcript job is published if download or inference fails.

## Common commands

```bash
# Stable job name; refuses an existing output directory.
uv run --locked local-transcribe transcribe video.mp3 --job-name interview --output-dir transcripts

# Process multiple recordings sequentially; continue after individual failures.
uv run --locked local-transcribe transcribe first.mp3 second.m4a meeting.mp4

# Specify language and retain word timestamps in JSON.
uv run --locked local-transcribe transcribe video.mp3 --language en --word-timestamps

# Use a cached model without network downloads.
uv run --locked local-transcribe transcribe video.mp3 --offline

# Use an existing local MLX model directory.
uv run --locked local-transcribe transcribe video.mp3 --model /path/to/mlx-model --offline
```

The default model is `mlx-community/whisper-large-v3-turbo`. Model downloads use the
Hugging Face cache and may consume several GB. An optional `HF_TOKEN` improves download
rate limits; never commit tokens. Exact model reproducibility requires a local model
snapshot: a repository identifier alone can change upstream. FFmpeg accepts common
audio/video formats; invalid, encrypted, or unsupported inputs fail with a nonzero exit.

Successful output-directory paths go to stdout. Progress and errors go to stderr.
Exit status is 0 for success, 1 if any job fails, 2 for invalid arguments, and 130 for
an interrupted transcription. Batch processing is sequential to avoid GPU contention.

## Reliability and limitations

Output files are staged together and published by directory rename on the same
filesystem. Existing jobs are never deliberately overwritten. An exclusive publication
lock prevents cooperating processes from publishing the same job simultaneously.
Input hashing detects a file that changed during transcription. Failed jobs do not
publish partial bundles; completed batch jobs remain available after later failures.

A hard process kill can leave `.transcribe-*` staging folders or a `.JOB.lock` file in
the output root. After verifying no process is publishing that job, remove those stale
items and rerun. Publication is atomic on ordinary local filesystems; power-loss
durability and unusual network filesystems are not guaranteed. Keep inputs immutable
while processing. Default output directories are private (mode 0700); access is
controlled by the local filesystem.

Whisper can mishear speech and hallucinate during silence. Review critical text and
subtitle timing against the audio. This project does not provide speaker diarization,
translation, real-time streaming, inference retries, or resumable segments. Long files
are handled by Whisper internally, and working memory depends on recording duration.
Word timestamps are stored in JSON; subtitles remain segment-level. Whisper can
return backward or inverted segment times. These do not discard a completed
transcript: TXT and JSON retain the original text order and timing. Subtitle starts
are clamped to nondecreasing times and ends to at least one millisecond after their
start. Adjusted cues are listed in JSON metadata as `subtitle_timing_adjustments`;
review them against the recording.

You can open the resulting text in LM Studio for summaries or analysis.
LM Studio is optional; MLX Whisper handles transcription.
Transcript text is untrusted input: avoid giving it authority to execute tools.

## Development and verification

```bash
uv sync --locked
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pytest
uv run --locked python -m build
```

Tests use a fake transcription engine to check publication failures, input changes,
formatting, batch failures, and command behavior without downloading models or requiring
GPU access. CI runs these tests on Linux across Python 3.11–3.13. It does not validate
Metal inference. Before releasing, perform a real-audio acceptance test on an Apple
Silicon Mac and review the transcript and subtitles. See `VALIDATION.md` for this build.

The packaged CLI also supports `python -m local_transcribe`. The Python orchestration
API is in `local_transcribe.core`; the CLI is the supported interface for this version.

Engine documentation: https://github.com/ml-explore/mlx-examples/tree/main/whisper

## Troubleshooting

| Symptom | Next step |
| --- | --- |
| `No Metal device available` | Run in macOS Terminal with native ARM64 Python; restricted or headless sessions may lack GPU access. |
| FFmpeg missing | Run `brew install ffmpeg`, then rerun `doctor`. |
| YouTube extraction fails | Check the video is publicly accessible, install Deno, and update yt-dlp as described above. |
| Output already exists | Choose a new `--job-name`, or omit it for a unique job folder. |
| Model unavailable offline | Run once online to cache weights, or supply a local MLX model directory. |
| Subtitle timing adjustments | Inspect `subtitle_timing_adjustments` in JSON and review affected cues against the recording. |

## Further reading

- [Validation record](VALIDATION.md)
- [Changelog](CHANGELOG.md)
- [MLX Whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper)
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)
