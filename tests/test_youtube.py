from unittest.mock import patch

import pytest

from local_transcribe.cli import main
from local_transcribe.core import TranscriptionError, publish
from local_transcribe.youtube import canonical_url, download

URL = "https://www.youtube.com/watch?v=wzN6qq08w0U"


@pytest.mark.parametrize(
    "url",
    [
        URL + "&list=xyz",
        "https://youtu.be/wzN6qq08w0U?t=30",
        "https://youtube.com/shorts/wzN6qq08w0U",
    ],
)
def test_canonical_url(url):
    assert canonical_url(url) == URL


@pytest.mark.parametrize(
    "url",
    [
        "https://youtube.com/playlist?list=x",
        "https://evil.com/watch?v=wzN6qq08w0U",
        "file:///tmp/audio",
        "https://youtube.com/watch?v=bad",
    ],
)
def test_reject_invalid_urls(url):
    with pytest.raises(TranscriptionError):
        canonical_url(url)


def test_download_mp3_and_metadata(tmp_path):
    class Downloader:
        def __init__(self, options):
            assert options["noplaylist"]
            assert options["postprocessors"][0]["preferredcodec"] == "mp3"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def extract_info(self, url, download):
            (tmp_path / "audio.mp3").write_bytes(b"audio")
            return {"id": "wzN6qq08w0U", "title": "test", "duration": 10}

    with patch("yt_dlp.YoutubeDL", Downloader), patch("shutil.which", return_value="ffmpeg"):
        audio, metadata = download(URL, tmp_path)
    assert audio.read_bytes() == b"audio"
    assert metadata["youtube_url"] == URL


def test_keep_audio_published_with_bundle(tmp_path):
    audio = tmp_path / "source.mp3"
    audio.write_bytes(b"mp3")
    publish(tmp_path / "job", {"transcript.txt": "hello"}, audio=audio)
    assert (tmp_path / "job/audio.mp3").read_bytes() == b"mp3"


def test_url_workflow_cleans_temporary_files(tmp_path):
    downloaded = []

    def fake_download(url, directory):
        audio = directory / "audio.mp3"
        audio.write_bytes(b"mp3")
        downloaded.append(audio)
        return audio, {"youtube_url": URL}

    def fake_transcribe(audio, destination, **kwargs):
        assert audio.exists()
        assert kwargs["keep_audio"]
        assert kwargs["source_metadata"]["youtube_url"] == URL
        return destination

    with (
        patch("local_transcribe.cli.platform.system", return_value="Darwin"),
        patch("local_transcribe.cli.platform.machine", return_value="arm64"),
        patch("local_transcribe.cli.download", side_effect=fake_download),
        patch("local_transcribe.cli.transcribe", side_effect=fake_transcribe),
    ):
        assert main(["transcribe", URL, "--keep-audio", "--output-dir", str(tmp_path)]) == 0
    assert not downloaded[0].exists()


def test_offline_url_rejected_before_download():
    with (
        patch("local_transcribe.cli.platform.system", return_value="Darwin"),
        patch("local_transcribe.cli.platform.machine", return_value="arm64"),
        patch("local_transcribe.cli.download") as downloader,
    ):
        with pytest.raises(SystemExit) as error:
            main(["transcribe", URL, "--offline"])
        assert error.value.code == 2
        downloader.assert_not_called()
