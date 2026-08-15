from unittest.mock import MagicMock, patch

import subprocess

from installer.shell import (
    clear_stream_sink,
    get_stream_sink,
    run_ok,
    run_privileged,
    run_streaming,
    set_stream_sink,
)


def test_run_ok_true_on_zero_exit():

    with patch(
        "installer.shell.subprocess.run",
        return_value=MagicMock(returncode=0)
    ):

        assert run_ok(["docker", "info"]) is True


def test_run_ok_false_on_nonzero_exit():

    with patch(
        "installer.shell.subprocess.run",
        return_value=MagicMock(returncode=1)
    ):

        assert run_ok(["docker", "info"]) is False


def test_run_ok_false_when_command_missing():

    with patch(
        "installer.shell.subprocess.run",
        side_effect=OSError("no such file")
    ):

        assert run_ok(["nonexistent-tool"]) is False


def test_run_privileged_prefixes_sudo_when_not_root():

    with patch("installer.shell.os.geteuid", return_value=1000), patch(
        "installer.shell.shutil.which", return_value="/usr/bin/sudo"
    ), patch(
        "installer.shell.subprocess.run",
        return_value=MagicMock(returncode=0)
    ) as mock_run:

        result = run_privileged(["usermod", "-aG", "docker", "sentinel"])

    assert result == {"success": True, "error": None}
    mock_run.assert_called_once_with(
        ["sudo", "usermod", "-aG", "docker", "sentinel"]
    )


def test_run_privileged_skips_sudo_when_already_root():

    with patch("installer.shell.os.geteuid", return_value=0), patch(
        "installer.shell.subprocess.run",
        return_value=MagicMock(returncode=0)
    ) as mock_run:

        result = run_privileged(["systemctl", "enable", "--now", "docker"])

    assert result == {"success": True, "error": None}
    mock_run.assert_called_once_with(
        ["systemctl", "enable", "--now", "docker"]
    )


def test_run_privileged_fails_cleanly_without_sudo_or_root():

    with patch("installer.shell.os.geteuid", return_value=1000), patch(
        "installer.shell.shutil.which", return_value=None
    ):

        result = run_privileged(["usermod", "-aG", "docker", "sentinel"])

    assert result == {
        "success": False,
        "error": "sudo not found and not running as root"
    }


def test_run_privileged_reports_nonzero_exit_code():

    with patch("installer.shell.os.geteuid", return_value=0), patch(
        "installer.shell.subprocess.run",
        return_value=MagicMock(returncode=1)
    ):

        result = run_privileged(["pacman", "-Sy", "--noconfirm", "docker"])

    assert result == {"success": False, "error": "exit code 1"}


def test_run_privileged_streams_through_sink_when_set():

    with patch("installer.shell.os.geteuid", return_value=1000), patch(
        "installer.shell.shutil.which", return_value="/usr/bin/sudo"
    ), patch(
        "installer.shell.run_streaming", return_value=0
    ) as mock_streaming:

        set_stream_sink("sink")
        try:
            result = run_privileged(["usermod", "-aG", "docker", "sentinel"])
        finally:
            clear_stream_sink()

    assert result == {"success": True, "error": None}
    mock_streaming.assert_called_once_with(
        ["sudo", "usermod", "-aG", "docker", "sentinel"], "sink"
    )


def test_run_privileged_streams_sudo_prefix_and_nonzero_exit():

    with patch("installer.shell.os.geteuid", return_value=1000), patch(
        "installer.shell.shutil.which", return_value="/usr/bin/sudo"
    ), patch(
        "installer.shell.run_streaming", return_value=1
    ) as mock_streaming:

        set_stream_sink("sink")
        try:
            result = run_privileged(["systemctl", "restart", "docker"])
        finally:
            clear_stream_sink()

    assert result == {"success": False, "error": "exit code 1"}
    mock_streaming.assert_called_once_with(
        ["sudo", "systemctl", "restart", "docker"], "sink"
    )


def test_run_streaming_tees_lines_and_returns_exit_code():

    class FakeProc:
        def __init__(self):
            self.returncode = 3
            self.stdout = iter(["one\n", "two\n", "three\n"])

        def wait(self):
            pass

    with patch("installer.shell.subprocess.Popen", return_value=FakeProc()) as mock_popen:

        lines = []
        code = run_streaming(["some", "cmd"], lines.append)

    assert lines == ["one", "two", "three"]
    assert code == 3
    mock_popen.assert_called_once_with(
        ["some", "cmd"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )


def test_run_streaming_strips_trailing_newline_only():

    class FakeProc:
        def __init__(self):
            self.returncode = 0
            self.stdout = iter(["  keep  \n", "  keep  \n"])

        def wait(self):
            pass

    with patch("installer.shell.subprocess.Popen", return_value=FakeProc()):

        lines = []
        run_streaming(["some", "cmd"], lines.append)

    assert lines == ["  keep  ", "  keep  "]


def test_run_streaming_returns_127_when_command_missing():

    with patch("installer.shell.subprocess.Popen", side_effect=OSError("no such file")):

        assert run_streaming(["nonexistent-tool"], lambda line: None) == 127


def test_stream_sink_defaults_to_none_and_clears():

    assert get_stream_sink() is None

    set_stream_sink("sink")

    assert get_stream_sink() == "sink"

    clear_stream_sink()

    assert get_stream_sink() is None
