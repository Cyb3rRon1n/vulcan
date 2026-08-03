import io
import tarfile
from unittest.mock import MagicMock, patch

from installer.post_install import backup_stack, latest_backup, pull_stack, restore_stack, update_stack


def test_pull_stack_failure_reports_clean_error():

    pull_proc = MagicMock(returncode=1)

    with patch(
        "installer.post_install.run_docker_command", return_value=pull_proc
    ) as mock_run:

        result = pull_stack("stack/docker-compose.yml", "stack/.env")

    assert result == {
        "success": False,
        "error": "Failed to pull images - check `docker compose logs`."
    }
    mock_run.assert_called_once()

    args = mock_run.call_args[0][0]
    assert args[-1] == "pull"


def test_pull_stack_success():

    pull_proc = MagicMock(returncode=0)

    with patch("installer.post_install.run_docker_command", return_value=pull_proc):

        result = pull_stack("stack/docker-compose.yml", "stack/.env")

    assert result == {"success": True, "error": None}


def test_update_stack_pull_failure_short_circuits_before_up():

    pull_proc = MagicMock(returncode=1)

    with patch(
        "installer.post_install.run_docker_command", return_value=pull_proc
    ) as mock_run:

        result = update_stack("stack/docker-compose.yml", "stack/.env")

    assert result == {
        "success": False,
        "error": "Failed to pull images - check `docker compose logs`."
    }
    mock_run.assert_called_once()

    args = mock_run.call_args[0][0]
    assert args[-1] == "pull"


def test_update_stack_up_failure_after_successful_pull():

    pull_proc = MagicMock(returncode=0)
    up_proc = MagicMock(returncode=1)

    with patch(
        "installer.post_install.run_docker_command", side_effect=[pull_proc, up_proc]
    ) as mock_run:

        result = update_stack("stack/docker-compose.yml", "stack/.env")

    assert result == {
        "success": False,
        "error": "Failed to recreate containers - check `docker compose logs`."
    }
    assert mock_run.call_count == 2

    second_args = mock_run.call_args_list[1][0][0]
    assert second_args[-2:] == ["up", "-d"]


def test_update_stack_full_success():

    pull_proc = MagicMock(returncode=0)
    up_proc = MagicMock(returncode=0)

    with patch(
        "installer.post_install.run_docker_command", side_effect=[pull_proc, up_proc]
    ):

        result = update_stack("stack/docker-compose.yml", "stack/.env")

    assert result == {"success": True, "error": None}


def test_backup_stack_no_stack_present(tmp_path):

    result = backup_stack(
        stack_dir=tmp_path / "stack", backup_dir=tmp_path / "backups"
    )

    assert result == {
        "success": False,
        "error": "No stack found to back up.",
        "backup_path": None,
        "warnings": []
    }


def test_backup_stack_creates_real_archive_with_expected_contents(tmp_path):

    stack_dir = tmp_path / "stack"
    backup_dir = tmp_path / "backups"

    (stack_dir / "config" / "jellyfin").mkdir(parents=True)
    (stack_dir / "config" / "jellyfin" / "settings.xml").write_text("<config/>")
    (stack_dir / "config" / "radarr").mkdir(parents=True)
    (stack_dir / "config" / "radarr" / "config.xml").write_text("<config/>")
    (stack_dir / "docker-compose.yml").write_text("services: {}\n")
    (stack_dir / ".env").write_text("PUID=1000\n")

    result = backup_stack(stack_dir=stack_dir, backup_dir=backup_dir)

    assert result["success"] is True
    assert result["error"] is None

    backup_path = result["backup_path"]
    assert backup_path is not None
    assert backup_path.endswith(".tar.gz")

    with tarfile.open(backup_path, "r:gz") as tar:

        names = set(tar.getnames())

        assert "docker-compose.yml" in names
        assert ".env" in names
        assert "config/jellyfin/settings.xml" in names
        assert "config/radarr/config.xml" in names

        env_member = tar.extractfile(".env")
        assert env_member.read().decode() == "PUID=1000\n"


def test_backup_stack_warns_about_env_secrets(tmp_path):

    stack_dir = tmp_path / "stack"
    (stack_dir / "config").mkdir(parents=True)
    (stack_dir / "docker-compose.yml").write_text("services: {}\n")
    (stack_dir / ".env").write_text("PUID=1000\n")

    result = backup_stack(stack_dir=stack_dir, backup_dir=tmp_path / "backups")

    assert result["warnings"] != []
    assert ".env" in result["warnings"][0]
    assert "credentials" in result["warnings"][0]


def test_latest_backup_returns_none_when_directory_missing(tmp_path):

    assert latest_backup(tmp_path / "backups") is None


def test_latest_backup_returns_none_when_directory_empty(tmp_path):

    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()

    assert latest_backup(backup_dir) is None


def test_latest_backup_returns_lexicographically_latest_match(tmp_path):

    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()

    (backup_dir / "vulcan-backup-20260101T000000Z.tar.gz").write_text("old")
    (backup_dir / "vulcan-backup-20260301T120000Z.tar.gz").write_text("newest")
    (backup_dir / "vulcan-backup-20260215T000000Z.tar.gz").write_text("middle")
    (backup_dir / "not-a-backup.txt").write_text("ignored")

    result = latest_backup(backup_dir)

    assert result == backup_dir / "vulcan-backup-20260301T120000Z.tar.gz"


def test_restore_stack_missing_backup_file(tmp_path):

    result = restore_stack(
        tmp_path / "nope.tar.gz",
        str(tmp_path / "stack" / "docker-compose.yml"),
        str(tmp_path / "stack" / ".env"),
        stack_dir=tmp_path / "stack"
    )

    assert result == {
        "success": False,
        "error": f"Backup file not found: {tmp_path / 'nope.tar.gz'}"
    }


def test_restore_stack_invalid_archive_reports_clean_error(tmp_path):

    bogus = tmp_path / "bogus.tar.gz"
    bogus.write_text("this is not a real tar archive")

    with patch("installer.post_install.run_docker_command") as mock_run:

        result = restore_stack(
            bogus,
            str(tmp_path / "stack" / "docker-compose.yml"),
            str(tmp_path / "stack" / ".env"),
            stack_dir=tmp_path / "stack"
        )

    assert result["success"] is False
    assert "bogus.tar.gz" in result["error"]
    assert "valid backup archive" in result["error"]
    mock_run.assert_not_called()


def test_restore_stack_extracts_real_archive_and_overwrites_stale_content(tmp_path):

    stack_dir = tmp_path / "stack"

    (stack_dir / "config" / "jellyfin").mkdir(parents=True)
    (stack_dir / "config" / "jellyfin" / "settings.xml").write_text("<old/>")
    (stack_dir / "docker-compose.yml").write_text("services: {stale: true}\n")
    (stack_dir / ".env").write_text("PUID=9999\n")

    backup_path = tmp_path / "backups" / "vulcan-backup-20260101T000000Z.tar.gz"
    backup_path.parent.mkdir(parents=True)

    fresh_dir = tmp_path / "fresh"
    (fresh_dir / "config" / "jellyfin").mkdir(parents=True)
    (fresh_dir / "config" / "jellyfin" / "settings.xml").write_text("<new/>")
    (fresh_dir / "docker-compose.yml").write_text("services: {stale: false}\n")
    (fresh_dir / ".env").write_text("PUID=1000\n")

    with tarfile.open(backup_path, "w:gz") as tar:
        tar.add(fresh_dir / "config", arcname="config")
        tar.add(fresh_dir / "docker-compose.yml", arcname="docker-compose.yml")
        tar.add(fresh_dir / ".env", arcname=".env")

    down_proc = MagicMock(returncode=0)

    with patch("installer.post_install.run_docker_command", return_value=down_proc):

        result = restore_stack(
            backup_path,
            str(stack_dir / "docker-compose.yml"),
            str(stack_dir / ".env"),
            stack_dir=stack_dir
        )

    assert result == {"success": True, "error": None}
    assert (stack_dir / "config" / "jellyfin" / "settings.xml").read_text() == "<new/>"
    assert (stack_dir / "docker-compose.yml").read_text() == "services: {stale: false}\n"
    assert (stack_dir / ".env").read_text() == "PUID=1000\n"


def test_restore_stack_removes_stray_files_not_in_the_archive(tmp_path):

    stack_dir = tmp_path / "stack"

    (stack_dir / "config" / "jellyfin").mkdir(parents=True)
    (stack_dir / "config" / "jellyfin" / "settings.xml").write_text("<old/>")
    (stack_dir / "config" / "jellyfin" / "drift-marker.txt").write_text("added after the backup")
    (stack_dir / "config" / "orphaned-service").mkdir(parents=True)
    (stack_dir / "config" / "orphaned-service" / "leftover.txt").write_text("no longer enabled")
    (stack_dir / "docker-compose.yml").write_text("services: {stale: true}\n")
    (stack_dir / ".env").write_text("PUID=9999\n")

    backup_path = tmp_path / "vulcan-backup-20260101T000000Z.tar.gz"

    fresh_dir = tmp_path / "fresh"
    (fresh_dir / "config" / "jellyfin").mkdir(parents=True)
    (fresh_dir / "config" / "jellyfin" / "settings.xml").write_text("<new/>")
    (fresh_dir / "docker-compose.yml").write_text("services: {stale: false}\n")
    (fresh_dir / ".env").write_text("PUID=1000\n")

    with tarfile.open(backup_path, "w:gz") as tar:
        tar.add(fresh_dir / "config", arcname="config")
        tar.add(fresh_dir / "docker-compose.yml", arcname="docker-compose.yml")
        tar.add(fresh_dir / ".env", arcname=".env")

    down_proc = MagicMock(returncode=0)

    with patch("installer.post_install.run_docker_command", return_value=down_proc):

        result = restore_stack(
            backup_path,
            str(stack_dir / "docker-compose.yml"),
            str(stack_dir / ".env"),
            stack_dir=stack_dir
        )

    assert result == {"success": True, "error": None}
    assert not (stack_dir / "config" / "jellyfin" / "drift-marker.txt").exists()
    assert not (stack_dir / "config" / "orphaned-service").exists()
    assert (stack_dir / "config" / "jellyfin" / "settings.xml").read_text() == "<new/>"


def test_restore_stack_stops_running_stack_before_extracting(tmp_path):

    stack_dir = tmp_path / "stack"
    stack_dir.mkdir()
    (stack_dir / "docker-compose.yml").write_text("services: {}\n")
    (stack_dir / ".env").write_text("PUID=1000\n")

    backup_path = tmp_path / "vulcan-backup-20260101T000000Z.tar.gz"

    with tarfile.open(backup_path, "w:gz") as tar:
        info = tarfile.TarInfo(name="docker-compose.yml")
        content = b"services: {}\n"
        info.size = len(content)

        tar.addfile(info, io.BytesIO(content))

    down_proc = MagicMock(returncode=0)

    with patch("installer.post_install.run_docker_command", return_value=down_proc) as mock_run:

        result = restore_stack(
            backup_path,
            str(stack_dir / "docker-compose.yml"),
            str(stack_dir / ".env"),
            stack_dir=stack_dir
        )

    assert result["success"] is True
    mock_run.assert_called_once()

    args = mock_run.call_args[0][0]
    assert args[-1] == "down"
    assert str(stack_dir / "docker-compose.yml") in args


def test_restore_stack_skips_down_when_no_existing_compose_file(tmp_path):

    stack_dir = tmp_path / "stack"

    backup_path = tmp_path / "vulcan-backup-20260101T000000Z.tar.gz"

    with tarfile.open(backup_path, "w:gz") as tar:
        info = tarfile.TarInfo(name="docker-compose.yml")
        content = b"services: {}\n"
        info.size = len(content)

        tar.addfile(info, io.BytesIO(content))

    with patch("installer.post_install.run_docker_command") as mock_run:

        result = restore_stack(
            backup_path,
            str(stack_dir / "docker-compose.yml"),
            str(stack_dir / ".env"),
            stack_dir=stack_dir
        )

    assert result["success"] is True
    mock_run.assert_not_called()


def test_restore_stack_down_failure_stops_before_touching_files(tmp_path):

    stack_dir = tmp_path / "stack"
    stack_dir.mkdir()
    (stack_dir / "docker-compose.yml").write_text("services: {stale: true}\n")
    (stack_dir / ".env").write_text("PUID=9999\n")

    backup_path = tmp_path / "vulcan-backup-20260101T000000Z.tar.gz"

    with tarfile.open(backup_path, "w:gz") as tar:
        info = tarfile.TarInfo(name="docker-compose.yml")
        content = b"services: {stale: false}\n"
        info.size = len(content)

        tar.addfile(info, io.BytesIO(content))

    down_proc = MagicMock(returncode=1)

    with patch("installer.post_install.run_docker_command", return_value=down_proc):

        result = restore_stack(
            backup_path,
            str(stack_dir / "docker-compose.yml"),
            str(stack_dir / ".env"),
            stack_dir=stack_dir
        )

    assert result["success"] is False
    assert "Failed to stop the running stack" in result["error"]
    assert (stack_dir / "docker-compose.yml").read_text() == "services: {stale: true}\n"
