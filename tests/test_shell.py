from unittest.mock import MagicMock, patch

from installer.shell import run_ok, run_privileged


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
