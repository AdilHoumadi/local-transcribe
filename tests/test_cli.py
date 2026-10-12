from unittest.mock import patch

import pytest

from local_transcribe.cli import main
from local_transcribe.core import TranscriptionError


def test_help_does_not_load_mlx():
    with pytest.raises(SystemExit) as error:
        main(["--help"])
    assert error.value.code == 0


def test_reject_path_traversal():
    with pytest.raises(SystemExit) as error:
        main(["transcribe", "audio.mp3", "--job-name", "../bad"])
    assert error.value.code == 2


def test_batch_continues_after_failure(tmp_path, capsys):
    def fake(audio, destination, **kwargs):
        if audio.name == "bad.mp3":
            raise TranscriptionError("bad audio")
        return destination

    with patch("local_transcribe.cli.platform.system", return_value="Darwin"):
        with patch("local_transcribe.cli.platform.machine", return_value="arm64"):
            with patch("local_transcribe.cli.transcribe", side_effect=fake) as engine:
                code = main(["transcribe", "bad.mp3", "good.mp3", "--output-dir", str(tmp_path)])
    assert code == 1
    assert engine.call_count == 2
    assert "good-" in capsys.readouterr().out


def test_interrupt_exit_code():
    with patch("local_transcribe.cli.platform.system", return_value="Darwin"):
        with patch("local_transcribe.cli.platform.machine", return_value="arm64"):
            with patch("local_transcribe.cli.transcribe", side_effect=KeyboardInterrupt):
                assert main(["transcribe", "audio.mp3"]) == 130
