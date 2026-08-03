"""
Post-install operations on an already-generated stack: pulling images
without starting anything (pull_stack), pulling fresh images and
recreating containers (update_stack, which just calls pull_stack for
its own pull step), archiving config for safekeeping (backup_stack),
and reversing that archive back onto disk (restore_stack). All of
these reuse the same real Docker/file primitives generation already
does - run_docker_command() for the subprocess calls, the same
STACK_DIR every other command reads from - no new machinery, just
more things to do with a stack that already exists.
"""

import shutil
import tarfile
from datetime import datetime
from datetime import timezone as dt_timezone
from pathlib import Path

from installer.docker_setup import run_docker_command
from installer.generate import STACK_DIR


def pull_stack(compose_path: str, env_path: str) -> dict:

    pull = run_docker_command(
        ["docker", "compose", "-f", compose_path, "--env-file", env_path, "pull"]
    )

    if pull.returncode != 0:
        return {"success": False, "error": "Failed to pull images - check `docker compose logs`."}

    return {"success": True, "error": None}


def update_stack(compose_path: str, env_path: str) -> dict:

    pull_result = pull_stack(compose_path, env_path)

    if not pull_result["success"]:
        return pull_result

    up = run_docker_command(
        ["docker", "compose", "-f", compose_path, "--env-file", env_path, "up", "-d"]
    )

    if up.returncode != 0:
        return {"success": False, "error": "Failed to recreate containers - check `docker compose logs`."}

    return {"success": True, "error": None}


def backup_stack(stack_dir: Path = STACK_DIR, backup_dir: Path = Path("backups")) -> dict:

    compose_path = stack_dir / "docker-compose.yml"

    if not compose_path.exists():

        return {
            "success": False,
            "error": "No stack found to back up.",
            "backup_path": None,
            "warnings": []
        }

    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_dir / f"vulcan-backup-{timestamp}.tar.gz"

    with tarfile.open(backup_path, "w:gz") as tar:

        tar.add(stack_dir / "config", arcname="config")
        tar.add(compose_path, arcname="docker-compose.yml")
        tar.add(stack_dir / ".env", arcname=".env")

    return {
        "success": True,
        "error": None,
        "backup_path": str(backup_path),
        "warnings": [
            "This backup includes stack/.env, which may contain real credentials "
            "(e.g. Gluetun VPN keys) - store the archive securely."
        ]
    }


def latest_backup(backup_dir: Path = Path("backups")) -> Path | None:

    if not backup_dir.is_dir():
        return None

    archives = sorted(backup_dir.glob("vulcan-backup-*.tar.gz"))

    return archives[-1] if archives else None


def restore_stack(
    backup_path: Path,
    compose_path: str,
    env_path: str,
    stack_dir: Path = STACK_DIR
) -> dict:

    backup_path = Path(backup_path)

    if not backup_path.exists():
        return {"success": False, "error": f"Backup file not found: {backup_path}"}

    if Path(compose_path).exists():

        down = run_docker_command(
            ["docker", "compose", "-f", compose_path, "--env-file", env_path, "down"]
        )

        if down.returncode != 0:
            return {"success": False, "error": "Failed to stop the running stack - check `docker compose logs`."}

    stack_dir.mkdir(parents=True, exist_ok=True)

    # tarfile.extractall() only ever adds/overwrites members present in the
    # archive - it never deletes files already on disk that aren't part of
    # it. Without clearing config/ first, a stray file added after the
    # backup was taken (or a service's config dir for something no longer
    # enabled) would silently survive a "restore" - confirmed by actually
    # hitting this with a real drifted file before adding the rmtree.
    config_dir = stack_dir / "config"

    if config_dir.exists():
        shutil.rmtree(config_dir)

    try:
        with tarfile.open(backup_path, "r:gz") as tar:
            tar.extractall(path=stack_dir, filter="data")
    except tarfile.TarError as error:
        return {"success": False, "error": f"'{backup_path.name}' isn't a valid backup archive: {error}"}

    return {"success": True, "error": None}
