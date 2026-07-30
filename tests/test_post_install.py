import tarfile
from unittest.mock import MagicMock, patch

from installer.post_install import backup_stack, update_stack


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
