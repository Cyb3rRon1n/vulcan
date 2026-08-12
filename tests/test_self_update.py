from pathlib import Path
from unittest.mock import MagicMock, patch

from installer.self_update import update_vulcan_self


def _proc(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:

    proc = MagicMock()
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = stderr

    return proc


def test_update_vulcan_self_not_a_git_repo():

    with patch("installer.self_update._run", return_value=_proc(returncode=1)):

        result = update_vulcan_self(Path("/nonexistent"))

    assert result["success"] is False
    assert "doesn't look like a git checkout" in result["error"]


def test_update_vulcan_self_fetch_failure():

    def fake_run(args, cwd):

        if args[:2] == ["git", "rev-parse"] and "--is-inside-work-tree" in args:
            return _proc(returncode=0)
        if args[:2] == ["git", "fetch"]:
            return _proc(returncode=1, stderr="unable to access origin")

        return _proc(returncode=0)

    with patch("installer.self_update._run", side_effect=fake_run):
        result = update_vulcan_self(Path("."))

    assert result["success"] is False
    assert "Failed to check for updates" in result["error"]
    assert "unable to access origin" in result["error"]


def test_update_vulcan_self_already_up_to_date():

    def fake_run(args, cwd):

        if args == ["git", "rev-parse", "--is-inside-work-tree"]:
            return _proc(returncode=0)
        if args == ["git", "fetch", "origin", "main"]:
            return _proc(returncode=0)
        if args == ["git", "rev-parse", "--short", "HEAD"]:
            return _proc(returncode=0, stdout="abc1234\n")
        if args == ["git", "rev-list", "HEAD..origin/main", "--count"]:
            return _proc(returncode=0, stdout="0\n")

        raise AssertionError(f"unexpected call: {args}")

    with patch("installer.self_update._run", side_effect=fake_run):
        result = update_vulcan_self(Path("."))

    assert result["success"] is True
    assert result["updated"] is False
    assert result["commit"] == "abc1234"


def test_update_vulcan_self_pull_failure_reports_divergence():

    def fake_run(args, cwd):

        if args == ["git", "rev-parse", "--is-inside-work-tree"]:
            return _proc(returncode=0)
        if args == ["git", "fetch", "origin", "main"]:
            return _proc(returncode=0)
        if args == ["git", "rev-parse", "--short", "HEAD"]:
            return _proc(returncode=0, stdout="abc1234\n")
        if args == ["git", "rev-list", "HEAD..origin/main", "--count"]:
            return _proc(returncode=0, stdout="2\n")
        if args == ["git", "pull", "--ff-only", "origin", "main"]:
            return _proc(returncode=1, stderr="Not possible to fast-forward")

        raise AssertionError(f"unexpected call: {args}")

    with patch("installer.self_update._run", side_effect=fake_run):
        result = update_vulcan_self(Path("."))

    assert result["success"] is False
    assert "diverged" in result["error"]
    assert "Not possible to fast-forward" in result["error"]


def test_update_vulcan_self_pip_reinstall_failure():

    def fake_run(args, cwd):

        if args == ["git", "rev-parse", "--is-inside-work-tree"]:
            return _proc(returncode=0)
        if args == ["git", "fetch", "origin", "main"]:
            return _proc(returncode=0)
        if args == ["git", "rev-parse", "--short", "HEAD"]:
            return _proc(returncode=0, stdout="abc1234\n")
        if args == ["git", "rev-list", "HEAD..origin/main", "--count"]:
            return _proc(returncode=0, stdout="2\n")
        if args == ["git", "pull", "--ff-only", "origin", "main"]:
            return _proc(returncode=0)

        raise AssertionError(f"unexpected call: {args}")

    with patch("installer.self_update._run", side_effect=fake_run), patch(
        "installer.self_update.subprocess.run",
        return_value=_proc(returncode=1, stderr="No matching distribution found")
    ):
        result = update_vulcan_self(Path("."))

    assert result["success"] is False
    assert "reinstalling dependencies failed" in result["error"]


def test_update_vulcan_self_success_reports_old_and_new_commit():

    call_count = {"rev_parse_head": 0}

    def fake_run(args, cwd):

        if args == ["git", "rev-parse", "--is-inside-work-tree"]:
            return _proc(returncode=0)
        if args == ["git", "fetch", "origin", "main"]:
            return _proc(returncode=0)
        if args == ["git", "rev-parse", "--short", "HEAD"]:
            call_count["rev_parse_head"] += 1
            commit = "abc1234" if call_count["rev_parse_head"] == 1 else "def5678"
            return _proc(returncode=0, stdout=f"{commit}\n")
        if args == ["git", "rev-list", "HEAD..origin/main", "--count"]:
            return _proc(returncode=0, stdout="2\n")
        if args == ["git", "pull", "--ff-only", "origin", "main"]:
            return _proc(returncode=0)

        raise AssertionError(f"unexpected call: {args}")

    with patch("installer.self_update._run", side_effect=fake_run), patch(
        "installer.self_update.subprocess.run", return_value=_proc(returncode=0)
    ):
        result = update_vulcan_self(Path("."))

    assert result["success"] is True
    assert result["updated"] is True
    assert result["old_commit"] == "abc1234"
    assert result["new_commit"] == "def5678"
