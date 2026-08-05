import io
import sqlite3
import tarfile
from unittest.mock import MagicMock, patch

from installer.post_install import (
    backup_stack,
    export_images,
    import_images,
    latest_backup,
    latest_export,
    pull_stack,
    remove_orphaned_containers,
    restore_stack,
    stack_containers_exist,
    uninstall_stack,
    update_stack,
)


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


def test_export_images_no_stack_found(tmp_path):

    result = export_images(
        str(tmp_path / "stack" / "docker-compose.yml"), str(tmp_path / "stack" / ".env")
    )

    assert result == {"success": False, "error": "No stack found to export.", "export_path": None}


def test_export_images_list_failure(tmp_path):

    compose_path = tmp_path / "stack" / "docker-compose.yml"
    compose_path.parent.mkdir(parents=True)
    compose_path.write_text("services: {}\n")

    list_proc = MagicMock(returncode=1, stdout="")

    with patch("installer.post_install.subprocess.run", return_value=list_proc):

        result = export_images(str(compose_path), str(tmp_path / "stack" / ".env"))

    assert result == {
        "success": False,
        "error": "Failed to resolve the stack's image list.",
        "export_path": None
    }


def test_export_images_no_images_found(tmp_path):

    compose_path = tmp_path / "stack" / "docker-compose.yml"
    compose_path.parent.mkdir(parents=True)
    compose_path.write_text("services: {}\n")

    list_proc = MagicMock(returncode=0, stdout="\n")

    with patch("installer.post_install.subprocess.run", return_value=list_proc):

        result = export_images(str(compose_path), str(tmp_path / "stack" / ".env"))

    assert result == {"success": False, "error": "No images found for this stack.", "export_path": None}


def test_export_images_save_failure(tmp_path):

    compose_path = tmp_path / "stack" / "docker-compose.yml"
    compose_path.parent.mkdir(parents=True)
    compose_path.write_text("services: {}\n")

    list_proc = MagicMock(returncode=0, stdout="alpine:3.19\nbusybox:1.36\n")
    save_proc = MagicMock(returncode=1)

    with patch("installer.post_install.subprocess.run", return_value=list_proc), patch(
        "installer.post_install.run_docker_command", return_value=save_proc
    ) as mock_run:

        result = export_images(
            str(compose_path), str(tmp_path / "stack" / ".env"), export_dir=tmp_path / "exports"
        )

    assert result == {"success": False, "error": "Failed to save images to a tarball.", "export_path": None}

    args = mock_run.call_args[0][0]
    assert args[:2] == ["docker", "save"]
    assert "alpine:3.19" in args
    assert "busybox:1.36" in args


def test_export_images_success_writes_timestamped_default_path(tmp_path):

    compose_path = tmp_path / "stack" / "docker-compose.yml"
    compose_path.parent.mkdir(parents=True)
    compose_path.write_text("services: {}\n")

    list_proc = MagicMock(returncode=0, stdout="alpine:3.19\n")
    save_proc = MagicMock(returncode=0)

    with patch("installer.post_install.subprocess.run", return_value=list_proc), patch(
        "installer.post_install.run_docker_command", return_value=save_proc
    ):

        result = export_images(
            str(compose_path), str(tmp_path / "stack" / ".env"), export_dir=tmp_path / "exports"
        )

    assert result["success"] is True
    assert result["error"] is None
    assert result["export_path"].startswith(str(tmp_path / "exports" / "vulcan-images-"))
    assert result["export_path"].endswith(".tar")


def test_export_images_success_with_explicit_output_path(tmp_path):

    compose_path = tmp_path / "stack" / "docker-compose.yml"
    compose_path.parent.mkdir(parents=True)
    compose_path.write_text("services: {}\n")

    list_proc = MagicMock(returncode=0, stdout="alpine:3.19\n")
    save_proc = MagicMock(returncode=0)
    output_path = tmp_path / "custom" / "images.tar"

    with patch("installer.post_install.subprocess.run", return_value=list_proc), patch(
        "installer.post_install.run_docker_command", return_value=save_proc
    ):

        result = export_images(
            str(compose_path), str(tmp_path / "stack" / ".env"), output_path=output_path
        )

    assert result == {"success": True, "error": None, "export_path": str(output_path)}
    assert output_path.parent.is_dir()


def test_latest_export_returns_none_when_directory_missing(tmp_path):

    assert latest_export(tmp_path / "exports") is None


def test_latest_export_returns_none_when_directory_empty(tmp_path):

    export_dir = tmp_path / "exports"
    export_dir.mkdir()

    assert latest_export(export_dir) is None


def test_latest_export_returns_lexicographically_latest_match(tmp_path):

    export_dir = tmp_path / "exports"
    export_dir.mkdir()

    (export_dir / "vulcan-images-20260101T000000Z.tar").write_text("old")
    (export_dir / "vulcan-images-20260301T120000Z.tar").write_text("newest")
    (export_dir / "vulcan-images-20260215T000000Z.tar").write_text("middle")
    (export_dir / "not-an-export.txt").write_text("ignored")

    result = latest_export(export_dir)

    assert result == export_dir / "vulcan-images-20260301T120000Z.tar"


def test_import_images_missing_archive(tmp_path):

    result = import_images(str(tmp_path / "does-not-exist.tar"))

    assert result == {
        "success": False,
        "error": f"Image archive not found: {tmp_path / 'does-not-exist.tar'}"
    }


def test_import_images_load_failure(tmp_path):

    tar_path = tmp_path / "images.tar"
    tar_path.write_text("not a real tar, just needs to exist")

    load_proc = MagicMock(returncode=1)

    with patch("installer.post_install.run_docker_command", return_value=load_proc) as mock_run:

        result = import_images(str(tar_path))

    assert result == {"success": False, "error": "Failed to load images from the archive."}

    args = mock_run.call_args[0][0]
    assert args == ["docker", "load", "-i", str(tar_path)]


def test_import_images_success(tmp_path):

    tar_path = tmp_path / "images.tar"
    tar_path.write_text("not a real tar, just needs to exist")

    load_proc = MagicMock(returncode=0)

    with patch("installer.post_install.run_docker_command", return_value=load_proc):

        result = import_images(str(tar_path))

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


def test_backup_stack_snapshots_live_sqlite_database_safely(tmp_path):

    stack_dir = tmp_path / "stack"
    backup_dir = tmp_path / "backups"

    db_path = stack_dir / "config" / "radarr" / "radarr.db"
    db_path.parent.mkdir(parents=True)

    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE Movies (Id INTEGER PRIMARY KEY, Title TEXT)")
    conn.execute("INSERT INTO Movies (Title) VALUES ('Real Movie')")
    conn.commit()
    conn.close()

    (stack_dir / "docker-compose.yml").write_text("services: {}\n")
    (stack_dir / ".env").write_text("PUID=1000\n")

    result = backup_stack(stack_dir=stack_dir, backup_dir=backup_dir)

    assert result["success"] is True
    assert not any("Could not safely snapshot" in w for w in result["warnings"])

    with tarfile.open(result["backup_path"], "r:gz") as tar:
        tar.extract("config/radarr/radarr.db", path=tmp_path / "extracted", filter="data")

    extracted_db = tmp_path / "extracted" / "config" / "radarr" / "radarr.db"

    conn = sqlite3.connect(extracted_db)
    assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    assert conn.execute("SELECT Title FROM Movies").fetchone() == ("Real Movie",)
    conn.close()


def test_backup_stack_falls_back_to_plain_copy_on_snapshot_failure(tmp_path):

    stack_dir = tmp_path / "stack"
    backup_dir = tmp_path / "backups"

    db_path = stack_dir / "config" / "radarr" / "radarr.db"
    db_path.parent.mkdir(parents=True)

    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE Movies (Id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()
    original_bytes = db_path.read_bytes()

    (stack_dir / "docker-compose.yml").write_text("services: {}\n")
    (stack_dir / ".env").write_text("PUID=1000\n")

    with patch(
        "installer.post_install._snapshot_sqlite_database", return_value=False
    ):

        result = backup_stack(stack_dir=stack_dir, backup_dir=backup_dir)

    assert result["success"] is True
    assert any("Could not safely snapshot" in w for w in result["warnings"])
    assert any("radarr/radarr.db" in w for w in result["warnings"])

    with tarfile.open(result["backup_path"], "r:gz") as tar:
        tar.extract("config/radarr/radarr.db", path=tmp_path / "extracted", filter="data")

    extracted_db = tmp_path / "extracted" / "config" / "radarr" / "radarr.db"
    assert extracted_db.read_bytes() == original_bytes


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


def test_uninstall_stack_stops_running_stack_and_removes_stack_dir(tmp_path):

    stack_dir = tmp_path / "stack"
    stack_dir.mkdir()
    (stack_dir / "docker-compose.yml").write_text("services: {}\n")
    (stack_dir / ".env").write_text("PUID=1000\n")
    (stack_dir / "config" / "jellyfin").mkdir(parents=True)

    down_proc = MagicMock(returncode=0)

    with patch("installer.post_install.run_docker_command", return_value=down_proc) as mock_run:

        result = uninstall_stack(
            str(stack_dir / "docker-compose.yml"),
            str(stack_dir / ".env"),
            stack_dir=stack_dir,
            backup_dir=tmp_path / "backups",
            export_dir=tmp_path / "exports"
        )

    assert result == {"success": True, "error": None}

    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert args[-1] == "down"
    assert str(stack_dir / "docker-compose.yml") in args

    assert not stack_dir.exists()


def test_uninstall_stack_skips_down_when_no_existing_compose_file(tmp_path):

    stack_dir = tmp_path / "stack"
    stack_dir.mkdir()
    (stack_dir / "config" / "jellyfin").mkdir(parents=True)

    with patch("installer.post_install.run_docker_command") as mock_run:

        result = uninstall_stack(
            str(stack_dir / "docker-compose.yml"),
            str(stack_dir / ".env"),
            stack_dir=stack_dir,
            backup_dir=tmp_path / "backups",
            export_dir=tmp_path / "exports"
        )

    assert result == {"success": True, "error": None}
    mock_run.assert_not_called()
    assert not stack_dir.exists()


def test_uninstall_stack_down_failure_leaves_stack_dir_untouched(tmp_path):

    stack_dir = tmp_path / "stack"
    stack_dir.mkdir()
    (stack_dir / "docker-compose.yml").write_text("services: {}\n")
    (stack_dir / ".env").write_text("PUID=1000\n")

    down_proc = MagicMock(returncode=1)

    with patch("installer.post_install.run_docker_command", return_value=down_proc):

        result = uninstall_stack(
            str(stack_dir / "docker-compose.yml"),
            str(stack_dir / ".env"),
            stack_dir=stack_dir,
            backup_dir=tmp_path / "backups",
            export_dir=tmp_path / "exports"
        )

    assert result["success"] is False
    assert "Failed to stop the running stack" in result["error"]
    assert stack_dir.exists()


def test_uninstall_stack_leaves_backups_and_exports_by_default(tmp_path):

    stack_dir = tmp_path / "stack"
    stack_dir.mkdir()

    backup_dir = tmp_path / "backups"
    export_dir = tmp_path / "exports"
    backup_dir.mkdir()
    export_dir.mkdir()
    (backup_dir / "vulcan-backup-20260101T000000Z.tar.gz").write_text("fake")
    (export_dir / "vulcan-images-20260101T000000Z.tar").write_text("fake")

    result = uninstall_stack(
        str(stack_dir / "docker-compose.yml"),
        str(stack_dir / ".env"),
        stack_dir=stack_dir,
        backup_dir=backup_dir,
        export_dir=export_dir
    )

    assert result["success"] is True
    assert not stack_dir.exists()
    assert backup_dir.exists()
    assert export_dir.exists()


def test_uninstall_stack_purge_artifacts_removes_backups_and_exports(tmp_path):

    stack_dir = tmp_path / "stack"
    stack_dir.mkdir()

    backup_dir = tmp_path / "backups"
    export_dir = tmp_path / "exports"
    backup_dir.mkdir()
    export_dir.mkdir()
    (backup_dir / "vulcan-backup-20260101T000000Z.tar.gz").write_text("fake")
    (export_dir / "vulcan-images-20260101T000000Z.tar").write_text("fake")

    result = uninstall_stack(
        str(stack_dir / "docker-compose.yml"),
        str(stack_dir / ".env"),
        stack_dir=stack_dir,
        backup_dir=backup_dir,
        export_dir=export_dir,
        purge_artifacts=True
    )

    assert result["success"] is True
    assert not stack_dir.exists()
    assert not backup_dir.exists()
    assert not export_dir.exists()


def test_uninstall_stack_purge_artifacts_no_op_when_dirs_absent(tmp_path):

    stack_dir = tmp_path / "stack"
    stack_dir.mkdir()

    result = uninstall_stack(
        str(stack_dir / "docker-compose.yml"),
        str(stack_dir / ".env"),
        stack_dir=stack_dir,
        backup_dir=tmp_path / "backups",
        export_dir=tmp_path / "exports",
        purge_artifacts=True
    )

    assert result == {"success": True, "error": None}
    assert not stack_dir.exists()


def test_uninstall_stack_falls_back_to_docker_removal_on_permission_error(tmp_path):

    stack_dir = tmp_path / "stack"
    stack_dir.mkdir()

    with patch(
        "installer.post_install.shutil.rmtree", side_effect=[PermissionError(), None]
    ) as mock_rmtree, patch(
        "installer.post_install.run_docker_command"
    ) as mock_run:

        result = uninstall_stack(
            str(stack_dir / "docker-compose.yml"),
            str(stack_dir / ".env"),
            stack_dir=stack_dir,
            backup_dir=tmp_path / "backups",
            export_dir=tmp_path / "exports"
        )

    assert result == {"success": True, "error": None}
    assert mock_rmtree.call_count == 2

    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert args[:3] == ["docker", "run", "--rm"]
    assert f"{stack_dir.resolve()}:/target" in args


def test_stack_containers_exist_true_when_docker_reports_a_container():

    proc = MagicMock(returncode=0, stdout="abc123def456\n")

    with patch("installer.post_install.subprocess.run", return_value=proc) as mock_run:
        result = stack_containers_exist("stack")

    assert result is True

    args = mock_run.call_args[0][0]
    assert args[:3] == ["docker", "ps", "-a"]
    assert "label=com.docker.compose.project=stack" in args


def test_stack_containers_exist_false_when_docker_reports_nothing():

    proc = MagicMock(returncode=0, stdout="")

    with patch("installer.post_install.subprocess.run", return_value=proc):
        result = stack_containers_exist("stack")

    assert result is False


def test_remove_orphaned_containers_success():

    proc = MagicMock(returncode=0)

    with patch("installer.post_install.run_docker_command", return_value=proc) as mock_run:
        result = remove_orphaned_containers("stack")

    assert result == {"success": True, "error": None}

    args = mock_run.call_args[0][0]
    assert args == ["docker", "compose", "-p", "stack", "down"]


def test_remove_orphaned_containers_failure():

    proc = MagicMock(returncode=1)

    with patch("installer.post_install.run_docker_command", return_value=proc):
        result = remove_orphaned_containers("stack")

    assert result["success"] is False
    assert "Failed to stop orphaned containers" in result["error"]


def test_remove_orphaned_containers_never_touches_stack_dir(tmp_path):
    """
    The real reason this is a separate function from uninstall_stack(),
    not a call to it: this is used mid-port-conflict-remediation, where
    stack/ holds the *freshly generated* compose file the current run
    is trying to start, not a stale one - uninstall_stack()'s own
    unconditional _remove_stack_dir() would delete it.
    """

    stack_dir = tmp_path / "stack"
    stack_dir.mkdir()
    (stack_dir / "docker-compose.yml").write_text("services: {}\n")

    proc = MagicMock(returncode=0)

    with patch("installer.post_install.run_docker_command", return_value=proc):
        remove_orphaned_containers("stack")

    assert (stack_dir / "docker-compose.yml").exists()


def test_uninstall_stack_falls_back_to_project_teardown_when_stack_dir_already_gone(tmp_path):
    """
    stack/ was deleted through some means other than a real
    `vulcan uninstall` run (confirmed a real, recurring scenario) -
    docker compose down needs no compose file, only the project name,
    to stop containers still carrying its labels.
    """

    stack_dir = tmp_path / "stack"

    down_proc = MagicMock(returncode=0)

    with patch(
        "installer.post_install.stack_containers_exist", return_value=True
    ), patch(
        "installer.post_install.run_docker_command", return_value=down_proc
    ) as mock_run:

        result = uninstall_stack(
            str(stack_dir / "docker-compose.yml"),
            str(stack_dir / ".env"),
            stack_dir=stack_dir,
            backup_dir=tmp_path / "backups",
            export_dir=tmp_path / "exports"
        )

    assert result == {"success": True, "error": None}

    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert args == ["docker", "compose", "-p", "stack", "down"]


def test_uninstall_stack_orphan_teardown_failure_reports_clean_error(tmp_path):

    stack_dir = tmp_path / "stack"

    down_proc = MagicMock(returncode=1)

    with patch(
        "installer.post_install.stack_containers_exist", return_value=True
    ), patch(
        "installer.post_install.run_docker_command", return_value=down_proc
    ):

        result = uninstall_stack(
            str(stack_dir / "docker-compose.yml"),
            str(stack_dir / ".env"),
            stack_dir=stack_dir,
            backup_dir=tmp_path / "backups",
            export_dir=tmp_path / "exports"
        )

    assert result["success"] is False
    assert "Failed to stop orphaned containers" in result["error"]


def test_uninstall_stack_skips_orphan_lookup_when_stack_dir_and_no_containers(tmp_path):

    stack_dir = tmp_path / "stack"

    with patch(
        "installer.post_install.stack_containers_exist", return_value=False
    ), patch(
        "installer.post_install.run_docker_command"
    ) as mock_run:

        result = uninstall_stack(
            str(stack_dir / "docker-compose.yml"),
            str(stack_dir / ".env"),
            stack_dir=stack_dir,
            backup_dir=tmp_path / "backups",
            export_dir=tmp_path / "exports"
        )

    assert result == {"success": True, "error": None}
    mock_run.assert_not_called()
